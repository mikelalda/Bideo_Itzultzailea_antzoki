# =============================================================================
# Bideo Itzultzailea - Video Translation Backend
# Orchestrates: Whisper (STT) → Translation → Antzoki/DramaBox (TTS)
# Supports: Gaztelera ↔ Euskera
# =============================================================================

import os
import re
import uuid
import json
import time
import logging
import asyncio
import tempfile
import subprocess
from pathlib import Path
from typing import Optional

import httpx
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.requests import Request
from contextlib import asynccontextmanager
from pydantic import BaseModel

from translator import TextTranslator

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
WHISPER_API_URL = os.getenv("WHISPER_API_URL", "http://whisper-api:8000")
ANTZOKI_API_URL = os.getenv("ANTZOKI_API_URL", "http://antzoki-api:8000")

UPLOAD_DIR = Path("/app/uploads")
OUTPUT_DIR = Path("/app/outputs")
TEMP_DIR = Path("/app/temp")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Translation model
# ---------------------------------------------------------------------------
translator = TextTranslator()

# ---------------------------------------------------------------------------
# Track job progress + per-job context across the step-by-step pipeline
# ---------------------------------------------------------------------------
job_status = {}


def update_job(job_id: str, state: str, progress: int, detail: str = ""):
    """Merge (not overwrite) so context stored by previous steps (chunks,
    srt, video_path, etc.) survives progress updates within a job."""
    job_status.setdefault(job_id, {})
    job_status[job_id].update({
        "state": state,
        "progress": progress,
        "detail": detail,
    })
    logger.info(f"[{job_id}] {state} ({progress}%): {detail}")


def set_job_error(job_id: str, message: str):
    job_status.setdefault(job_id, {})
    job_status[job_id].update({"state": "error", "progress": -1, "detail": message})


# ---------------------------------------------------------------------------
# SRT helpers (transcript review/edit step)
# ---------------------------------------------------------------------------
_SRT_TIME_RE = re.compile(
    r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2})[,.](\d{3})"
)


def _srt_timestamp(seconds) -> str:
    seconds = max(0.0, seconds or 0.0)
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int(round((seconds - int(seconds)) * 1000))
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def chunks_to_srt(chunks: list) -> str:
    lines = []
    for i, chunk in enumerate(chunks, start=1):
        ts = chunk.get("timestamp") or [0, 0]
        start = ts[0] if ts[0] is not None else 0.0
        end = ts[1] if len(ts) > 1 and ts[1] is not None else start + 2.0
        lines.append(str(i))
        lines.append(f"{_srt_timestamp(start)} --> {_srt_timestamp(end)}")
        lines.append((chunk.get("text") or "").strip())
        lines.append("")
    return "\n".join(lines)


def srt_to_chunks(srt_text: str) -> list:
    chunks = []
    blocks = re.split(r"\n\s*\n", srt_text.strip())
    for block in blocks:
        lines = [l for l in block.splitlines() if l.strip() != ""]
        if not lines:
            continue
        time_idx = next(
            (i for i, l in enumerate(lines) if _SRT_TIME_RE.search(l)), None
        )
        if time_idx is None:
            continue
        m = _SRT_TIME_RE.search(lines[time_idx])
        g = m.groups()
        start = int(g[0]) * 3600 + int(g[1]) * 60 + int(g[2]) + int(g[3]) / 1000.0
        end = int(g[4]) * 3600 + int(g[5]) * 60 + int(g[6]) + int(g[7]) / 1000.0
        text = " ".join(lines[time_idx + 1:]).strip()
        chunks.append({"text": text, "timestamp": [start, end]})
    if not chunks:
        raise ValueError("Ez da SRT bloke baliozkorik aurkitu")
    return chunks


def words_to_sentence_chunks(words: list) -> list:
    """Group word timestamps using sentence-ending punctuation only."""
    sentences = []
    current = []
    start = None
    end = None

    def flush():
        nonlocal current, start, end
        text = "".join(current).strip()
        if text and start is not None and end is not None:
            sentences.append({"text": text, "timestamp": [start, end]})
        current = []
        start = None
        end = None

    for word in words:
        timestamp = word.get("timestamp") or [None, None]
        word_start = timestamp[0]
        word_end = timestamp[1] if len(timestamp) > 1 else None
        raw_text = word.get("text") or ""
        clean_text = raw_text.strip()
        if not clean_text or word_start is None or word_end is None:
            continue

        if start is None:
            start = word_start
            current.append(clean_text)
        elif raw_text[:1].isspace() or re.match(r"^[,.;:!?]", clean_text):
            current.append(raw_text)
        else:
            current.append(f" {clean_text}")
        end = word_end

        text = "".join(current).strip()
        sentence_end = bool(re.search(r"[.!?][\"')\]]*$", text))
        if sentence_end:
            flush()

    flush()
    return sentences


def words_to_caption_chunks(
    words: list,
    max_duration: float = 4.0,
    max_chars: int = 52,
    pause_threshold: float = 0.7,
) -> list:
    """Group timed words into short cues suitable for video display."""
    captions = []
    current = []
    start = None
    end = None

    def current_text() -> str:
        return "".join(current).strip()

    def flush():
        nonlocal current, start, end
        text = current_text()
        if text and start is not None and end is not None:
            captions.append({"text": text, "timestamp": [start, end]})
        current = []
        start = None
        end = None

    for word in words:
        timestamp = word.get("timestamp") or [None, None]
        word_start = timestamp[0]
        word_end = timestamp[1] if len(timestamp) > 1 else None
        raw_text = word.get("text") or ""
        clean_text = raw_text.strip()
        if not clean_text or word_start is None or word_end is None:
            continue

        separator = "" if not current or raw_text[:1].isspace() else " "
        candidate = f"{current_text()}{separator}{clean_text}".strip()
        has_pause = end is not None and word_start - end >= pause_threshold
        too_long = start is not None and (
            word_end - start > max_duration or len(candidate) > max_chars
        )
        if current and (has_pause or too_long):
            flush()

        if start is None:
            start = word_start
            current.append(clean_text)
        elif raw_text[:1].isspace() or re.match(r"^[,.;:!?]", clean_text):
            current.append(raw_text)
        else:
            current.append(f" {clean_text}")
        end = word_end

        if re.search(r"[.!?][\"')\]]*$", current_text()):
            flush()

    flush()
    return captions


def chunks_to_timed_words(chunks: list) -> list:
    """Turn edited chunks back into a shared timed-word representation."""
    words = []
    for chunk in chunks:
        timestamp = chunk.get("timestamp") or [0, 0]
        start = timestamp[0] if timestamp[0] is not None else 0.0
        end = timestamp[1] if len(timestamp) > 1 and timestamp[1] is not None else start
        tokens = re.findall(r"\S+", chunk.get("text") or "")
        if not tokens:
            continue
        token_duration = max(end - start, 0.001) / len(tokens)
        for index, token in enumerate(tokens):
            token_start = start + index * token_duration
            token_end = end if index == len(tokens) - 1 else token_start + token_duration
            words.append({"text": token, "timestamp": [token_start, token_end]})
    return words


def set_transcript_views(job: dict, words: list):
    """Store canonical words and refresh both transcript projections."""
    sentences = words_to_sentence_chunks(words)
    captions = words_to_caption_chunks(words)
    job.update({
        "words": words,
        "sentence_chunks": sentences,
        "caption_chunks": captions,
        "chunks": sentences,
        "srt": chunks_to_srt(captions),
    })


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    logger.info("Loading translation models...")
    translator.load_models()
    logger.info("Translation models loaded.")
    yield
    logger.info("Shutting down...")


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Bideo Itzultzailea",
    description="Gaztelera ↔ Euskera bideo itzulpen sistema",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static files and templates
app.mount("/static", StaticFiles(directory="/app/static"), name="static")
templates = Jinja2Templates(directory="/app/templates")


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------
def extract_audio(video_path: str, audio_path: str) -> float:
    """Extract audio from video using ffmpeg. Returns duration in seconds."""
    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
        audio_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg extract audio failed: {result.stderr}")

    # Get duration
    probe_cmd = [
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", video_path
    ]
    probe_result = subprocess.run(probe_cmd, capture_output=True, text=True)
    duration = float(probe_result.stdout.strip())
    return duration


def detect_speech_start(audio_path: str) -> float:
    """Return the end of leading silence, or zero when none is detected."""
    cmd = [
        "ffmpeg", "-hide_banner", "-i", audio_path,
        "-af", "silencedetect=noise=-40dB:d=0.1",
        "-f", "null", "-",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    silence_start = re.search(r"silence_start:\s*(-?\d+(?:\.\d+)?)", result.stderr)
    if not silence_start or abs(float(silence_start.group(1))) > 0.05:
        return 0.0
    silence_end = re.search(r"silence_end:\s*(\d+(?:\.\d+)?)", result.stderr)
    return float(silence_end.group(1)) if silence_end else 0.0


def extract_voice_reference(
    audio_path: str,
    output_path: str,
    start: float,
    audio_duration: float,
):
    """Extract a clean mono reference clip for zero-shot voice conversion."""
    reference_duration = min(12.0, audio_duration - start)
    if reference_duration < 1.0:
        raise RuntimeError("Ez dago ahotsa klonatzeko audio nahikorik")
    cmd = [
        "ffmpeg", "-y", "-ss", str(start), "-i", audio_path,
        "-t", str(reference_duration),
        "-af", "highpass=f=70,lowpass=f=8000,loudnorm",
        "-ar", "24000", "-ac", "1", "-acodec", "pcm_s16le",
        output_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Voice reference extraction failed: {result.stderr}")


def align_word_timeline(words: list, speech_start: float):
    """Align zero-based Whisper word timestamps with the source audio."""
    if speech_start <= 0:
        return
    first_word = next((word for word in words if (word.get("text") or "").strip()), None)
    if not first_word:
        return
    timestamp = first_word.get("timestamp") or [None, None]
    word_start = timestamp[0]
    if word_start is None or word_start > 0.05:
        return
    word_end = timestamp[1] if len(timestamp) > 1 else None
    if word_end is not None and speech_start < word_end:
        first_word["timestamp"] = [speech_start, word_end]
        return

    for word in words:
        word_timestamp = word.get("timestamp") or [None, None]
        start = word_timestamp[0]
        end = word_timestamp[1] if len(word_timestamp) > 1 else None
        if start is None or end is None:
            continue
        word["timestamp"] = [start + speech_start, end + speech_start]


def get_audio_duration(audio_path: str) -> float:
    """Get duration of audio file in seconds."""
    cmd = [
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", audio_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {result.stderr}")
    return float(result.stdout.strip())


def replace_audio_in_video(video_path: str, audio_path: str, output_path: str):
    """Replace the audio track of a video with a new audio file."""
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-i", audio_path,
        "-c:v", "copy",
        "-map", "0:v:0", "-map", "1:a:0",
        "-shortest",
        output_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg replace audio failed: {result.stderr}")


def concatenate_audio_segments(segment_paths: list, output_path: str):
    """Concatenate multiple audio files using ffmpeg."""
    if not segment_paths:
        raise ValueError("No audio segments to concatenate")

    list_file = output_path + ".list.txt"
    with open(list_file, "w") as f:
        for seg_path in segment_paths:
            f.write(f"file '{seg_path}'\n")

    cmd = [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", list_file, "-c", "copy", output_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    os.remove(list_file)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg concat failed: {result.stderr}")


def generate_silence(duration_sec: float, output_path: str):
    """Generate silence audio of a given duration."""
    cmd = [
        "ffmpeg", "-y", "-f", "lavfi",
        "-i", f"anullsrc=r=22050:cl=mono",
        "-t", str(duration_sec),
        "-acodec", "pcm_s16le",
        output_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg silence gen failed: {result.stderr}")


# ---------------------------------------------------------------------------
# API Endpoints
# ---------------------------------------------------------------------------
@app.get("/")
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/api/health")
async def health():
    """Check health of all services."""
    status = {"orchestrator": "ok"}

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            r = await client.get(f"{WHISPER_API_URL}/health")
            status["whisper"] = r.json() if r.status_code == 200 else "error"
        except Exception as e:
            status["whisper"] = f"unreachable: {str(e)}"

        try:
            r = await client.get(f"{ANTZOKI_API_URL}/health")
            status["antzoki"] = r.json() if r.status_code == 200 else "error"
        except Exception as e:
            status["antzoki"] = f"unreachable: {str(e)}"

    return status


@app.get("/api/voices")
async def get_voices():
    """Get available TTS voices."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            r = await client.get(f"{ANTZOKI_API_URL}/voices")
            return r.json()
        except Exception as e:
            raise HTTPException(status_code=503, detail=f"Antzoki unavailable: {e}")


class SrtUpdate(BaseModel):
    srt: str


class SubtitleItem(BaseModel):
    start: float
    end: float
    text: str


class SubtitleUpdate(BaseModel):
    subtitles: list[SubtitleItem]


class TranscriptUpdate(SubtitleUpdate):
    view: str


def chunks_to_subtitles(chunks: list) -> list[dict]:
    subtitles = []
    for chunk in chunks:
        timestamp = chunk.get("timestamp") or [0, 0]
        start = timestamp[0] if timestamp[0] is not None else 0.0
        end = timestamp[1] if len(timestamp) > 1 and timestamp[1] is not None else start + 2.0
        subtitles.append({"start": start, "end": end, "text": chunk.get("text", "")})
    return subtitles


def validate_subtitles(items: list[SubtitleItem]) -> list[dict]:
    if not items:
        raise HTTPException(400, "Gutxienez azpititulu bat behar da")

    chunks = []
    previous_start = -1.0
    for index, item in enumerate(items, start=1):
        text = item.text.strip()
        if item.start < 0 or item.end <= item.start:
            raise HTTPException(400, f"{index}. azpitituluaren denbora baliogabea da")
        if item.start < previous_start:
            raise HTTPException(400, "Azpitituluak hasiera-denboraren arabera ordenatu behar dira")
        if not text:
            raise HTTPException(400, f"{index}. azpitituluak ez du testurik")
        chunks.append({"text": text, "timestamp": [item.start, item.end]})
        previous_start = item.start
    return chunks


@app.get("/api/job/{job_id}")
async def get_job_status(job_id: str):
    """
    Estado del job. Erabiltzaileak berrikusi/onartu behar duen urratsean
    dagoenean (transkripzioa edo itzulpena), SRT testua ere itzultzen du.
    """
    if job_id not in job_status:
        return {"state": "unknown", "progress": 0, "detail": "Job not found"}

    job = job_status[job_id]
    response = {
        "state": job.get("state"),
        "progress": job.get("progress"),
        "detail": job.get("detail"),
    }
    if job.get("state") == "awaiting_transcript_review":
        response["srt"] = job.get("srt", "")
        response["subtitles"] = chunks_to_subtitles(job.get("sentence_chunks", []))
        response["sentences"] = chunks_to_subtitles(job.get("sentence_chunks", []))
        response["captions"] = chunks_to_subtitles(job.get("caption_chunks", []))
    if job.get("state") == "awaiting_translation_review":
        response["srt_translated"] = job.get("srt_translated", "")
        response["subtitles"] = chunks_to_subtitles(job.get("translated_chunks", []))
    if job.get("state") == "completed":
        response["result"] = job.get("result")
    return response


@app.put("/api/job/{job_id}/srt")
async def update_job_srt(job_id: str, body: SrtUpdate):
    """
    Transkripzioaren SRT edizioa onartu. Bakarrik 'awaiting_transcript_review'
    egoeran dagoenean uzten da (itzuli aurretik zuzentzeko urratsa).
    """
    if job_id not in job_status:
        raise HTTPException(404, "Job not found")
    job = job_status[job_id]
    if job.get("state") != "awaiting_transcript_review":
        raise HTTPException(
            400,
            f"Job ez dago transkripzioa berrikusteko egoeran "
            f"(egungo egoera: {job.get('state')})",
        )
    try:
        chunks = srt_to_chunks(body.srt)
    except ValueError as e:
        raise HTTPException(400, f"SRT baliogabea: {e}")

    set_transcript_views(job, chunks_to_timed_words(chunks))
    return {
        "success": True,
        "sentences": chunks_to_subtitles(job["sentence_chunks"]),
        "captions": chunks_to_subtitles(job["caption_chunks"]),
    }


@app.put("/api/job/{job_id}/transcript")
async def update_job_transcript(job_id: str, body: TranscriptUpdate):
    if job_id not in job_status:
        raise HTTPException(404, "Job not found")
    job = job_status[job_id]
    if job.get("state") != "awaiting_transcript_review":
        raise HTTPException(400, "Job ez dago transkripzioa berrikusteko egoeran")
    if body.view not in ("sentences", "captions"):
        raise HTTPException(400, "view must be 'sentences' or 'captions'")

    chunks = validate_subtitles(body.subtitles)
    set_transcript_views(job, chunks_to_timed_words(chunks))
    return {
        "success": True,
        "sentences": chunks_to_subtitles(job["sentence_chunks"]),
        "captions": chunks_to_subtitles(job["caption_chunks"]),
    }


@app.put("/api/job/{job_id}/subtitles")
async def update_job_subtitles(job_id: str, body: SubtitleUpdate):
    if job_id not in job_status:
        raise HTTPException(404, "Job not found")

    job = job_status[job_id]
    state = job.get("state")
    chunks = validate_subtitles(body.subtitles)
    if state == "awaiting_transcript_review":
        set_transcript_views(job, chunks_to_timed_words(chunks))
    elif state == "awaiting_translation_review":
        job["translated_chunks"] = chunks
        job["srt_translated"] = chunks_to_srt(chunks)
    else:
        raise HTTPException(
            400,
            f"Job ez dago azpitituluak berrikusteko egoeran (egungo egoera: {state})",
        )
    return {"success": True, "subtitles": chunks_to_subtitles(chunks)}


@app.post("/api/job/{job_id}/approve")
async def approve_job_step(job_id: str):
    """
    Uneko berrikuspen-urratsa onartu eta hurrengo urratsa abiarazi
    (background task gisa, HTTP eskaerak ez du itxaron behar).
    """
    if job_id not in job_status:
        raise HTTPException(404, "Job not found")
    job = job_status[job_id]
    state = job.get("state")

    if state == "awaiting_transcript_review":
        update_job(job_id, "translating", 45, "Testua itzultzen...")
        asyncio.create_task(run_translation(job_id))
    elif state == "awaiting_translation_review":
        update_job(job_id, "synthesizing", 60, "Ahotsa sintetizatzen...")
        asyncio.create_task(run_synthesis(job_id))
    elif state == "awaiting_synthesis_review":
        update_job(job_id, "finalizing", 90, "Bideo finala sortzen...")
        asyncio.create_task(run_finalize(job_id))
    else:
        raise HTTPException(
            400,
            f"Job ez dago onarpen-urrats batean (egungo egoera: {state})",
        )

    return {"success": True}


@app.post("/api/translate")
async def translate_video(
    file: UploadFile = File(..., description="Video file to translate"),
    source_lang: str = Form(..., description="Source language: es or eu"),
    target_lang: str = Form(..., description="Target language: es or eu"),
    voice: str = Form("antzoki", description="TTS voice name"),
    clone_voice: bool = Form(True, description="Preserve the source speaker voice"),
):
    """
    Bideoa igo eta transkripzio-urratsa abiarazi. Berehala itzultzen du
    job_id bat -- HTTP eskaerak ez du pipeline osoa itxaron behar (HF
    Spaces-en proxy-ak eskaera luzeak mozten ditu ~60s-tara).
    """
    if source_lang not in ("es", "eu"):
        raise HTTPException(400, "source_lang must be 'es' or 'eu'")
    if target_lang not in ("es", "eu"):
        raise HTTPException(400, "target_lang must be 'es' or 'eu'")
    if source_lang == target_lang:
        raise HTTPException(400, "source_lang and target_lang must be different")

    job_id = str(uuid.uuid4())[:8]
    update_job(job_id, "uploading", 5, "Bideoa igotzen...")

    video_ext = os.path.splitext(file.filename or "video.mp4")[1] or ".mp4"
    video_path = str(UPLOAD_DIR / f"{job_id}{video_ext}")
    with open(video_path, "wb") as f:
        content = await file.read()
        f.write(content)

    asyncio.create_task(
        run_transcription(
            job_id, video_path, video_ext, source_lang, target_lang, voice,
            clone_voice,
        )
    )

    return JSONResponse({"success": True, "job_id": job_id})


# ---------------------------------------------------------------------------
# Pipeline urratsak (bakoitza background task gisa, hurrengoa hasi aurretik
# erabiltzailearen onarpenaren zain geratzen dena)
# ---------------------------------------------------------------------------
async def run_transcription(
    job_id: str,
    video_path: str,
    video_ext: str,
    source_lang: str,
    target_lang: str,
    voice: str,
    clone_voice: bool,
):
    """1. urratsa: audioa atera + Whisper bidez transkribatu.
    Amaitzean 'awaiting_transcript_review' egoerara pasatzen da, SRT
    editagarria erabiltzailearen esku utziz."""
    try:
        update_job(job_id, "extracting_audio", 10, "Audioa ateratzen bideotik...")
        audio_path = str(TEMP_DIR / f"{job_id}_audio.wav")
        video_duration = extract_audio(video_path, audio_path)
        logger.info(f"[{job_id}] Video duration: {video_duration:.2f}s")

        update_job(job_id, "transcribing", 20, "Audioa transkribatzen...")
        async with httpx.AsyncClient(timeout=600.0) as client:
            with open(audio_path, "rb") as audio_file:
                transcription_response = await client.post(
                    f"{WHISPER_API_URL}/transcribe",
                    files={"file": ("audio.wav", audio_file, "audio/wav")},
                    data={
                        "language": source_lang,
                        "task": "transcribe",
                        "return_timestamps": "word",
                    },
                )
            if transcription_response.status_code != 200:
                raise RuntimeError(f"Whisper API error: {transcription_response.text}")
            transcription = transcription_response.json()

        words = transcription.get("chunks") or []
        speech_start = detect_speech_start(audio_path)
        if not words:
            fallback_chunks = [{
                "text": transcription.get("text", ""),
                "timestamp": [speech_start, video_duration],
            }]
            words = chunks_to_timed_words(fallback_chunks)
        else:
            align_word_timeline(words, speech_start)

        voice_reference_path = None
        if clone_voice:
            voice_reference_path = str(TEMP_DIR / f"{job_id}_voice_reference.wav")
            extract_voice_reference(
                audio_path,
                voice_reference_path,
                speech_start,
                video_duration,
            )

        job_status[job_id].update({
            "video_path": video_path,
            "video_ext": video_ext,
            "source_lang": source_lang,
            "target_lang": target_lang,
            "voice": voice,
            "clone_voice": clone_voice,
            "voice_reference_path": voice_reference_path,
            "video_duration": video_duration,
        })
        set_transcript_views(job_status[job_id], words)
        update_job(
            job_id, "awaiting_transcript_review", 30,
            "Berrikusi transkripzioa eta onartu itzultzeko",
        )

    except Exception as e:
        set_job_error(job_id, str(e))
        logger.exception(f"[{job_id}] Transcription failed")


async def run_translation(job_id: str):
    """2. urratsa: (erabiltzaileak editatutako) transkripzioa itzuli
    MarianMT bidez. Amaitzean 'awaiting_translation_review' egoerara
    pasatzen da (SRT itzulia, irakurtzeko soilik)."""
    job = job_status[job_id]
    try:
        chunks = job["chunks"]
        source_lang = job["source_lang"]
        target_lang = job["target_lang"]

        translated_chunks = []
        for chunk in chunks:
            text = (chunk.get("text") or "").strip()
            if not text:
                continue
            translated_text = translator.translate(text, source_lang, target_lang)
            translated_chunks.append({
                "text": translated_text,
                "timestamp": chunk.get("timestamp", [0, 0]),
            })

        srt_translated = chunks_to_srt(translated_chunks)

        job_status[job_id].update({
            "translated_chunks": translated_chunks,
            "srt_translated": srt_translated,
        })
        update_job(
            job_id, "awaiting_translation_review", 55,
            "Berrikusi itzulpena eta onartu ahotsa sortzeko",
        )

    except Exception as e:
        set_job_error(job_id, str(e))
        logger.exception(f"[{job_id}] Translation failed")


async def run_synthesis(job_id: str):
    """3. urratsa: itzulitako testua Antzoki bidez sintetizatu, zatiak
    denboran doitu eta elkartu. Amaitzean 'awaiting_synthesis_review'
    egoerara pasatzen da."""
    job = job_status[job_id]
    try:
        translated_chunks = job["translated_chunks"]
        target_lang = job["target_lang"]
        voice = job["voice"]
        clone_voice = job.get("clone_voice", False)
        voice_reference_path = job.get("voice_reference_path")
        video_duration = job["video_duration"]

        segment_paths = []
        async with httpx.AsyncClient(timeout=1800.0) as client:
            timeline_cursor = 0.0
            for i, chunk in enumerate(translated_chunks):
                progress = 60 + int(20 * (i / max(len(translated_chunks), 1)))
                update_job(
                    job_id, "synthesizing", progress,
                    f"Zatia sintetizatzen {i + 1}/{len(translated_chunks)}...",
                )

                ts = chunk["timestamp"]
                chunk_start = ts[0] if ts[0] is not None else timeline_cursor
                chunk_end = ts[1] if ts[1] is not None else chunk_start + 3.0
                chunk_duration = max(chunk_end - chunk_start, 0.5)

                gap = chunk_start - timeline_cursor
                if gap > 0.1:
                    silence_path = str(TEMP_DIR / f"{job_id}_silence_{i}.wav")
                    generate_silence(gap, silence_path)
                    segment_paths.append(silence_path)
                    timeline_cursor += gap

                synth_payload = {
                    "text": chunk["text"],
                    "language": target_lang,
                    "voice": "antzoki",
                    "style": voice,
                    "duration": chunk_duration,
                }
                if clone_voice:
                    with open(voice_reference_path, "rb") as reference_file:
                        synth_response = await client.post(
                            f"{ANTZOKI_API_URL}/synthesize-cloned",
                            data={
                                "text": chunk["text"],
                                "language": target_lang,
                                "style": voice,
                                "duration": str(chunk_duration),
                            },
                            files={
                                "reference": (
                                    "reference.wav", reference_file, "audio/wav"
                                ),
                            },
                        )
                else:
                    synth_response = await client.post(
                        f"{ANTZOKI_API_URL}/synthesize",
                        json=synth_payload,
                    )

                if synth_response.status_code != 200:
                    logger.error(f"[{job_id}] TTS error for chunk {i}: {synth_response.text}")
                    silence_path = str(TEMP_DIR / f"{job_id}_fail_{i}.wav")
                    generate_silence(chunk_duration, silence_path)
                    segment_paths.append(silence_path)
                    timeline_cursor += chunk_duration
                    continue

                raw_synth_path = str(TEMP_DIR / f"{job_id}_synth_{i}.wav")
                with open(raw_synth_path, "wb") as sf:
                    sf.write(synth_response.content)

                synth_duration = get_audio_duration(raw_synth_path)
                segment_paths.append(raw_synth_path)
                timeline_cursor += synth_duration if synth_duration > 0 else chunk_duration

            if timeline_cursor < video_duration:
                trailing_silence = str(TEMP_DIR / f"{job_id}_trailing.wav")
                generate_silence(video_duration - timeline_cursor, trailing_silence)
                segment_paths.append(trailing_silence)

        update_job(job_id, "combining", 82, "Audio zatiak konbinatzen...")
        final_audio_path = str(TEMP_DIR / f"{job_id}_final_audio.wav")

        if len(segment_paths) == 1:
            final_audio_path = segment_paths[0]
        else:
            normalized_paths = []
            for idx, seg in enumerate(segment_paths):
                norm_path = str(TEMP_DIR / f"{job_id}_norm_{idx}.wav")
                cmd = [
                    "ffmpeg", "-y", "-i", seg,
                    "-ar", "22050", "-ac", "1", "-acodec", "pcm_s16le",
                    norm_path,
                ]
                subprocess.run(cmd, capture_output=True, text=True)
                normalized_paths.append(norm_path)
            concatenate_audio_segments(normalized_paths, final_audio_path)

        job_status[job_id]["final_audio_path"] = final_audio_path
        update_job(
            job_id, "awaiting_synthesis_review", 85,
            "Ahotsa sortuta. Onartu bideo finala sortzeko",
        )

    except Exception as e:
        set_job_error(job_id, str(e))
        logger.exception(f"[{job_id}] Synthesis failed")


async def run_finalize(job_id: str):
    """4. urratsa: audio berria bideoan txertatu eta emaitza sortu."""
    job = job_status[job_id]
    try:
        video_path = job["video_path"]
        video_ext = job["video_ext"]
        final_audio_path = job["final_audio_path"]

        update_job(job_id, "finalizing", 92, "Bideo finala sortzen...")
        output_filename = f"{job_id}_translated{video_ext}"
        output_path = str(OUTPUT_DIR / output_filename)
        replace_audio_in_video(video_path, final_audio_path, output_path)

        for p in TEMP_DIR.glob(f"{job_id}_*"):
            try:
                p.unlink()
            except OSError:
                pass

        job_status[job_id].update({
            "state": "completed",
            "progress": 100,
            "detail": "Itzulpena amaituta!",
            "result": {
                "success": True,
                "job_id": job_id,
                "download_url": f"/api/download/{output_filename}",
                "transcription": " ".join(c["text"] for c in job["chunks"]),
                "translated_text": " ".join(
                    c["text"] for c in job["translated_chunks"]
                ),
            },
        })
        logger.info(f"[{job_id}] completed (100%): Translation complete!")

    except Exception as e:
        set_job_error(job_id, str(e))
        logger.exception(f"[{job_id}] Finalize failed")


@app.get("/api/download/{filename}")
async def download_file(filename: str):
    """Download a translated video."""
    file_path = OUTPUT_DIR / filename
    if not file_path.exists():
        raise HTTPException(404, "File not found")
    return FileResponse(
        path=str(file_path),
        media_type="video/mp4",
        filename=filename,
    )


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=5000, reload=False)

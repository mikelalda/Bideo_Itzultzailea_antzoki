# =============================================================================
# Bideo Itzultzailea - Video Translation Backend
# Orchestrates: Whisper (STT) → Translation → aHoTTS (TTS)
# Supports: Castellano ↔ Euskera
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

from translator import TextTranslator

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
WHISPER_API_URL = os.getenv("WHISPER_API_URL", "http://whisper-api:8000")
AHOTTS_API_URL = os.getenv("AHOTTS_API_URL", "http://ahotts-api:8000")

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
# Track job progress via WebSocket
# ---------------------------------------------------------------------------
job_status = {}


def update_job(job_id: str, step: str, progress: int, detail: str = ""):
    job_status[job_id] = {
        "step": step,
        "progress": progress,
        "detail": detail,
    }
    logger.info(f"[{job_id}] {step} ({progress}%): {detail}")


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
    description="Sistema de traducción de vídeo Castellano ↔ Euskera",
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


def adjust_audio_speed(input_path: str, output_path: str, speed_factor: float):
    """Adjust audio speed using ffmpeg atempo filter."""
    if speed_factor < 0.5:
        speed_factor = 0.5
    if speed_factor > 2.0:
        speed_factor = 2.0

    # atempo only supports 0.5 to 2.0, chain filters for wider range
    cmd = [
        "ffmpeg", "-y", "-i", input_path,
        "-filter:a", f"atempo={speed_factor}",
        "-vn", output_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg speed adjust failed: {result.stderr}")


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
            r = await client.get(f"{AHOTTS_API_URL}/health")
            status["ahotts"] = r.json() if r.status_code == 200 else "error"
        except Exception as e:
            status["ahotts"] = f"unreachable: {str(e)}"

    return status


@app.get("/api/voices")
async def get_voices():
    """Get available TTS voices."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            r = await client.get(f"{AHOTTS_API_URL}/voices")
            return r.json()
        except Exception as e:
            raise HTTPException(status_code=503, detail=f"aHoTTS unavailable: {e}")


@app.get("/api/job/{job_id}")
async def get_job_status(job_id: str):
    """Get status of a translation job."""
    if job_id in job_status:
        return job_status[job_id]
    return {"step": "unknown", "progress": 0, "detail": "Job not found"}


@app.post("/api/translate")
async def translate_video(
    file: UploadFile = File(..., description="Video file to translate"),
    source_lang: str = Form(..., description="Source language: es or eu"),
    target_lang: str = Form(..., description="Target language: es or eu"),
    voice: str = Form("antton", description="TTS voice name"),
):
    """
    Kicks off the translation pipeline in the background and returns
    immediately with a job_id. The HF Spaces front proxy kills HTTP
    requests that stay open too long (~60s), so this endpoint must NOT
    block until the whole pipeline finishes -- the client polls
    GET /api/job/{job_id} instead (see process_translation below).
    """
    if source_lang not in ("es", "eu"):
        raise HTTPException(400, "source_lang must be 'es' or 'eu'")
    if target_lang not in ("es", "eu"):
        raise HTTPException(400, "target_lang must be 'es' or 'eu'")
    if source_lang == target_lang:
        raise HTTPException(400, "source_lang and target_lang must be different")

    job_id = str(uuid.uuid4())[:8]
    update_job(job_id, "uploading", 5, "Uploading video...")

    # Save uploaded video (fast; safe to do inline before responding)
    video_ext = os.path.splitext(file.filename or "video.mp4")[1] or ".mp4"
    video_path = str(UPLOAD_DIR / f"{job_id}{video_ext}")
    with open(video_path, "wb") as f:
        content = await file.read()
        f.write(content)

    # Run the actual pipeline in the background; the request returns now.
    asyncio.create_task(
        process_translation(
            job_id, video_path, video_ext, source_lang, target_lang, voice
        )
    )

    return JSONResponse({"success": True, "job_id": job_id})


async def process_translation(
    job_id: str,
    video_path: str,
    video_ext: str,
    source_lang: str,
    target_lang: str,
    voice: str,
):
    """
    The actual translation pipeline (STT -> MT -> TTS -> mux), run as a
    background task. Progress and the final result are written into
    job_status[job_id], which the client reads via GET /api/job/{job_id}.

    Pipeline:
    1. Extract audio from video
    2. Transcribe audio (Whisper API)
    3. Translate text (MarianMT)
    4. Synthesize translated text (aHoTTS API)
    5. Adjust speed to match original timing
    6. Replace audio in video
    """
    try:
        # STEP 1: Extract audio
        update_job(job_id, "extracting_audio", 10, "Extracting audio from video...")
        audio_path = str(TEMP_DIR / f"{job_id}_audio.wav")
        video_duration = extract_audio(video_path, audio_path)
        logger.info(f"Video duration: {video_duration:.2f}s")

        # STEP 2: Transcribe with Whisper API
        update_job(job_id, "transcribing", 20, "Transcribing audio...")
        async with httpx.AsyncClient(timeout=600.0) as client:
            with open(audio_path, "rb") as audio_file:
                transcription_response = await client.post(
                    f"{WHISPER_API_URL}/transcribe",
                    files={"file": ("audio.wav", audio_file, "audio/wav")},
                    data={
                        "language": source_lang,
                        "task": "transcribe",
                        "return_timestamps": "true",
                    },
                )

            if transcription_response.status_code != 200:
                raise RuntimeError(
                    f"Whisper API error: {transcription_response.text}"
                )

            transcription = transcription_response.json()
            logger.info(f"Transcription: {transcription.get('text', '')[:200]}")

        # STEP 3: Translate text
        update_job(job_id, "translating", 40, "Translating text...")
        chunks = transcription.get("chunks", [])

        if chunks:
            # Translate each chunk individually to maintain timing
            translated_chunks = []
            for chunk in chunks:
                original_text = chunk.get("text", "").strip()
                if not original_text:
                    continue
                translated_text = translator.translate(
                    original_text, source_lang, target_lang
                )
                translated_chunks.append({
                    "text": translated_text,
                    "timestamp": chunk.get("timestamp", [0, 0]),
                })
            logger.info(f"Translated {len(translated_chunks)} chunks")
        else:
            # No chunks, translate full text
            full_text = transcription.get("text", "")
            translated_text = translator.translate(
                full_text, source_lang, target_lang
            )
            translated_chunks = [{
                "text": translated_text,
                "timestamp": [0, video_duration],
            }]

        # STEP 4: Synthesize each chunk with aHoTTS
        update_job(job_id, "synthesizing", 55, "Synthesizing translated speech...")
        segment_paths = []

        async with httpx.AsyncClient(timeout=120.0) as client:
            prev_end = 0.0
            for i, chunk in enumerate(translated_chunks):
                progress = 55 + int(25 * (i / max(len(translated_chunks), 1)))
                update_job(
                    job_id, "synthesizing", progress,
                    f"Synthesizing segment {i+1}/{len(translated_chunks)}..."
                )

                ts = chunk["timestamp"]
                chunk_start = ts[0] if ts[0] is not None else prev_end
                chunk_end = ts[1] if ts[1] is not None else chunk_start + 3.0
                chunk_duration = max(chunk_end - chunk_start, 0.5)

                # Add silence gap if needed
                gap = chunk_start - prev_end
                if gap > 0.1:
                    silence_path = str(TEMP_DIR / f"{job_id}_silence_{i}.wav")
                    generate_silence(gap, silence_path)
                    segment_paths.append(silence_path)

                # Synthesize this chunk
                synth_response = await client.post(
                    f"{AHOTTS_API_URL}/synthesize",
                    json={
                        "text": chunk["text"],
                        "language": target_lang,
                        "voice": voice,
                    },
                )

                if synth_response.status_code != 200:
                    logger.error(
                        f"TTS error for chunk {i}: {synth_response.text}"
                    )
                    # Generate silence instead
                    silence_path = str(TEMP_DIR / f"{job_id}_fail_{i}.wav")
                    generate_silence(chunk_duration, silence_path)
                    segment_paths.append(silence_path)
                    prev_end = chunk_end
                    continue

                # Save synthesized audio
                raw_synth_path = str(TEMP_DIR / f"{job_id}_synth_{i}.wav")
                with open(raw_synth_path, "wb") as sf:
                    sf.write(synth_response.content)

                # STEP 5: Adjust speed to match original timing
                synth_duration = get_audio_duration(raw_synth_path)
                if synth_duration > 0 and chunk_duration > 0:
                    speed_factor = synth_duration / chunk_duration
                    # Only adjust if significantly different
                    if abs(speed_factor - 1.0) > 0.1:
                        adjusted_path = str(
                            TEMP_DIR / f"{job_id}_adjusted_{i}.wav"
                        )
                        speed_factor = max(0.5, min(2.0, speed_factor))
                        adjust_audio_speed(
                            raw_synth_path, adjusted_path, speed_factor
                        )
                        segment_paths.append(adjusted_path)
                    else:
                        segment_paths.append(raw_synth_path)
                else:
                    segment_paths.append(raw_synth_path)

                prev_end = chunk_end

            # Add trailing silence if video is longer
            if prev_end < video_duration:
                trailing_silence = str(TEMP_DIR / f"{job_id}_trailing.wav")
                generate_silence(video_duration - prev_end, trailing_silence)
                segment_paths.append(trailing_silence)

        # STEP 6: Concatenate all segments
        update_job(job_id, "combining", 85, "Combining audio segments...")
        final_audio_path = str(TEMP_DIR / f"{job_id}_final_audio.wav")

        if len(segment_paths) == 1:
            final_audio_path = segment_paths[0]
        else:
            # Normalize all segments to same format before concat
            normalized_paths = []
            for idx, seg in enumerate(segment_paths):
                norm_path = str(TEMP_DIR / f"{job_id}_norm_{idx}.wav")
                cmd = [
                    "ffmpeg", "-y", "-i", seg,
                    "-ar", "22050", "-ac", "1", "-acodec", "pcm_s16le",
                    norm_path
                ]
                subprocess.run(cmd, capture_output=True, text=True)
                normalized_paths.append(norm_path)

            concatenate_audio_segments(normalized_paths, final_audio_path)

        # STEP 7: Replace audio in video
        update_job(job_id, "finalizing", 90, "Creating final video...")
        output_filename = f"{job_id}_translated{video_ext}"
        output_path = str(OUTPUT_DIR / output_filename)
        replace_audio_in_video(video_path, final_audio_path, output_path)

        # Cleanup temp files
        for p in TEMP_DIR.glob(f"{job_id}_*"):
            try:
                p.unlink()
            except OSError:
                pass

        # Store the final result alongside the job status (no HTTP response
        # to return to here -- this runs as a detached background task).
        job_status[job_id] = {
            "step": "completed",
            "progress": 100,
            "detail": "Translation complete!",
            "result": {
                "success": True,
                "job_id": job_id,
                "download_url": f"/api/download/{output_filename}",
                "transcription": transcription.get("text", ""),
                "translated_text": " ".join(c["text"] for c in translated_chunks),
            },
        }
        logger.info(f"[{job_id}] completed (100%): Translation complete!")

    except Exception as e:
        update_job(job_id, "error", -1, str(e))
        logger.exception(f"Translation failed for job {job_id}")


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

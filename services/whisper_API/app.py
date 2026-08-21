"""
Whisper API - Speech-to-Text API using xezpeleta/whisper-large-v3-eu
Supports: Basque (eu), Spanish (es), English (en)
"""

import os
import time
import asyncio
import logging
import tempfile
from typing import Optional
from contextlib import asynccontextmanager

import torch
import numpy as np
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from transformers import AutoModelForSpeechSeq2Seq, AutoProcessor, pipeline
import librosa

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MODEL_ID = os.getenv("MODEL_ID", "xezpeleta/whisper-large-v3-eu")
DEVICE = os.getenv("DEVICE", "cuda" if torch.cuda.is_available() else "cpu")
TORCH_DTYPE = torch.float16 if DEVICE == "cuda" else torch.float32
BATCH_SIZE = int(os.getenv("BATCH_SIZE", "16"))
MAX_FILE_SIZE_MB = int(os.getenv("MAX_FILE_SIZE_MB", "100"))
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))

SUPPORTED_LANGUAGES = {
    "eu": "basque",
    "es": "spanish",
    "en": "english",
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Global model references
# ---------------------------------------------------------------------------
pipe = None
model_status = {"state": "not_started", "detail": ""}


def load_model():
    """Load model and processor, build the ASR pipeline."""
    global pipe, model_status
    import threading

    def _download_and_load():
        global pipe, model_status
        try:
            model_status = {"state": "downloading", "detail": f"Deskargatzen: {MODEL_ID}"}
            logger.info("Downloading/loading model %s on %s (%s)…", MODEL_ID, DEVICE, TORCH_DTYPE)

            model = AutoModelForSpeechSeq2Seq.from_pretrained(
                MODEL_ID,
                torch_dtype=TORCH_DTYPE,
                low_cpu_mem_usage=True,
                use_safetensors=True,
            ).to(DEVICE)

            model_status = {"state": "downloading", "detail": f"Prozesadorea kargatzen: {MODEL_ID}"}
            processor = AutoProcessor.from_pretrained(MODEL_ID)

            model_status = {"state": "loading", "detail": "Pipeline konfiguratzen..."}
            pipe = pipeline(
                "automatic-speech-recognition",
                model=model,
                tokenizer=processor.tokenizer,
                feature_extractor=processor.feature_extractor,
                torch_dtype=TORCH_DTYPE,
                device=DEVICE,
            )

            model_status = {"state": "ready", "detail": ""}
            logger.info("Model loaded successfully.")
        except Exception as e:
            model_status = {"state": "error", "detail": str(e)}
            logger.error("Failed to load model: %s", e)

    thread = threading.Thread(target=_download_and_load, daemon=True)
    thread.start()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle."""
    load_model()
    yield
    logger.info("Shutting down…")


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Whisper API (eu/es/en)",
    description=(
        "API de transcripción de voz a texto utilizando el modelo "
        "xezpeleta/whisper-large-v3-eu. Soporta euskera, castellano e inglés."
    ),
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _load_audio(path: str, sr: int = 16_000) -> np.ndarray:
    """Load an audio file and resample to the target sample rate."""
    audio, _ = librosa.load(path, sr=sr, mono=True)
    return audio


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@app.get("/health")
async def health():
    """Health-check endpoint."""
    if model_status["state"] in ("downloading", "loading", "not_started"):
        return {
            "status": "loading",
            "model": MODEL_ID,
            "device": DEVICE,
            "model_state": model_status["state"],
            "detail": model_status["detail"],
            "supported_languages": SUPPORTED_LANGUAGES,
        }
    if model_status["state"] == "error":
        return {
            "status": "error",
            "model": MODEL_ID,
            "detail": model_status["detail"],
        }
    return {
        "status": "ok",
        "model": MODEL_ID,
        "device": DEVICE,
        "supported_languages": SUPPORTED_LANGUAGES,
    }


@app.get("/languages")
async def languages():
    """Return supported languages."""
    return {"languages": SUPPORTED_LANGUAGES}


@app.post("/transcribe")
async def transcribe(
    file: UploadFile = File(..., description="Audio file (wav, mp3, ogg, flac, m4a…)"),
    language: Optional[str] = Form(
        None,
        description="Language code: 'eu' (euskera), 'es' (castellano), 'en' (english). "
                    "If omitted the model will auto-detect.",
    ),
    task: Optional[str] = Form(
        "transcribe",
        description="'transcribe' for transcription or 'translate' to translate to English.",
    ),
    return_timestamps: Optional[bool] = Form(
        False,
        description="If true, return word-level or chunk-level timestamps.",
    ),
):
    """
    Transcribe an audio file.

    - **file**: Audio file to transcribe.
    - **language**: Optional language code (eu, es, en). Auto-detected if omitted.
    - **task**: 'transcribe' (default) or 'translate' (translates to English).
    - **return_timestamps**: Whether to include timestamps in the response.
    """
    if pipe is None:
        raise HTTPException(status_code=503, detail="Model not loaded yet.")

    # Validate language
    if language and language not in SUPPORTED_LANGUAGES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported language '{language}'. Supported: {list(SUPPORTED_LANGUAGES.keys())}",
        )

    # Validate task
    if task not in ("transcribe", "translate"):
        raise HTTPException(
            status_code=400,
            detail="Task must be 'transcribe' or 'translate'.",
        )

    # Validate file size
    contents = await file.read()
    size_mb = len(contents) / (1024 * 1024)
    if size_mb > MAX_FILE_SIZE_MB:
        raise HTTPException(
            status_code=413,
            detail=f"File too large ({size_mb:.1f} MB). Max allowed: {MAX_FILE_SIZE_MB} MB.",
        )

    # Write to temp file and load audio
    suffix = os.path.splitext(file.filename or "audio.wav")[1] or ".wav"
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(contents)
            tmp_path = tmp.name

        audio = _load_audio(tmp_path)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error reading audio file: {e}")
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)

    # Build generate_kwargs
    generate_kwargs = {"task": task}
    if language:
        generate_kwargs["language"] = SUPPORTED_LANGUAGES[language]

    # Run inference in a thread pool so health checks remain responsive
    t0 = time.time()
    try:
        result = await asyncio.to_thread(
            pipe,
            audio,
            batch_size=BATCH_SIZE,
            generate_kwargs=generate_kwargs,
            return_timestamps=return_timestamps,
        )
    except Exception as e:
        logger.exception("Inference failed")
        raise HTTPException(status_code=500, detail=f"Transcription error: {e}")
    elapsed = time.time() - t0

    duration_seconds = len(audio) / 16_000

    response = {
        "text": result["text"].strip(),
        "language": language or "auto",
        "task": task,
        "duration_seconds": round(duration_seconds, 2),
        "processing_time_seconds": round(elapsed, 2),
    }

    if return_timestamps and "chunks" in result:
        response["chunks"] = result["chunks"]

    return JSONResponse(content=response)


@app.post("/detect-language")
async def detect_language(
    file: UploadFile = File(..., description="Audio file to detect language from."),
):
    """
    Detect the language of the audio file (best effort using the first 30 s).
    """
    if pipe is None:
        raise HTTPException(status_code=503, detail="Model not loaded yet.")

    contents = await file.read()
    suffix = os.path.splitext(file.filename or "audio.wav")[1] or ".wav"
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(contents)
            tmp_path = tmp.name

        audio = _load_audio(tmp_path)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error reading audio file: {e}")
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)

    # Use only first 30 seconds for detection
    audio_30s = audio[: 16_000 * 30]

    # Run pipeline in a thread pool so health checks remain responsive
    try:
        result = await asyncio.to_thread(
            pipe,
            audio_30s,
            generate_kwargs={"task": "transcribe"},
            return_timestamps=False,
        )
    except Exception as e:
        logger.exception("Language detection failed")
        raise HTTPException(status_code=500, detail=f"Language detection error: {e}")

    # The token ids can hint at detected language; return transcription text
    return {
        "text": result["text"].strip(),
        "note": "Language auto-detected by the model based on the audio content.",
    }


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host=HOST, port=PORT, reload=False, log_level="info")

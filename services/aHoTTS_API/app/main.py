# =============================================================================
# aHoTTS API - Main FastAPI Application
# =============================================================================

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTask

from app.config import (
    API_DESCRIPTION,
    API_TITLE,
    API_VERSION,
    AVAILABLE_VOICES,
    LANGUAGE_NAMES,
    OUTPUT_PATH,
)
from app.engine import tts_engine
from app.models import (
    ErrorResponse,
    HealthResponse,
    LanguageInfo,
    SynthesizeRequest,
    SynthesizeResponse,
    VoiceInfo,
    VoicesResponse,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def _cleanup_output_files() -> None:
    """Remove all temporary synthesis output files."""
    if not os.path.isdir(OUTPUT_PATH):
        return
    for name in os.listdir(OUTPUT_PATH):
        if name.startswith("tts_") and name.endswith(".wav"):
            try:
                os.remove(os.path.join(OUTPUT_PATH, name))
            except OSError:
                pass


def _safe_remove(path: str) -> None:
    """Delete a single file, ignoring errors (used as a response background task)."""
    try:
        os.remove(path)
        logger.info(f"Removed temporary audio file: {path}")
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Lifespan: startup / shutdown
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup and shutdown events."""
    logger.info("Starting aHoTTS API...")
    os.makedirs(OUTPUT_PATH, exist_ok=True)

    # Remove any output files orphaned by a previous abrupt shutdown.
    _cleanup_output_files()

    if tts_engine.is_binary_available():
        logger.info("TTS binary found and executable.")
    else:
        logger.warning("TTS binary NOT found or not executable!")

    yield

    # Cleanup: remove temporary output files
    logger.info("Shutting down aHoTTS API...")
    _cleanup_output_files()


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(
    title=API_TITLE,
    description=API_DESCRIPTION,
    version=API_VERSION,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/health", response_model=HealthResponse, tags=["System"])
async def health_check():
    """Check the health status of the API."""
    return HealthResponse(
        status="ok",
        version=API_VERSION,
        tts_binary_available=tts_engine.is_binary_available(),
    )


@app.get("/voices", response_model=VoicesResponse, tags=["Voices"])
async def list_voices():
    """List all available voices grouped by language."""
    languages = []
    for lang_code, voices in AVAILABLE_VOICES.items():
        voice_list = [
            VoiceInfo(
                name=v,
                language=lang_code,
                language_name=LANGUAGE_NAMES.get(lang_code, lang_code),
                downloaded=tts_engine.is_voice_downloaded(lang_code, v),
            )
            for v in voices
        ]
        languages.append(
            LanguageInfo(
                code=lang_code,
                name=LANGUAGE_NAMES.get(lang_code, lang_code),
                voices=voice_list,
            )
        )
    return VoicesResponse(languages=languages)


@app.get("/voices/{language}", tags=["Voices"])
async def list_voices_by_language(language: str):
    """List available voices for a specific language."""
    if language not in AVAILABLE_VOICES:
        raise HTTPException(
            status_code=404,
            detail=f"Language '{language}' not found. Available: {list(AVAILABLE_VOICES.keys())}",
        )
    voices = [
        VoiceInfo(
            name=v,
            language=language,
            language_name=LANGUAGE_NAMES.get(language, language),
            downloaded=tts_engine.is_voice_downloaded(language, v),
        )
        for v in AVAILABLE_VOICES[language]
    ]
    return {
        "language": language,
        "name": LANGUAGE_NAMES.get(language, language),
        "voices": voices,
    }


@app.post(
    "/synthesize",
    tags=["Synthesis"],
    responses={
        200: {"content": {"audio/wav": {}}, "description": "WAV audio file"},
        400: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
)
async def synthesize(request: SynthesizeRequest):
    """
    Synthesize text to speech and return a WAV audio file.

    The voice model will be automatically downloaded from HuggingFace
    on first use (this may take a moment).

    **Languages & Voices:**
    - **eu** (Basque): antton, maider
    - **gl** (Galician): brais, celtia, iago, icia, paulo, sabela
    - **ca** (Catalan): bet, eli, eva, jan, mar, ona, pau, pep, pol
    - **es** (Spanish): laura, alejandro
    """
    try:
        output_path = await tts_engine.synthesize(
            text=request.text,
            language=request.language,
            voice=request.voice,
        )
        # Delete the WAV as soon as it has been streamed to the client: the
        # browser keeps its own copy (Blob), so the server file is no longer needed.
        return FileResponse(
            path=output_path,
            media_type="audio/wav",
            filename=f"tts_{request.language}_{request.voice}.wav",
            background=BackgroundTask(_safe_remove, output_path),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.exception("Unexpected error during synthesis")
        raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}")


@app.get(
    "/synthesize",
    tags=["Synthesis"],
    responses={
        200: {"content": {"audio/wav": {}}, "description": "WAV audio file"},
        400: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
)
async def synthesize_get(
    text: str = Query(..., min_length=1, description="Text to synthesize"),
    language: str = Query(..., pattern="^(eu|gl|ca|es)$", description="Language code"),
    voice: str = Query(..., min_length=1, description="Voice name"),
):
    """
    Synthesize text to speech via GET request (useful for quick testing).

    Same functionality as `POST /synthesize` but with query parameters.
    """
    request = SynthesizeRequest(text=text, language=language, voice=voice)
    return await synthesize(request)


@app.post("/download/{language}/{voice}", tags=["Voices"])
async def download_voice(language: str, voice: str):
    """
    Pre-download a voice model from HuggingFace.

    Use this to warm up models before synthesis requests.
    """
    if language not in AVAILABLE_VOICES:
        raise HTTPException(
            status_code=404,
            detail=f"Language '{language}' not found.",
        )
    if voice not in AVAILABLE_VOICES[language]:
        raise HTTPException(
            status_code=404,
            detail=f"Voice '{voice}' not available for '{language}'. "
            f"Available: {AVAILABLE_VOICES[language]}",
        )
    try:
        await tts_engine.download_voice(language, voice)
        return {
            "success": True,
            "message": f"Voice '{voice}' ({language}) is ready.",
        }
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Web client (browser UI with Transformers.js + Web Speech API)
# ---------------------------------------------------------------------------

WEB_DIR = Path(__file__).resolve().parent.parent / "web"

if WEB_DIR.is_dir():
    app.mount(
        "/web",
        StaticFiles(directory=str(WEB_DIR), html=True),
        name="web-static",
    )

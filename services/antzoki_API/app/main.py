import logging
import os

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from app.engine import antzoki_engine
from app.models import HealthResponse, SynthesizeRequest

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Antzoki TTS API", version="1.0.0")


def _safe_remove(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    import torch

    return HealthResponse(
        status="ok" if torch.cuda.is_available() else "error",
        cuda_available=torch.cuda.is_available(),
        gpu=antzoki_engine.gpu_name(),
        models_downloaded=antzoki_engine.models_downloaded(),
        busy=antzoki_engine.busy,
    )


@app.get("/voices")
async def voices():
    return {
        "languages": [{
            "code": "eu",
            "name": "Euskara (Basque)",
            "voices": [{
                "name": "antzoki",
                "language": "eu",
                "language_name": "Euskara (Basque)",
                "downloaded": antzoki_engine.models_downloaded(),
            }],
        }],
    }


@app.post("/download")
async def download_models():
    try:
        await antzoki_engine.prepare()
        return {"success": True, "models_downloaded": True}
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/synthesize")
async def synthesize(request: SynthesizeRequest):
    try:
        output_path = await antzoki_engine.synthesize(request.text, request.duration)
        return FileResponse(
            output_path,
            media_type="audio/wav",
            filename="antzoki.wav",
            background=BackgroundTask(_safe_remove, output_path),
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

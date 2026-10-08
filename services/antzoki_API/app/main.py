import logging
import os
import tempfile

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
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


def _safe_remove_many(*paths: str) -> None:
    for path in paths:
        _safe_remove(path)


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
        "languages": [
            {
                "code": "eu",
                "name": "Euskara (Antzoki LoRA)",
                "engine": "antzoki",
            },
            {
                "code": "es",
                "name": "Castellano (DramaBox base, experimental)",
                "engine": "dramabox",
            },
        ],
        "styles": ["natural", "warm", "dramatic", "serious", "joyful"],
        "voice_cloning": True,
        "models_downloaded": antzoki_engine.models_downloaded(),
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
        output_path = await antzoki_engine.synthesize(
            request.text,
            language=request.language,
            duration=request.duration,
            style=request.style,
        )
        return FileResponse(
            output_path,
            media_type="audio/wav",
            filename="antzoki.wav",
            background=BackgroundTask(_safe_remove, output_path),
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/synthesize-cloned")
async def synthesize_cloned(
    text: str = Form(...),
    language: str = Form(...),
    style: str = Form("natural"),
    duration: float | None = Form(None),
    reference: UploadFile = File(...),
):
    request = SynthesizeRequest(
        text=text,
        language=language,
        style=style,
        duration=duration,
    )
    suffix = os.path.splitext(reference.filename or "reference.wav")[1] or ".wav"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as reference_file:
        reference_file.write(await reference.read())
        reference_path = reference_file.name
    try:
        output_path = await antzoki_engine.synthesize(
            request.text,
            language=request.language,
            duration=request.duration,
            voice_reference=reference_path,
            style=request.style,
        )
        return FileResponse(
            output_path,
            media_type="audio/wav",
            filename="antzoki-cloned.wav",
            background=BackgroundTask(
                _safe_remove_many, reference_path, output_path
            ),
        )
    except RuntimeError as exc:
        _safe_remove(reference_path)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

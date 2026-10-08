from pydantic import BaseModel, Field

from app.config import MAX_TEXT_LENGTH


class SynthesizeRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=MAX_TEXT_LENGTH)
    language: str = Field(..., pattern="^(eu|es)$")
    voice: str = Field("antzoki", pattern="^antzoki$")
    style: str = Field("natural", pattern="^(natural|warm|dramatic|serious|joyful)$")
    duration: float | None = Field(None, gt=0, le=45)


class HealthResponse(BaseModel):
    status: str
    cuda_available: bool
    gpu: str | None
    models_downloaded: bool
    busy: bool

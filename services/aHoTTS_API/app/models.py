# =============================================================================
# aHoTTS API - Pydantic Models
# =============================================================================

from typing import Dict, List, Optional
from pydantic import BaseModel, Field
from app.config import MAX_TEXT_LENGTH


class SynthesizeRequest(BaseModel):
    """Request body for text-to-speech synthesis."""

    text: str = Field(
        ...,
        min_length=1,
        max_length=MAX_TEXT_LENGTH,
        description="Text to synthesize into speech",
        examples=["Kaixo, zer moduz zaude?"],
    )
    language: str = Field(
        ...,
        pattern="^(eu|gl|ca|es)$",
        description="Language code: eu (Basque), gl (Galician), ca (Catalan), es (Spanish)",
        examples=["eu"],
    )
    voice: str = Field(
        ...,
        min_length=1,
        description="Voice model name (e.g., antton, maider, laura, brais)",
        examples=["antton"],
    )


class VoiceInfo(BaseModel):
    """Information about a single voice."""

    name: str
    language: str
    language_name: str
    downloaded: bool


class LanguageInfo(BaseModel):
    """Information about available voices for a language."""

    code: str
    name: str
    voices: List[VoiceInfo]


class VoicesResponse(BaseModel):
    """Response containing all available voices."""

    languages: List[LanguageInfo]


class SynthesizeResponse(BaseModel):
    """Response metadata for a synthesis request."""

    success: bool
    message: str
    language: str
    voice: str
    text: str
    filename: Optional[str] = None


class HealthResponse(BaseModel):
    """Health check response."""

    status: str
    version: str
    tts_binary_available: bool


class ErrorResponse(BaseModel):
    """Error response."""

    detail: str

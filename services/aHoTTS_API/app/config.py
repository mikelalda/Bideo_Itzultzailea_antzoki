# =============================================================================
# aHoTTS API - Configuration
# =============================================================================

import os
from typing import Dict, List

# Base path for the aHoTTS project
AHOTTS_BASE_PATH = os.environ.get("AHOTTS_BASE_PATH", "/app/aHoTTS")

# Path to the TTS binary
TTS_BINARY = os.path.join(AHOTTS_BASE_PATH, "ahotts", "tts")

# Path to dictionaries
DICTS_PATH = os.path.join(AHOTTS_BASE_PATH, "ahotts", "dicts")

# Path to voices
VOICES_PATH = os.path.join(AHOTTS_BASE_PATH, "ahotts", "voices")

# Output directory
OUTPUT_PATH = os.path.join(AHOTTS_BASE_PATH, "output")

# Available voices per language
AVAILABLE_VOICES: Dict[str, List[str]] = {
    "eu": ["antton", "maider"],
    "gl": ["brais", "celtia", "iago", "icia", "paulo", "sabela"],
    "ca": ["bet", "eli", "eva", "jan", "mar", "ona", "pau", "pep", "pol"],
    "es": ["laura", "alejandro"],
}

# Language names for display
LANGUAGE_NAMES: Dict[str, str] = {
    "eu": "Euskara (Basque)",
    "gl": "Galego (Galician)",
    "ca": "Català (Catalan)",
    "es": "Español (Spanish)",
}

# HuggingFace repo pattern
HF_REPO_PATTERN = os.environ.get("HF_REPO_PATTERN", "HiTZ/TTS-{lang}_{voice}")

# Maximum text length
MAX_TEXT_LENGTH = int(os.environ.get("MAX_TEXT_LENGTH", "5000"))

# API configuration
API_TITLE = "aHoTTS API"
API_DESCRIPTION = """
API de Text-to-Speech (TTS) para Euskara, Español, Galego y Català.

Utiliza modelos VITS de [HiTZ](https://huggingface.co/collections/HiTZ/tts) 
basados en el proyecto [aHoTTS](https://github.com/hitz-zentroa/aHoTTS) 
del laboratorio Aholab (UPV/EHU).
"""
API_VERSION = "1.0.0"

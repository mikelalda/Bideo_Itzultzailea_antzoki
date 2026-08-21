# =============================================================================
# Bideo Itzultzailea - Dockerfile combinado para Hugging Face Spaces
# Empaqueta whisper-api + ahotts-api + orchestrator en UN solo contenedor,
# gestionados con supervisord (HF Spaces con SDK Docker solo admite 1 proceso
# principal y 1 puerto expuesto).
#
# Estructura de repo esperada (submodulos ya "aplanados", sin .gitmodules):
#   /app.py, /requirements.txt          -> orchestrator (raiz del repo)
#   /app/, /static/                     -> orchestrator
#   /services/whisper_API/              -> contenido de github.com/mikelalda/whisper_API
#   /services/aHoTTS_API/               -> contenido de github.com/mikelalda/aHoTTS_API
# =============================================================================
FROM python:3.11-slim-bookworm

LABEL maintainer="Bideo Itzultzailea"
LABEL description="Video translation system ES <-> EU (Whisper + MarianMT + aHoTTS) - HF Space combinado"

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# -----------------------------------------------------------------------------
# Dependencias de sistema (union de las 3 imagenes originales)
# - ffmpeg, libsndfile1 -> whisper-api (audio) y orchestrator
# - git, wget, ca-certificates -> aHoTTS_API (clona hitz-zentroa/aHoTTS en build)
# - supervisor -> gestor de los 3 procesos
# -----------------------------------------------------------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        libsndfile1 \
        git \
        wget \
        ca-certificates \
        supervisor \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# =============================================================================
# 1) Orchestrator - venv propio
# =============================================================================
COPY requirements.txt /app/requirements.txt
RUN python3 -m venv /opt/venv/orchestrator \
    && /opt/venv/orchestrator/bin/pip install --no-cache-dir --upgrade pip \
    && /opt/venv/orchestrator/bin/pip install --no-cache-dir -r /app/requirements.txt

# Pre-descarga los modelos MarianMT en build time (igual que el Dockerfile original)
RUN /opt/venv/orchestrator/bin/python -c "\
from transformers import MarianMTModel, MarianTokenizer; \
MarianTokenizer.from_pretrained('Helsinki-NLP/opus-mt-es-eu'); \
MarianMTModel.from_pretrained('Helsinki-NLP/opus-mt-es-eu'); \
MarianTokenizer.from_pretrained('Helsinki-NLP/opus-mt-eu-es'); \
MarianMTModel.from_pretrained('Helsinki-NLP/opus-mt-eu-es'); \
print('Orchestrator models downloaded successfully')"

COPY app/ /app/app/
COPY static/ /app/static/
RUN ln -sf /app/app/templates /app/templates \
    && mkdir -p /app/uploads /app/outputs /app/temp

# =============================================================================
# 2) whisper-api - venv propio (torch/transformers, pesado)
# =============================================================================
COPY services/whisper_API/ /app/services/whisper_API/
RUN python3 -m venv /opt/venv/whisper \
    && /opt/venv/whisper/bin/pip install --no-cache-dir --upgrade pip \
    && /opt/venv/whisper/bin/pip install --no-cache-dir -r /app/services/whisper_API/requirements.txt

# Descomenta para hornear el modelo en la imagen (evita descarga en el primer
# arranque, pero engorda la imagen varios GB y alarga el build):
# RUN /opt/venv/whisper/bin/python -c "\
# from transformers import AutoModelForSpeechSeq2Seq, AutoProcessor; \
# AutoModelForSpeechSeq2Seq.from_pretrained('xezpeleta/whisper-large-v3-eu'); \
# AutoProcessor.from_pretrained('xezpeleta/whisper-large-v3-eu')"

# =============================================================================
# 3) ahotts-api - venv propio + binario tts de hitz-zentroa/aHoTTS
# =============================================================================
COPY services/aHoTTS_API/requirements.txt /app/services/aHoTTS_API/requirements.txt
RUN python3 -m venv /opt/venv/ahotts \
    && /opt/venv/ahotts/bin/pip install --no-cache-dir --upgrade pip \
    && /opt/venv/ahotts/bin/pip install --no-cache-dir -r /app/services/aHoTTS_API/requirements.txt

# Clona aHoTTS y prepara el binario tts + libonnxruntime (igual que su Dockerfile original)
RUN git clone https://github.com/hitz-zentroa/aHoTTS.git /app/services/aHoTTS_API/aHoTTS \
    && cp /app/services/aHoTTS_API/aHoTTS/libonnxruntime.so.1.13.1 /usr/lib/ \
    && ln -sf /usr/lib/libonnxruntime.so.1.13.1 /usr/lib/libonnxruntime.so \
    && ldconfig \
    && chmod +x /app/services/aHoTTS_API/aHoTTS/ahotts/tts \
    && mkdir -p /app/services/aHoTTS_API/aHoTTS/ahotts/voices/eu \
               /app/services/aHoTTS_API/aHoTTS/ahotts/voices/es \
               /app/services/aHoTTS_API/aHoTTS/ahotts/voices/gl \
               /app/services/aHoTTS_API/aHoTTS/ahotts/voices/ca \
               /app/services/aHoTTS_API/aHoTTS/output

COPY services/aHoTTS_API/app/ /app/services/aHoTTS_API/app/
COPY services/aHoTTS_API/web/ /app/services/aHoTTS_API/web/

# =============================================================================
# Supervisord - lanza los 3 procesos en un solo contenedor
# =============================================================================
COPY supervisord.conf /app/supervisord.conf

# HF Spaces (SDK Docker) espera que el contenedor escuche en app_port (README.md, 7860)
EXPOSE 7860

HEALTHCHECK --interval=30s --timeout=10s --start-period=180s --retries=3 \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:7860/api/health')" || exit 1

CMD ["supervisord", "-n", "-c", "/app/supervisord.conf"]

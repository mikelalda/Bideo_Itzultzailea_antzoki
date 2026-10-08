# =============================================================================
# Bideo Itzultzailea - Dockerfile combinado para Hugging Face Spaces
# Empaqueta whisper-api + orchestrator en UN solo contenedor. Antzoki se
# configura como servicio GPU externo mediante ANTZOKI_API_URL.
# gestionados con supervisord (HF Spaces con SDK Docker solo admite 1 proceso
# principal y 1 puerto expuesto).
# =============================================================================
FROM python:3.11-slim-bookworm

LABEL maintainer="Bideo Itzultzailea"
LABEL description="Video translation system ES <-> EU (Whisper + MarianMT + Antzoki)"

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

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

# =============================================================================
# Supervisord - lanza los 2 procesos locales en un solo contenedor
# =============================================================================
COPY supervisord.conf /app/supervisord.conf

EXPOSE 7860

HEALTHCHECK --interval=30s --timeout=10s --start-period=180s --retries=3 \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:7860/api/health')" || exit 1

CMD ["supervisord", "-n", "-c", "/app/supervisord.conf"]

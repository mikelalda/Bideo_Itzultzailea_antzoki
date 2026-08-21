# ---------- Stage 1: base ----------
FROM python:3.11-slim AS base

# System deps for audio processing
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# ---------- Stage 2: runtime ----------
FROM base AS runtime

# Pre-download the model at build time (optional – comment out to download on first run)
# RUN python -c "from transformers import AutoModelForSpeechSeq2Seq, AutoProcessor; \
#     AutoModelForSpeechSeq2Seq.from_pretrained('xezpeleta/whisper-large-v3-eu'); \
#     AutoProcessor.from_pretrained('xezpeleta/whisper-large-v3-eu')"

ENV HOST=0.0.0.0
ENV PORT=8000
EXPOSE 8000

CMD ["python", "app.py"]

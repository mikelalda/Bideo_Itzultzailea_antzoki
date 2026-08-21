# =============================================================================
# aHoTTS API - Dockerfile
# Text-to-Speech API for Basque, Spanish, Galician, and Catalan
# Uses VITS models from HiTZ/Aholab via hitz-zentroa/aHoTTS
# =============================================================================

FROM python:3.11-slim-bookworm

LABEL maintainer="aHoTTS API"
LABEL description="TTS API for Basque, Spanish, Galician, and Catalan using VITS models"

# Avoid interactive prompts
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    wget \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Clone the aHoTTS repository
RUN git clone https://github.com/hitz-zentroa/aHoTTS.git /app/aHoTTS

# Copy the ONNX runtime library to system path and make tts binary executable
RUN cp /app/aHoTTS/libonnxruntime.so.1.13.1 /usr/lib/ \
    && ln -sf /usr/lib/libonnxruntime.so.1.13.1 /usr/lib/libonnxruntime.so \
    && ldconfig \
    && chmod +x /app/aHoTTS/ahotts/tts

# Install Python dependencies
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Pre-create voices directories
RUN mkdir -p /app/aHoTTS/ahotts/voices/eu \
    /app/aHoTTS/ahotts/voices/es \
    /app/aHoTTS/ahotts/voices/gl \
    /app/aHoTTS/ahotts/voices/ca \
    /app/aHoTTS/output

# Copy application code
COPY app/ /app/app/

# Expose the API port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

# Start the API server
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

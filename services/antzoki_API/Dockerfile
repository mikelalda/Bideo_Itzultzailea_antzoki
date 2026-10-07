FROM pytorch/pytorch:2.8.0-cuda12.8-cudnn9-runtime

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/opt/dramabox/ltx2

RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        git \
        libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt
RUN git clone https://github.com/resemble-ai/DramaBox.git /opt/dramabox \
    && cd /opt/dramabox \
    && git checkout d5372975c4a59cda6ed48e1e35f0319a4b517db5 \
    && sed -i 's/use_bnb_4bit=args.bnb_4bit, warm=True)/use_bnb_4bit=args.bnb_4bit, warm=True, audio_only=True)/' src/inference.py \
    && grep -q 'warm=True, audio_only=True' src/inference.py

RUN pip install --no-cache-dir -r /opt/dramabox/requirements.txt

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app/ /app/app/

RUN mkdir -p /models /tmp/antzoki-output

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

# Whisper API (eu / es / en)

API REST de transcripción de voz a texto utilizando el modelo [xezpeleta/whisper-large-v3-eu](https://huggingface.co/xezpeleta/whisper-large-v3-eu), un fine-tune de `whisper-large-v3` optimizado para **euskera** y compatible con **castellano** e **inglés**.

## Características

- **Transcripción** de audio en euskera, castellano e inglés.
- **Traducción** al inglés desde cualquiera de los tres idiomas.
- **Detección automática** del idioma si no se especifica.
- **Timestamps** opcionales a nivel de chunk.
- Acepta formatos de audio: `wav`, `mp3`, `ogg`, `flac`, `m4a`, etc.
- Documentación interactiva disponible en `/docs` (Swagger UI).

## Requisitos

- Python 3.10+
- GPU con CUDA recomendada (funciona en CPU pero más lento)
- ~6 GB de VRAM para el modelo en FP16

## Instalación

```bash
# Clonar el repositorio
git clone <repo-url>
cd whisper_API

# Crear entorno virtual
python -m venv venv
source venv/bin/activate   # Linux/Mac
venv\Scripts\activate      # Windows

# Instalar dependencias
pip install -r requirements.txt
```

## Uso

### Ejecutar el servidor

```bash
python app.py
```

El servidor arrancará en `http://localhost:8000`. La documentación interactiva estará en `http://localhost:8000/docs`.

### Endpoints

#### `GET /health`
Health check. Devuelve el estado del modelo y los idiomas soportados.

#### `GET /languages`
Lista los idiomas soportados: `eu`, `es`, `en`.

#### `POST /transcribe`
Transcribe un archivo de audio.

| Parámetro           | Tipo   | Requerido | Descripción                                                                 |
|---------------------|--------|-----------|-----------------------------------------------------------------------------|
| `file`              | file   | Sí        | Archivo de audio                                                            |
| `language`          | string | No        | Código de idioma: `eu`, `es`, `en`. Auto-detecta si se omite.              |
| `task`              | string | No        | `transcribe` (defecto) o `translate` (traducir al inglés)                   |
| `return_timestamps` | bool   | No        | `true` para incluir timestamps en la respuesta                              |

**Ejemplo con `curl`:**

```bash
# Transcribir en euskera
curl -X POST http://localhost:8000/transcribe \
  -F "file=@audio.wav" \
  -F "language=eu"

# Transcribir con detección automática de idioma
curl -X POST http://localhost:8000/transcribe \
  -F "file=@audio.mp3"

# Transcribir en castellano con timestamps
curl -X POST http://localhost:8000/transcribe \
  -F "file=@audio.wav" \
  -F "language=es" \
  -F "return_timestamps=true"

# Traducir euskera a inglés
curl -X POST http://localhost:8000/transcribe \
  -F "file=@audio_eu.wav" \
  -F "language=eu" \
  -F "task=translate"
```

**Respuesta:**

```json
{
  "text": "Kaixo, zer moduz zaude?",
  "language": "eu",
  "task": "transcribe",
  "duration_seconds": 3.45,
  "processing_time_seconds": 1.23
}
```

#### `POST /detect-language`
Detecta el idioma del audio (usa los primeros 30 s).

```bash
curl -X POST http://localhost:8000/detect-language \
  -F "file=@audio.wav"
```

## Docker

```bash
# Construir imagen
docker build -t whisper-api .

# Ejecutar (con GPU)
docker run --gpus all -p 8000:8000 whisper-api

# Ejecutar (solo CPU)
docker run -p 8000:8000 -e DEVICE=cpu whisper-api
```

## Variables de entorno

| Variable          | Defecto                            | Descripción                          |
|-------------------|------------------------------------|--------------------------------------|
| `MODEL_ID`        | `xezpeleta/whisper-large-v3-eu`    | ID del modelo en HuggingFace         |
| `DEVICE`          | auto (`cuda`/`cpu`)                | Dispositivo de cómputo               |
| `BATCH_SIZE`      | `16`                               | Tamaño de batch para audio largo     |
| `MAX_FILE_SIZE_MB`| `100`                              | Tamaño máximo de archivo en MB       |
| `HOST`            | `0.0.0.0`                          | Host del servidor                    |
| `PORT`            | `8000`                             | Puerto del servidor                  |

## Modelo

Este API utiliza [xezpeleta/whisper-large-v3-eu](https://huggingface.co/xezpeleta/whisper-large-v3-eu), un fine-tune de OpenAI `whisper-large-v3` entrenado con el corpus [asierhv/composite_corpus_eu_v2.1](https://huggingface.co/datasets/asierhv/composite_corpus_eu_v2.1) para ASR en euskera. Al estar basado en el modelo multilingüe whisper-large-v3, mantiene soporte para castellano e inglés.

- **WER en Common Voice 18.0 (eu)**: 4.84%
- **Arquitectura**: Whisper Large v3 (1.5B parámetros)
- **Licencia**: Apache 2.0

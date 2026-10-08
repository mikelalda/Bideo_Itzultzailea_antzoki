# Bideo Itzultzailea

Sistema local de traduccion de video Castellano <-> Euskera:

- Whisper para transcripcion.
- MarianMT para traduccion.
- Antzoki/DramaBox para sintesis expresiva y clonacion de voz.
- Antzoki LoRA para euskera y DramaBox base para castellano.

## Requisitos

- Docker Engine con Docker Compose.
- NVIDIA Container Toolkit configurado (`docker run --rm --gpus all nvidia/cuda:13.0.1-base-ubuntu24.04 nvidia-smi`).
- GPU NVIDIA con aproximadamente 24 GB de VRAM para Antzoki.
- Al menos 40 GB libres para imagenes, modelos y caches.

La configuracion se ha probado con una RTX 5090 Laptop de 24 GB.

## Puesta en marcha local

Construir e iniciar todos los servicios:

```bash
docker compose up --build -d
```

La aplicacion estara disponible en:

```text
http://localhost:7860
```

La primera descarga de Antzoki ocupa unos 17 GB. Se puede iniciar antes de
procesar un video:

```bash
curl -X POST http://localhost:8003/download
```

La descarga queda guardada en el volumen Docker `antzoki-models`. Tambien se
inicia automaticamente con la primera sintesis.

Comprobar el estado:

```bash
curl http://localhost:7860/api/health
curl http://localhost:8003/health
docker compose ps
```

Al terminar la transcripcion se ofrecen dos vistas sincronizadas. La vista de
frases completas agrupa las palabras usando los signos de fin de frase (`.`,
`?` y `!`) y se utiliza para la traduccion y la sintesis. La vista de video
genera fragmentos cortos para el resaltado durante la reproduccion y para el
SRT. Al editar cualquiera de las dos vistas, ambas se regeneran desde una linea
temporal comun de palabras. Tambien se puede descargar o importar el SRT de la
vista de video.

La opcion de mantener la voz extrae una referencia del audio original y usa
el condicionamiento nativo de DramaBox. El selector de tono permite una
locucion natural, calida, dramatica, seria o alegre. El soporte oficial de
DramaBox base es ingles; la sintesis en castellano es experimental, mientras
que el modelo Antzoki esta entrenado especificamente para euskera.

Ver registros:

```bash
docker compose logs -f antzoki-api
```

Detener el entorno sin borrar los modelos:

```bash
docker compose down
```

Para borrar tambien modelos y caches:

```bash
docker compose down -v
```

## Servicios

Docker Compose levanta tres contenedores:

- `orchestrator`: interfaz y pipeline, puerto `7860`.
- `whisper-api`: Speech-to-Text en CPU.
- `antzoki-api`: Text-to-Speech, clonacion y control de tono mediante CUDA,
  puerto `8003`.

Antzoki usa `itzune/antzoki-tts` con el checkpoint recomendado
`best_step_06850.safetensors`, DramaBox y Gemma 3 12B cuantizado. Las peticiones
se serializan para no superar la VRAM disponible.

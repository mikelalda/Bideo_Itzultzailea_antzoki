---
title: Bideo Itzultzailea
emoji: 🎬
colorFrom: blue
colorTo: green
sdk: docker
app_port: 7860
pinned: false
---

# Bideo Itzultzailea

Sistema de traducción de vídeo Castellano ↔ Euskera (Whisper + MarianMT + aHoTTS),
empaquetado como un único contenedor para Hugging Face Spaces.

Dentro del contenedor corren 3 procesos (gestionados por `supervisord`):

- **orchestrator** — Web UI + pipeline (puerto interno 7860, expuesto por el Space)
- **whisper-api** — Speech-to-Text (puerto interno 8001)
- **ahotts-api** — Text-to-Speech (puerto interno 8002)

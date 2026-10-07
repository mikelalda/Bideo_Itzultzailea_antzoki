import asyncio
import logging
import os
import sys
import uuid
from pathlib import Path

import torch
from huggingface_hub import hf_hub_download, snapshot_download

from app.config import (
    ANTZOKI_REPO,
    ANTZOKI_REVISION,
    DRAMABOX_PATH,
    DRAMABOX_REPO,
    DRAMABOX_REVISION,
    GEMMA_REPO,
    MODEL_ROOT,
    OUTPUT_PATH,
)

logger = logging.getLogger(__name__)


class AntzokiEngine:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self.model_root = Path(MODEL_ROOT)
        self.dramabox_dir = self.model_root / "dramabox"
        self.gemma_dir = self.model_root / "gemma-3-12b-it-bnb-4bit"
        self.antzoki_dir = self.model_root / "antzoki"

    @property
    def busy(self) -> bool:
        return self._lock.locked()

    @property
    def checkpoint(self) -> Path:
        return self.dramabox_dir / "dramabox-dit-v1.safetensors"

    @property
    def components(self) -> Path:
        return self.dramabox_dir / "dramabox-audio-components.safetensors"

    @property
    def lora(self) -> Path:
        return self.antzoki_dir / "best_step_06850.safetensors"

    def models_downloaded(self) -> bool:
        gemma_index = self.gemma_dir / "model.safetensors.index.json"
        return all(path.is_file() for path in (
            self.checkpoint,
            self.components,
            self.lora,
            gemma_index,
        ))

    def gpu_name(self) -> str | None:
        return torch.cuda.get_device_name(0) if torch.cuda.is_available() else None

    def _download_models(self) -> None:
        self.dramabox_dir.mkdir(parents=True, exist_ok=True)
        self.antzoki_dir.mkdir(parents=True, exist_ok=True)

        for filename in (
            "dramabox-dit-v1.safetensors",
            "dramabox-audio-components.safetensors",
        ):
            hf_hub_download(
                repo_id=DRAMABOX_REPO,
                revision=DRAMABOX_REVISION,
                filename=filename,
                local_dir=self.dramabox_dir,
            )

        hf_hub_download(
            repo_id=ANTZOKI_REPO,
            revision=ANTZOKI_REVISION,
            filename="best_step_06850.safetensors",
            local_dir=self.antzoki_dir,
        )
        snapshot_download(
            repo_id=GEMMA_REPO,
            local_dir=self.gemma_dir,
            allow_patterns=[
                "*.json",
                "*.jinja",
                "*.model",
                "*.safetensors",
            ],
        )

    async def prepare(self) -> None:
        if self.models_downloaded():
            return
        if not torch.cuda.is_available():
            raise RuntimeError("Antzoki requires an NVIDIA GPU with CUDA")
        await asyncio.to_thread(self._download_models)

    async def synthesize(self, text: str) -> str:
        if not torch.cuda.is_available():
            raise RuntimeError("Antzoki requires an NVIDIA GPU with CUDA")

        async with self._lock:
            await self.prepare()
            os.makedirs(OUTPUT_PATH, exist_ok=True)
            output_path = os.path.join(OUTPUT_PATH, f"antzoki_{uuid.uuid4().hex[:12]}.wav")
            spoken_text = text.replace('"', "'").strip()
            prompt = f'A professional narrator speaks in Basque, "{spoken_text}"'

            command = [
                sys.executable,
                os.path.join(DRAMABOX_PATH, "src", "inference.py"),
                "--no-ref",
                "--prompt", prompt,
                "--output", output_path,
                "--checkpoint", str(self.checkpoint),
                "--full-checkpoint", str(self.components),
                "--gemma-root", str(self.gemma_dir),
                "--lora", str(self.lora),
                "--lora-rank", "128",
                "--cfg-scale", "2.5",
                "--stg-scale", "1.5",
                "--modality-scale", "1",
                "--steps", "30",
                "--fps", "25",
            ]
            logger.info("Starting Antzoki synthesis for %d characters", len(text))
            process = await asyncio.create_subprocess_exec(
                *command,
                cwd=DRAMABOX_PATH,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await process.communicate()
            if process.returncode != 0:
                details = stderr.decode("utf-8", errors="replace")[-4000:]
                logger.error("Antzoki inference failed: %s", details)
                raise RuntimeError(f"Antzoki inference failed: {details}")
            if not os.path.isfile(output_path):
                raise RuntimeError("Antzoki completed without creating a WAV file")
            logger.info("Antzoki synthesis completed: %s", output_path)
            return output_path


antzoki_engine = AntzokiEngine()

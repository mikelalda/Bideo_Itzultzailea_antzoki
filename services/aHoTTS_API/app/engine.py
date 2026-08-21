# =============================================================================
# aHoTTS API - TTS Synthesis Engine
# =============================================================================

import asyncio
import os
import shutil
import uuid
import logging
from typing import Optional

from huggingface_hub import hf_hub_download

from app.config import (
    AHOTTS_BASE_PATH,
    AVAILABLE_VOICES,
    DICTS_PATH,
    HF_REPO_PATTERN,
    OUTPUT_PATH,
    TTS_BINARY,
    VOICES_PATH,
)

logger = logging.getLogger(__name__)


class TTSEngine:
    """Engine that wraps the aHoTTS binary for speech synthesis."""

    def __init__(self):
        self._download_locks: dict[str, asyncio.Lock] = {}

    def _get_download_lock(self, key: str) -> asyncio.Lock:
        if key not in self._download_locks:
            self._download_locks[key] = asyncio.Lock()
        return self._download_locks[key]

    def is_binary_available(self) -> bool:
        """Check if the TTS binary exists and is executable."""
        return os.path.isfile(TTS_BINARY) and os.access(TTS_BINARY, os.X_OK)

    def is_voice_downloaded(self, language: str, voice: str) -> bool:
        """Check if a voice model is already downloaded."""
        model_path = os.path.join(VOICES_PATH, language, voice, "vits.onnx")
        return os.path.isfile(model_path)

    def get_available_voices(self) -> dict:
        """Return available voices with download status."""
        result = {}
        for lang, voices in AVAILABLE_VOICES.items():
            result[lang] = {
                v: self.is_voice_downloaded(lang, v) for v in voices
            }
        return result

    async def download_voice(self, language: str, voice: str) -> str:
        """Download a voice model from HuggingFace if not present."""
        model_dir = os.path.join(VOICES_PATH, language, voice)
        model_file = os.path.join(model_dir, "vits.onnx")

        if os.path.isfile(model_file):
            logger.info(f"Voice {voice} ({language}) already downloaded.")
            return model_file

        lock_key = f"{language}_{voice}"
        lock = self._get_download_lock(lock_key)

        async with lock:
            # Double-check after acquiring lock
            if os.path.isfile(model_file):
                return model_file

            repo_id = HF_REPO_PATTERN.format(lang=language, voice=voice)
            logger.info(f"Downloading voice model: {repo_id}")

            try:
                # Run download in thread pool to avoid blocking
                loop = asyncio.get_event_loop()
                file_path = await loop.run_in_executor(
                    None,
                    lambda: hf_hub_download(
                        repo_id=repo_id,
                        filename="vits.onnx",
                    ),
                )

                os.makedirs(model_dir, exist_ok=True)
                shutil.copy2(file_path, model_file)
                logger.info(f"Voice {voice} ({language}) downloaded successfully.")
                return model_file

            except Exception as e:
                logger.error(f"Failed to download voice {voice} ({language}): {e}")
                raise RuntimeError(
                    f"Failed to download voice model '{voice}' for language '{language}': {e}"
                )

    def _build_command(self, text: str, language: str, voice: str, output_path: str) -> str:
        """Build the shell command for synthesis based on language."""
        voice_path = os.path.join(VOICES_PATH, language, voice)

        if language == "eu":
            return (
                f'echo "{text}" | iconv -f UTF-8 -t ISO-8859-1 '
                f"| {TTS_BINARY} -Lang={language} -Method=Vits "
                f"-HDic={DICTS_PATH}/{language}/eu_dicc "
                f"-voice_path={voice_path} "
                f"{output_path}"
            )
        elif language == "gl":
            return (
                f'echo "{text}" '
                f"| {TTS_BINARY} -Lang={language} -Method=Vits "
                f"-HDicDB={DICTS_PATH}/{language}/cotovia "
                f"-voice_path={voice_path} "
                f"{output_path}"
            )
        elif language == "ca":
            return (
                f'echo "{text}" '
                f"| {TTS_BINARY} -Lang={language} -Method=Vits "
                f"-HDic={DICTS_PATH}/{language}/espeak-ng-data "
                f"-voice_path={voice_path} "
                f"{output_path}"
            )
        elif language == "es":
            return (
                f'echo "{text}" | iconv -f UTF-8 -t ISO-8859-1 '
                f"| {TTS_BINARY} -Lang={language} -Method=Vits "
                f"-HDic={DICTS_PATH}/{language}/es_dicc "
                f"-voice_path={voice_path} "
                f"{output_path}"
            )
        else:
            raise ValueError(f"Unsupported language: {language}")

    async def synthesize(
        self, text: str, language: str, voice: str
    ) -> Optional[str]:
        """
        Synthesize text to speech.
        Returns the path to the generated WAV file.
        """
        # Validate language and voice
        if language not in AVAILABLE_VOICES:
            raise ValueError(
                f"Unsupported language '{language}'. "
                f"Available: {list(AVAILABLE_VOICES.keys())}"
            )

        if voice not in AVAILABLE_VOICES[language]:
            raise ValueError(
                f"Voice '{voice}' not available for language '{language}'. "
                f"Available: {AVAILABLE_VOICES[language]}"
            )

        # Ensure model is downloaded
        await self.download_voice(language, voice)

        # Generate unique filename
        file_id = uuid.uuid4().hex[:12]
        output_filename = f"tts_{language}_{voice}_{file_id}"
        output_path = os.path.join(OUTPUT_PATH, f"{output_filename}.wav")

        # Sanitize text for shell (escape double quotes and special chars)
        safe_text = text.replace('"', '\\"').replace("$", "\\$").replace("`", "\\`")

        # Build and execute synthesis command
        command = self._build_command(safe_text, language, voice, output_path)
        logger.info(f"Running synthesis: lang={language}, voice={voice}, text_len={len(text)}")

        try:
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=AHOTTS_BASE_PATH,
            )
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=120
            )

            if process.returncode != 0:
                error_msg = stderr.decode("utf-8", errors="replace").strip()
                logger.error(f"TTS synthesis failed: {error_msg}")
                raise RuntimeError(f"TTS synthesis failed: {error_msg}")

            if not os.path.isfile(output_path):
                raise RuntimeError(
                    "TTS synthesis completed but output file was not created."
                )

            logger.info(f"Synthesis completed: {output_path}")
            return output_path

        except asyncio.TimeoutError:
            logger.error("TTS synthesis timed out after 120 seconds.")
            raise RuntimeError("TTS synthesis timed out.")
        except Exception as e:
            logger.error(f"TTS synthesis error: {e}")
            raise


# Singleton engine instance
tts_engine = TTSEngine()

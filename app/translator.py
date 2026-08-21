# =============================================================================
# Text Translator - MarianMT models for ES ↔ EU translation
# =============================================================================

import logging
from transformers import MarianMTModel, MarianTokenizer

logger = logging.getLogger(__name__)

# Model mappings for translation directions
MODEL_MAP = {
    ("es", "eu"): "Helsinki-NLP/opus-mt-es-eu",
    ("eu", "es"): "Helsinki-NLP/opus-mt-eu-es",
}


class TextTranslator:
    """Handles text translation between Spanish and Basque using MarianMT."""

    def __init__(self):
        self.models = {}
        self.tokenizers = {}

    def load_models(self):
        """Pre-load all translation models."""
        for (src, tgt), model_name in MODEL_MAP.items():
            key = f"{src}-{tgt}"
            logger.info(f"Loading translation model: {model_name}")
            try:
                self.tokenizers[key] = MarianTokenizer.from_pretrained(model_name)
                self.models[key] = MarianMTModel.from_pretrained(model_name)
                logger.info(f"Model {model_name} loaded successfully.")
            except Exception as e:
                logger.error(f"Failed to load model {model_name}: {e}")

    def translate(self, text: str, source_lang: str, target_lang: str) -> str:
        """
        Translate text from source_lang to target_lang.
        Supported pairs: es→eu, eu→es
        """
        if not text.strip():
            return text

        key = f"{source_lang}-{target_lang}"
        if key not in self.models:
            raise ValueError(
                f"Translation pair {source_lang}→{target_lang} not supported. "
                f"Available: {list(MODEL_MAP.keys())}"
            )

        tokenizer = self.tokenizers[key]
        model = self.models[key]

        # Split long texts into sentences for better translation
        sentences = self._split_sentences(text)
        translated_parts = []

        for sentence in sentences:
            if not sentence.strip():
                translated_parts.append(sentence)
                continue

            inputs = tokenizer(
                sentence,
                return_tensors="pt",
                padding=True,
                truncation=True,
                max_length=512,
            )
            translated = model.generate(**inputs)
            result = tokenizer.decode(translated[0], skip_special_tokens=True)
            translated_parts.append(result)

        return " ".join(translated_parts)

    def _split_sentences(self, text: str) -> list:
        """Split text into sentences for better translation quality."""
        import re
        sentences = re.split(r'(?<=[.!?])\s+', text)
        return [s for s in sentences if s.strip()]

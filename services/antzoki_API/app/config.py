import os


MODEL_ROOT = os.getenv("ANTZOKI_MODEL_ROOT", "/models")
OUTPUT_PATH = os.getenv("ANTZOKI_OUTPUT_PATH", "/tmp/antzoki-output")
DRAMABOX_PATH = os.getenv("DRAMABOX_PATH", "/opt/dramabox")

DRAMABOX_REPO = "ResembleAI/Dramabox"
DRAMABOX_REVISION = "404f967f653fa1170dc15a9d1ddd3fdb9a0a842d"
ANTZOKI_REPO = "itzune/antzoki-tts"
ANTZOKI_REVISION = "3f31fdd3df4800d14b1e0f16948b0ec3a134f6b4"
GEMMA_REPO = "unsloth/gemma-3-12b-it-bnb-4bit"

MAX_TEXT_LENGTH = int(os.getenv("MAX_TEXT_LENGTH", "1000"))

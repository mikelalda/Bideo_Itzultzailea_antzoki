#!/usr/bin/env bash
set -e
BASE=/home/birt/aHoTTS_API
LOG=$BASE/setup.log
echo "[$(date)] START setup" > "$LOG"

# 1. Clone aHoTTS (binary + onnxruntime + dicts)
if [ ! -d "$BASE/aHoTTS/.git" ]; then
  echo "[$(date)] cloning aHoTTS..." >> "$LOG"
  git clone --depth 1 https://github.com/hitz-zentroa/aHoTTS.git "$BASE/aHoTTS" >> "$LOG" 2>&1
else
  echo "[$(date)] aHoTTS already cloned" >> "$LOG"
fi

# 2. onnxruntime lib + binary perms
cd "$BASE/aHoTTS"
if [ -f libonnxruntime.so.1.13.1 ]; then
  ln -sf libonnxruntime.so.1.13.1 libonnxruntime.so
fi
chmod +x ahotts/tts 2>>"$LOG" || true
echo "[$(date)] tree:" >> "$LOG"
ls -la "$BASE/aHoTTS" >> "$LOG" 2>&1
ls -la "$BASE/aHoTTS/ahotts" >> "$LOG" 2>&1

# 3. venv + deps
if [ ! -d "$BASE/.venv" ]; then
  echo "[$(date)] creating venv..." >> "$LOG"
  python3 -m venv "$BASE/.venv" >> "$LOG" 2>&1
fi
"$BASE/.venv/bin/python" -m ensurepip --upgrade >> "$LOG" 2>&1 || true
"$BASE/.venv/bin/python" -m pip install --upgrade pip >> "$LOG" 2>&1
echo "[$(date)] installing requirements..." >> "$LOG"
"$BASE/.venv/bin/pip" install -r "$BASE/requirements.txt" >> "$LOG" 2>&1
echo "[$(date)] SETUP DONE" >> "$LOG"

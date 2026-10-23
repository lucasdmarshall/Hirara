#!/usr/bin/env bash
set -euo pipefail
echo "== HiraraAudio preflight =="
python3 --version 2>/dev/null || true
for bin in ffmpeg ffprobe espeak-ng; do
  if command -v "$bin" >/dev/null 2>&1; then
    echo "$bin: ok"
  else
    echo "$bin: MISSING$([ "$bin" = espeak-ng ] && echo ' (only audio_speak needs it)')"
  fi
done
python3 - <<'PY' 2>/dev/null || echo "some imports missing"
import importlib
for mod in ("numpy", "httpx", "hirara_core", "fastapi", "uvicorn", "mcp"):
    try:
        importlib.import_module(mod)
        print(f"{mod}: ok")
    except Exception as exc:
        print(f"{mod}: MISSING ({exc})")
PY
echo "Preflight finished."

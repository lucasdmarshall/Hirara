#!/usr/bin/env bash
set -euo pipefail
echo "== HiraraUtil preflight =="
python3 --version 2>/dev/null || true
python3 - <<'PY' 2>/dev/null || echo "some imports missing"
import importlib
for mod in ("fastapi", "uvicorn", "mcp"):
    try:
        importlib.import_module(mod)
        print(f"{mod}: ok")
    except Exception as exc:
        print(f"{mod}: MISSING ({exc})")
PY
echo "Preflight finished."

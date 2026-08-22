#!/usr/bin/env bash
# Read-only survey before bringing HiraraBrowser up.
set -euo pipefail

echo "== HiraraBrowser preflight =="
echo

echo "-- python --"
python3 --version 2>/dev/null || true
echo

echo "-- deps --"
python3 - <<'PY' 2>/dev/null || echo "imports missing — pip install -r requirements.txt && playwright install chromium"
import importlib
for mod in ("playwright", "hirara_core"):
    try:
        importlib.import_module(mod)
        print(f"{mod}: ok")
    except Exception as exc:
        print(f"{mod}: MISSING ({exc})")
PY
echo

echo "-- docker --"
if command -v docker >/dev/null 2>&1; then
  docker version --format '{{.Server.Version}}' 2>/dev/null || true
  echo "port 8700 listeners:"
  ss -ltn 'sport = :8700' 2>/dev/null || netstat -ltn 2>/dev/null | grep 8700 || echo "(none)"
else
  echo "docker: NOT FOUND"
fi
echo

echo "Preflight finished (read-only)."

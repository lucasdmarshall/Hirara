#!/usr/bin/env bash
# Quick smoke: import + schema present.
set -euo pipefail
cd "$(dirname "$0")/.."
python -c "from hirarahttp import Toolset, HTTP_REQUEST_SCHEMA; assert HTTP_REQUEST_SCHEMA['name']=='http_request'; print('ok', Toolset.from_env().health())"

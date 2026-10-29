# PaddlePaddle wheels target CPython <=3.12; 3.11-slim is the safe base.
FROM python:3.11-slim

# System deps: tesseract (fallback engine), poppler (scanned-PDF rasterization),
# libgomp for paddlepaddle, libglib2.0-0 + libgl1 for the OpenCV that PaddleOCR
# pulls in (it needs libGL.so.1), certs for model downloads.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       tesseract-ocr poppler-utils libgomp1 libglib2.0-0 libgl1 ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY constraints-release.txt /app/constraints-release.txt
ENV PIP_CONSTRAINT=/app/constraints-release.txt

# Build context is the repo root (see docker-compose.yml). Install the shared
# SSRF guard first so the tool install sees hirara-core already satisfied.
COPY hirara-core ./hirara-core
RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then export PIP_CERT=/run/secrets/proxy_ca; fi; \
    pip install --no-cache-dir ./hirara-core

COPY hiraraocr/pyproject.toml hiraraocr/README.md \
     hiraraocr/LICENSE hiraraocr/NOTICE hiraraocr/requirements.txt ./
COPY hiraraocr/src ./src

# Both engines baked in, plus the HTTP + MCP front ends.
RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then export PIP_CERT=/run/secrets/proxy_ca; fi; \
    pip install --no-cache-dir ".[paddle,tesseract]" \
    "uvicorn[standard]" "fastapi" "python-multipart" "mcp"

RUN useradd --create-home --uid 10001 app \
    && mkdir -p /data && chown -R app:app /data /app
USER app

# HOME=/data so PaddleOCR's model cache (~/.paddleocr) lands in the volume and
# is downloaded once, surviving restarts.
ENV HOME=/data \
    COCR_ENGINE=paddleocr \
    COCR_DEVICE=cpu \
    COCR_ALLOW_LOCAL_PATH=false \
    COCR_ALLOW_URL_FETCH=false \
    PYTHONUNBUFFERED=1

EXPOSE 8400

CMD ["uvicorn", "hiraraocr.service:app", "--host", "0.0.0.0", "--port", "8400"]

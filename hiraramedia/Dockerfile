FROM python:3.13-slim

# FFmpeg for video_profile, zbar for barcode_read. No model weights.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg libzbar0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY constraints-release.txt /app/constraints-release.txt
ENV PIP_CONSTRAINT=/app/constraints-release.txt

# Build context is the repo root: the shared SSRF guard and hiraraaudio (for
# the soundtrack timeline) are installed from the repo.
COPY hirara-core ./hirara-core
COPY hiraraaudio ./hiraraaudio
RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then export PIP_CERT=/run/secrets/proxy_ca; fi; \
    pip install --no-cache-dir ./hirara-core ./hiraraaudio

COPY hiraramedia/pyproject.toml hiraramedia/README.md \
     hiraramedia/LICENSE hiraramedia/NOTICE hiraramedia/requirements.txt ./
COPY hiraramedia/src ./src

RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then export PIP_CERT=/run/secrets/proxy_ca; fi; \
    pip install --no-cache-dir ".[audio]" "uvicorn[standard]" "fastapi" "python-multipart" "mcp"

RUN useradd --create-home --uid 10001 app \
    && mkdir -p /data /data/tmp \
    && chown -R app:app /app /data
USER app

# Paths are inside this container only; put media to work on in /data.
ENV HM_ALLOW_LOCAL_PATH=true \
    HM_ALLOW_OUTPUT_PATH=true \
    HM_ALLOW_URL_FETCH=false \
    PYTHONUNBUFFERED=1 \
    TMPDIR=/data/tmp

EXPOSE 9500

CMD ["uvicorn", "hiraramedia.service:app", "--host", "0.0.0.0", "--port", "9500"]

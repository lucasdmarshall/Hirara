FROM python:3.13-slim

# FFmpeg does all decoding/encoding; eSpeak NG powers audio_speak. Both are
# small system packages, and there are no model weights to download.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg espeak-ng \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY constraints-release.txt /app/constraints-release.txt
ENV PIP_CONSTRAINT=/app/constraints-release.txt

# Build context is the repo root (see docker-compose.yml), so paths are
# repo-relative. Install the shared SSRF guard first, so the tool install
# below sees hirara-core already satisfied instead of hitting PyPI.
COPY hirara-core ./hirara-core
RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then export PIP_CERT=/run/secrets/proxy_ca; fi; \
    pip install --no-cache-dir ./hirara-core

COPY hiraraaudio/pyproject.toml hiraraaudio/README.md \
     hiraraaudio/LICENSE hiraraaudio/NOTICE hiraraaudio/requirements.txt ./
COPY hiraraaudio/src ./src

RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then export PIP_CERT=/run/secrets/proxy_ca; fi; \
    pip install --no-cache-dir . "uvicorn[standard]" "fastapi" "python-multipart" "mcp"

RUN useradd --create-home --uid 10001 app \
    && mkdir -p /data /data/tmp \
    && chown -R app:app /app /data
USER app

# Paths are inside this container only; put files to work on in /data.
ENV HA_ALLOW_LOCAL_PATH=true \
    HA_ALLOW_OUTPUT_PATH=true \
    HA_ALLOW_URL_FETCH=false \
    HA_MAX_BYTES=209715200 \
    HA_MAX_DURATION=14400 \
    HA_MAX_WATCHERS=4 \
    PYTHONUNBUFFERED=1 \
    TMPDIR=/data/tmp

EXPOSE 9300

CMD ["uvicorn", "hiraraaudio.service:app", "--host", "0.0.0.0", "--port", "9300"]

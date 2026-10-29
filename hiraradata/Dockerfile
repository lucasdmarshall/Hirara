FROM python:3.13-slim

# Graphviz lays out diagram_render; fonts give it and matplotlib real glyphs.
RUN apt-get update \
    && apt-get install -y --no-install-recommends graphviz fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY constraints-release.txt /app/constraints-release.txt
ENV PIP_CONSTRAINT=/app/constraints-release.txt

# Build context is the repo root so the shared SSRF guard can be installed first.
COPY hirara-core ./hirara-core
RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then export PIP_CERT=/run/secrets/proxy_ca; fi; \
    pip install --no-cache-dir ./hirara-core

COPY hiraradata/pyproject.toml hiraradata/README.md \
     hiraradata/LICENSE hiraradata/NOTICE hiraradata/requirements.txt ./
COPY hiraradata/src ./src

RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then export PIP_CERT=/run/secrets/proxy_ca; fi; \
    pip install --no-cache-dir ".[parquet]" "uvicorn[standard]" "fastapi" "python-multipart" "mcp"

RUN useradd --create-home --uid 10001 app \
    && mkdir -p /data /data/tmp \
    && chown -R app:app /app /data
USER app

# Paths are inside this container only; put files to profile in /data.
ENV HD_ALLOW_LOCAL_PATH=true \
    HD_ALLOW_OUTPUT_PATH=true \
    HD_ALLOW_URL_FETCH=false \
    MPLCONFIGDIR=/data/tmp \
    PYTHONUNBUFFERED=1 \
    TMPDIR=/data/tmp

EXPOSE 9400

CMD ["uvicorn", "hiraradata.service:app", "--host", "0.0.0.0", "--port", "9400"]

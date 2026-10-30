FROM rust:1-slim-bookworm AS native-builder
WORKDIR /native
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-venv python3-dev \
    && rm -rf /var/lib/apt/lists/*
RUN python3 -m venv /native-venv
RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then export PIP_CERT=/run/secrets/proxy_ca; fi; \
    /native-venv/bin/pip install 'maturin>=1.7,<2'
COPY hirara-native /native
RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then export CARGO_HTTP_CAINFO=/run/secrets/proxy_ca; fi; \
    /native-venv/bin/maturin build --release --locked --out /wheels

FROM python:3.13-slim

# lxml (via trafilatura) needs these at build time on slim.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libxml2-dev libxslt1-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY --from=native-builder /wheels /native-wheels
RUN pip install --no-cache-dir /native-wheels/*.whl && rm -rf /native-wheels

COPY constraints-release.txt /app/constraints-release.txt
ENV PIP_CONSTRAINT=/app/constraints-release.txt

# Shared SSRF guard first, so `pip install .` sees hirara-core already
# satisfied and never reaches for a (non-existent) PyPI release. The build
# context is the repo root, so hirara-core/ is in scope.
COPY hirara-core ./hirara-core
RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then export PIP_CERT=/run/secrets/proxy_ca; fi; \
    pip install --no-cache-dir ./hirara-core

COPY pyproject.toml ./
COPY src ./src

RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then export PIP_CERT=/run/secrets/proxy_ca; fi; \
    pip install --no-cache-dir . "uvicorn[standard]" "fastapi" "mcp"

# Runs unprivileged: this process fetches attacker-chosen URLs for a living.
RUN useradd --create-home --uid 10001 app \
    && mkdir -p /data \
    && chown -R app:app /data /app
USER app

ENV WT_CACHE_PATH=/data/cache.db \
    PYTHONUNBUFFERED=1

EXPOSE 8000

CMD ["uvicorn", "hiraraweb.service:app", "--host", "0.0.0.0", "--port", "8000"]

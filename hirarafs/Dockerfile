FROM rust:1-slim-bookworm AS native-builder
WORKDIR /native
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-venv python3-dev git \
    && rm -rf /var/lib/apt/lists/*
RUN python3 -m venv /native-venv
RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then export PIP_CERT=/run/secrets/proxy_ca; fi; \
    /native-venv/bin/pip install 'maturin>=1.7,<2'
COPY hirara-native /native
RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then export CARGO_HTTP_CAINFO=/run/secrets/proxy_ca; export GIT_SSL_CAINFO=/run/secrets/proxy_ca; fi; \
    CARGO_NET_GIT_FETCH_WITH_CLI=true /native-venv/bin/maturin build --release --locked --out /wheels

FROM python:3.13-slim

WORKDIR /app
COPY --from=native-builder /wheels /native-wheels
RUN pip install --no-cache-dir /native-wheels/*.whl && rm -rf /native-wheels

COPY constraints-release.txt /app/constraints-release.txt
ENV PIP_CONSTRAINT=/app/constraints-release.txt

COPY hirara-core ./hirara-core
RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then export PIP_CERT=/run/secrets/proxy_ca; fi; \
    pip install --no-cache-dir ./hirara-core

COPY hirarafs/pyproject.toml hirarafs/README.md \
     hirarafs/LICENSE hirarafs/NOTICE hirarafs/requirements.txt ./
COPY hirarafs/src ./src

RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then export PIP_CERT=/run/secrets/proxy_ca; fi; \
    pip install --no-cache-dir . "uvicorn[standard]" "fastapi" "mcp" "pypdfium2>=4"

RUN useradd --create-home --uid 10001 app \
    && mkdir -p /data /indexes /models \
    && chown -R app:app /app /data /indexes
USER app

# Locked down: only files under /data (bind-mount a workspace there).
ENV CFS_ALLOW_ANY_PATH=false \
    CFS_ROOTS=/data \
    CFS_MAX_BYTES=2000000 \
    CFS_MAX_WRITE_BYTES=2000000 \
    CFS_ALLOW_WRITE=true \
    PYTHONUNBUFFERED=1

EXPOSE 8900

CMD ["uvicorn", "hirarafs.service:app", "--host", "0.0.0.0", "--port", "8900"]

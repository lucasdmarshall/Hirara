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

WORKDIR /app
COPY --from=native-builder /wheels /native-wheels
RUN pip install --no-cache-dir /native-wheels/*.whl && rm -rf /native-wheels

COPY constraints-release.txt /app/constraints-release.txt
ENV PIP_CONSTRAINT=/app/constraints-release.txt

COPY hirara-core ./hirara-core
RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then export PIP_CERT=/run/secrets/proxy_ca; fi; \
    pip install --no-cache-dir ./hirara-core

COPY hirarautil/pyproject.toml hirarautil/README.md \
     hirarautil/LICENSE hirarautil/NOTICE hirarautil/requirements.txt ./
COPY hirarautil/src ./src

RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then export PIP_CERT=/run/secrets/proxy_ca; fi; \
    pip install --no-cache-dir . "uvicorn[standard]" "fastapi" "mcp"

RUN useradd --create-home --uid 10001 app && chown -R app:app /app
USER app

ENV CUTIL_MAX_INPUT_CHARS=1000000 \
    CUTIL_MAX_OUTPUT_BYTES=2000000 \
    PYTHONUNBUFFERED=1

EXPOSE 9000

CMD ["uvicorn", "hirarautil.service:app", "--host", "0.0.0.0", "--port", "9000"]

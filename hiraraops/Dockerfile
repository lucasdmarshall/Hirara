FROM python:3.13-slim

WORKDIR /app

COPY constraints-release.txt /app/constraints-release.txt
ENV PIP_CONSTRAINT=/app/constraints-release.txt

COPY hirara-core ./hirara-core
RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then export PIP_CERT=/run/secrets/proxy_ca; fi; \
    pip install --no-cache-dir ./hirara-core

COPY hiraraops/pyproject.toml hiraraops/README.md \
     hiraraops/LICENSE hiraraops/NOTICE hiraraops/requirements.txt ./
COPY hiraraops/src ./src

RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then export PIP_CERT=/run/secrets/proxy_ca; fi; \
    pip install --no-cache-dir . "uvicorn[standard]" "fastapi" "mcp"

RUN useradd --create-home --uid 10001 app \
    && mkdir -p /logs \
    && chown -R app:app /app /logs
USER app

ENV COPS_ALLOW_ANY_PATH=false \
    COPS_ROOTS=/logs \
    COPS_DEFAULT_LINES=100 \
    COPS_MAX_LINES=5000 \
    COPS_MAX_BYTES=2000000 \
    COPS_MAX_PROCESSES=500 \
    COPS_ALLOW_PROCESS_LIST=true \
    COPS_ALLOW_ENVIRONMENT_READ=true \
    COPS_REDACT_ENV=true \
    COPS_MAX_ENV_VARS=500 \
    PYTHONUNBUFFERED=1

EXPOSE 9200

CMD ["uvicorn", "hiraraops.service:app", "--host", "0.0.0.0", "--port", "9200"]

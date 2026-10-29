FROM python:3.13-slim

WORKDIR /app

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
    pip install --no-cache-dir . "uvicorn[standard]" "fastapi" "mcp"

RUN useradd --create-home --uid 10001 app \
    && mkdir -p /data \
    && chown -R app:app /app /data
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

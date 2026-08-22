FROM python:3.13-slim

WORKDIR /app

# Build context is the repo root (see docker-compose.yml). Install the shared
# core package first so the tool install sees hirara-core already satisfied.
COPY hirara-core ./hirara-core
RUN pip install --no-cache-dir ./hirara-core

COPY hirarahttp/pyproject.toml hirarahttp/README.md \
     hirarahttp/LICENSE hirarahttp/NOTICE hirarahttp/requirements.txt ./
COPY hirarahttp/src ./src

RUN pip install --no-cache-dir . "uvicorn[standard]" "fastapi" "mcp"

RUN useradd --create-home --uid 10001 app && chown -R app:app /app
USER app

ENV PYTHONUNBUFFERED=1
ENV CHTTP_ALLOW_PRIVATE_IPS=false

EXPOSE 8800

CMD ["uvicorn", "hirarahttp.service:app", "--host", "0.0.0.0", "--port", "8800"]

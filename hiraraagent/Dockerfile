FROM python:3.13-slim

WORKDIR /app

COPY constraints-release.txt /app/constraints-release.txt
ENV PIP_CONSTRAINT=/app/constraints-release.txt

COPY hirara-core ./hirara-core
RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then export PIP_CERT=/run/secrets/proxy_ca; fi; \
    pip install --no-cache-dir ./hirara-core

COPY hiraraagent/pyproject.toml hiraraagent/README.md \
     hiraraagent/LICENSE hiraraagent/NOTICE hiraraagent/requirements.txt ./
COPY hiraraagent/src ./src

RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then export PIP_CERT=/run/secrets/proxy_ca; fi; \
    pip install --no-cache-dir . "uvicorn[standard]" "fastapi" "python-multipart" "mcp"

RUN useradd --create-home --uid 10001 app \
    && mkdir -p /data \
    && chown -R app:app /app /data
USER app

# Memory, questions and reminders live in one SQLite file on the data volume.
ENV HG_DB=/data/agent.db \
    HG_MAX_WAIT=100 \
    PYTHONUNBUFFERED=1

EXPOSE 9600

CMD ["uvicorn", "hiraraagent.service:app", "--host", "0.0.0.0", "--port", "9600"]

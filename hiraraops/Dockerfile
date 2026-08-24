FROM python:3.13-slim

WORKDIR /app

COPY hiraraops/pyproject.toml hiraraops/README.md \
     hiraraops/LICENSE hiraraops/NOTICE hiraraops/requirements.txt ./
COPY hiraraops/src ./src

RUN pip install --no-cache-dir . "uvicorn[standard]" "fastapi" "mcp"

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
    PYTHONUNBUFFERED=1

EXPOSE 9200

CMD ["uvicorn", "hiraraops.service:app", "--host", "0.0.0.0", "--port", "9200"]

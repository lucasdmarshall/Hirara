FROM python:3.13-slim

WORKDIR /app

COPY hiraradb/pyproject.toml hiraradb/README.md \
     hiraradb/LICENSE hiraradb/NOTICE hiraradb/requirements.txt ./
COPY hiraradb/src ./src

RUN pip install --no-cache-dir . "uvicorn[standard]" "fastapi" "mcp"

RUN useradd --create-home --uid 10001 app \
    && mkdir -p /data \
    && chown -R app:app /app /data
USER app

ENV CDB_READONLY=true \
    CDB_ROOTS=/data \
    CDB_ALLOW_ANY_PATH=false \
    CDB_MAX_ROWS=1000 \
    CDB_PATH=/data/app.db \
    PYTHONUNBUFFERED=1

EXPOSE 9100

CMD ["uvicorn", "hiraradb.service:app", "--host", "0.0.0.0", "--port", "9100"]

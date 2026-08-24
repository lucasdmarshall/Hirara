FROM python:3.13-slim

WORKDIR /app

COPY hirarautil/pyproject.toml hirarautil/README.md \
     hirarautil/LICENSE hirarautil/NOTICE hirarautil/requirements.txt ./
COPY hirarautil/src ./src

RUN pip install --no-cache-dir . "uvicorn[standard]" "fastapi" "mcp"

RUN useradd --create-home --uid 10001 app && chown -R app:app /app
USER app

ENV CUTIL_MAX_INPUT_CHARS=1000000 \
    CUTIL_MAX_OUTPUT_BYTES=2000000 \
    PYTHONUNBUFFERED=1

EXPOSE 9000

CMD ["uvicorn", "hirarautil.service:app", "--host", "0.0.0.0", "--port", "9000"]

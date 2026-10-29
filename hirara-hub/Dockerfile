FROM python:3.13-slim

WORKDIR /app

COPY constraints-release.txt /app/constraints-release.txt
ENV PIP_CONSTRAINT=/app/constraints-release.txt

COPY hirara-core ./hirara-core
RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then export PIP_CERT=/run/secrets/proxy_ca; fi; \
    pip install --no-cache-dir ./hirara-core

COPY hirara-hub/pyproject.toml hirara-hub/README.md \
     hirara-hub/LICENSE hirara-hub/NOTICE hirara-hub/requirements.txt ./
COPY hirara-hub/src ./src

RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then export PIP_CERT=/run/secrets/proxy_ca; fi; \
    pip install --no-cache-dir . "mcp"

RUN useradd --create-home --uid 10001 app && chown -R app:app /app
USER app

ENV PYTHONUNBUFFERED=1
EXPOSE 8080

CMD ["uvicorn", "hirara_hub.service:app", "--host", "0.0.0.0", "--port", "8080"]

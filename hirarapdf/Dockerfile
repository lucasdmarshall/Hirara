FROM python:3.13-slim

WORKDIR /app

COPY constraints-release.txt /app/constraints-release.txt
ENV PIP_CONSTRAINT=/app/constraints-release.txt

# Build context is the repo root (see docker-compose.yml), so paths are
# repo-relative. Install the shared SSRF guard first, so the tool install
# below sees hirara-core already satisfied instead of hitting PyPI.
COPY hirara-core ./hirara-core
RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then export PIP_CERT=/run/secrets/proxy_ca; fi; \
    pip install --no-cache-dir ./hirara-core

COPY hirarapdf/pyproject.toml hirarapdf/README.md \
     hirarapdf/LICENSE hirarapdf/NOTICE hirarapdf/requirements.txt ./
COPY hirarapdf/src ./src

RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then export PIP_CERT=/run/secrets/proxy_ca; fi; \
    pip install --no-cache-dir . "uvicorn[standard]" "fastapi" "python-multipart" "mcp"

RUN useradd --create-home --uid 10001 app \
    && mkdir -p /data/output /data/tmp \
    && chown -R app:app /data /app
USER app

ENV CPDF_ALLOW_LOCAL_PATH=false \
    CPDF_ALLOW_URL_FETCH=false \
    PYTHONUNBUFFERED=1 \
    TMPDIR=/data/tmp

EXPOSE 8200

CMD ["uvicorn", "hirarapdf.service:app", "--host", "0.0.0.0", "--port", "8200"]

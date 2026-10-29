FROM python:3.13-slim

WORKDIR /app

COPY constraints-release.txt /app/constraints-release.txt
ENV PIP_CONSTRAINT=/app/constraints-release.txt

# Playwright needs OS deps for Chromium.
RUN apt-get update && apt-get install -y --no-install-recommends \
    chromium libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 \
    libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 \
    libgbm1 libasound2 libpango-1.0-0 libcairo2 \
    && rm -rf /var/lib/apt/lists/*

COPY hirara-core ./hirara-core
RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then export PIP_CERT=/run/secrets/proxy_ca; fi; \
    pip install --no-cache-dir ./hirara-core

COPY hirarabrowser/pyproject.toml hirarabrowser/README.md \
     hirarabrowser/LICENSE hirarabrowser/NOTICE hirarabrowser/requirements.txt ./
COPY hirarabrowser/src ./src

RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then export PIP_CERT=/run/secrets/proxy_ca; fi; \
    pip install --no-cache-dir . "uvicorn[standard]" "fastapi" "mcp"

RUN useradd --create-home --uid 10001 app && chown -R app:app /app
USER app

ENV PYTHONUNBUFFERED=1 \
    CBRO_ALLOW_PRIVATE_URLS=false \
    CBRO_HEADLESS=true \
    CBRO_EXECUTABLE_PATH=/usr/bin/chromium

EXPOSE 8700

CMD ["uvicorn", "hirarabrowser.service:app", "--host", "0.0.0.0", "--port", "8700"]

FROM python:3.13-slim

WORKDIR /app

# Playwright needs OS deps for Chromium.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 \
    libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 \
    libgbm1 libasound2 libpango-1.0-0 libcairo2 \
    && rm -rf /var/lib/apt/lists/*

COPY hirara-core ./hirara-core
RUN pip install --no-cache-dir ./hirara-core

COPY hirarabrowser/pyproject.toml hirarabrowser/README.md \
     hirarabrowser/LICENSE hirarabrowser/NOTICE hirarabrowser/requirements.txt ./
COPY hirarabrowser/src ./src

RUN pip install --no-cache-dir . "uvicorn[standard]" "fastapi" "mcp" \
    && playwright install chromium

RUN useradd --create-home --uid 10001 app && chown -R app:app /app
USER app

ENV PYTHONUNBUFFERED=1 \
    CBRO_ALLOW_PRIVATE_URLS=false \
    CBRO_HEADLESS=true

EXPOSE 8700

CMD ["uvicorn", "hirarabrowser.service:app", "--host", "0.0.0.0", "--port", "8700"]

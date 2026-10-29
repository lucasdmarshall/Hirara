FROM python:3.13-slim

WORKDIR /app

COPY constraints-release.txt /app/constraints-release.txt
ENV PIP_CONSTRAINT=/app/constraints-release.txt

COPY hirara-core ./hirara-core
RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then export PIP_CERT=/run/secrets/proxy_ca; fi; \
    pip install --no-cache-dir ./hirara-core

COPY hiraracode/pyproject.toml hiraracode/README.md \
     hiraracode/LICENSE hiraracode/NOTICE hiraracode/requirements.txt ./
COPY hiraracode/src ./src

RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then export PIP_CERT=/run/secrets/proxy_ca; fi; \
    pip install --no-cache-dir . "uvicorn[standard]" "fastapi" "mcp"

# NOTE: this service is intentionally NOT run as an unprivileged user, and the
# container is given access to the host's Docker socket (see docker-compose.yml).
# Driving the daemon is root-equivalent on the host — that is inherent to a
# Docker-isolated executor, not an oversight. The mitigation is operational:
# bind the service to loopback, put auth in front, never expose it. The code it
# runs is what gets sandboxed (sibling containers), not this process.

ENV CCODE_ALLOW_NETWORK=false \
    PYTHONUNBUFFERED=1

EXPOSE 8300

CMD ["uvicorn", "hiraracode.service:app", "--host", "0.0.0.0", "--port", "8300"]

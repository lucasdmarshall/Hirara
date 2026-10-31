# syntax=docker/dockerfile:1
FROM rust:1-slim-bookworm AS builder
WORKDIR /build
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates cmake \
    && rm -rf /var/lib/apt/lists/*
COPY hirara-connectors/Cargo.toml hirara-connectors/Cargo.lock ./
COPY hirara-connectors/src ./src
RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then export CARGO_HTTP_CAINFO=/run/secrets/proxy_ca; fi; \
    cargo build --release --locked

FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 hirara \
    && mkdir -p /data && chown 10001:10001 /data
COPY --from=builder /build/target/release/hirara-connectors /usr/local/bin/hirara-connectors
USER 10001:10001
ENV HCONNECT_BIND=0.0.0.0:9700 HCONNECT_STORE_DIR=/data
EXPOSE 9700
ENTRYPOINT ["hirara-connectors"]

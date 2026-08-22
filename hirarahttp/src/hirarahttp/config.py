"""Runtime configuration for HiraraHttp."""

from __future__ import annotations

import os
from dataclasses import dataclass


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    return int(raw) if raw else default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    return float(raw) if raw else default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    return raw.strip().lower() in {"1", "true", "yes", "on"} if raw else default


@dataclass(frozen=True)
class HttpConfig:
    """HTTP-tool knobs."""

    # Per-request timeout (seconds).
    timeout: float = 30.0

    # Cap on response body bytes (decoded / after decompression).
    max_bytes: int = 2_000_000

    # Default redirect hop budget when follow_redirects is true.
    max_redirects: int = 5

    # Cap on request body size the tool will send.
    max_request_body_bytes: int = 1_000_000

    # Cap on custom header count / total header value bytes.
    max_headers: int = 40
    max_header_bytes: int = 16_384

    # Default User-Agent when the caller does not set one.
    user_agent: str = (
        "Mozilla/5.0 (compatible; hirara/0.1; +https://github.com/lucasdmarshall/Hirara)"
    )

    # When False, resolve_target rejects private/reserved destinations.
    # True on a trusted laptop; False in the Docker image.
    allow_private_ips: bool = True

    @classmethod
    def from_env(cls) -> "HttpConfig":
        return cls(
            timeout=_env_float("CHTTP_TIMEOUT", cls.timeout),
            max_bytes=_env_int("CHTTP_MAX_BYTES", cls.max_bytes),
            max_redirects=_env_int("CHTTP_MAX_REDIRECTS", cls.max_redirects),
            max_request_body_bytes=_env_int(
                "CHTTP_MAX_REQUEST_BODY_BYTES", cls.max_request_body_bytes
            ),
            max_headers=_env_int("CHTTP_MAX_HEADERS", cls.max_headers),
            max_header_bytes=_env_int("CHTTP_MAX_HEADER_BYTES", cls.max_header_bytes),
            user_agent=(os.getenv("CHTTP_USER_AGENT") or cls.user_agent).strip()
            or cls.user_agent,
            allow_private_ips=_env_bool(
                "CHTTP_ALLOW_PRIVATE_IPS", cls.allow_private_ips
            ),
        )


__all__ = ["HttpConfig"]

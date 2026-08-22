"""The tool layer: schema and JSON-ready results.

Both front ends (HTTP service and MCP server) call into here, so the two can
never drift apart in behaviour — only in transport.

Tools: ``http_request``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from .config import HttpConfig
from .request import http_request, result_to_dict

log = logging.getLogger(__name__)


HTTP_REQUEST_SCHEMA = {
    "name": "http_request",
    "description": (
        "Send an HTTP request and return status, headers, and body. Use this "
        "for raw HTTP (any method) when you need the full response — not a "
        "cleaned page extract. URLs (and every redirect hop) are checked "
        "through Hirara's SSRF perimeter; 4xx/5xx responses are returned as "
        "data, not tool failures.\n\n"
        "Pass method, optional headers/body, and follow_redirects. Binary "
        "response bodies come back as base64 (body_encoding=base64); text "
        "and JSON as utf-8."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "http(s) URL to request.",
            },
            "method": {
                "type": "string",
                "enum": ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
                "description": "HTTP method (default GET).",
            },
            "headers": {
                "type": "object",
                "additionalProperties": {"type": "string"},
                "description": "Optional request headers (Host / hop-by-hop blocked).",
            },
            "body": {
                "type": "string",
                "description": "Optional request body (UTF-8). Not allowed with GET/HEAD.",
            },
            "timeout": {
                "type": "number",
                "minimum": 0.1,
                "description": "Request timeout in seconds.",
            },
            "follow_redirects": {
                "type": "boolean",
                "description": "Follow redirects (re-validated each hop). Default true.",
            },
            "max_redirects": {
                "type": "integer",
                "minimum": 0,
                "description": "Max redirect hops when follow_redirects is true.",
            },
            "max_bytes": {
                "type": "integer",
                "minimum": 1,
                "description": "Cap on response body bytes (server also caps).",
            },
        },
        "required": ["url"],
        "additionalProperties": False,
    },
}


def _envelope(**overrides) -> dict:
    envelope = {
        "method": None,
        "url": None,
        "final_url": None,
        "status": None,
        "reason": None,
        "request_headers": {},
        "response_headers": {},
        "body": None,
        "body_encoding": None,
        "truncated": False,
        "bytes_downloaded": None,
        "elapsed_ms": None,
        "redirects": [],
        "error": None,
    }
    envelope.update(overrides)
    return envelope


@dataclass
class Toolset:
    """HTTP tools sharing one config."""

    config: HttpConfig

    @classmethod
    def from_env(cls) -> "Toolset":
        return cls(config=HttpConfig.from_env())

    def schemas(self) -> list[dict]:
        return [HTTP_REQUEST_SCHEMA]

    def health(self) -> dict:
        return {
            "status": "ok",
            "version": "0.1.0",
            "tools": ["http_request"],
            "max_bytes": self.config.max_bytes,
            "max_redirects": self.config.max_redirects,
        }

    async def http_request(
        self,
        *,
        url: str,
        method: str = "GET",
        headers: dict[str, str] | None = None,
        body: str | None = None,
        timeout: float | None = None,
        follow_redirects: bool = True,
        max_redirects: int | None = None,
        max_bytes: int | None = None,
    ) -> dict:
        try:
            result = await http_request(
                url,
                method=method,
                headers=headers,
                body=body,
                timeout=timeout,
                follow_redirects=follow_redirects,
                max_redirects=max_redirects,
                max_bytes=max_bytes,
                config=self.config,
            )
            return result_to_dict(result)
        except Exception as exc:  # noqa: BLE001
            log.exception("http_request failed")
            return _envelope(
                method=method,
                url=url,
                error=f"http_request failed: {exc}",
            )


__all__ = [
    "HTTP_REQUEST_SCHEMA",
    "Toolset",
    "TOOL_NAMES",
    "call_tool",
    "tool_schemas",
]


TOOL_NAMES = ("http_request",)
_local_toolset: "Toolset | None" = None


def _backend() -> "Toolset":
    global _local_toolset
    if _local_toolset is None:
        _local_toolset = Toolset.from_env()
    return _local_toolset


async def call_tool(name: str, arguments: dict | None = None) -> dict:
    args = arguments or {}
    if name == "http_request":
        return await _backend().http_request(**args)
    raise KeyError(f"unknown tool: {name}")


def tool_schemas() -> list[dict]:
    return _backend().schemas()

"""The tool layer: schema and JSON-ready results.

Tools: ``decode`` (hash / jwt tools land later).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from .config import UtilConfig
from .decode import DecodeError, decode as run_decode, result_to_dict

log = logging.getLogger(__name__)


DECODE_SCHEMA = {
    "name": "decode",
    "description": (
        "Decode a string from a common encoding: base64, base64url, hex, "
        "url (percent-encoding), html entities, or unicode_escape. "
        "format=auto tries to detect. Binary results return as base64 "
        "(output_encoding=base64). Errors stay in the JSON envelope."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "input": {
                "type": "string",
                "description": "Encoded string to decode.",
            },
            "format": {
                "type": "string",
                "enum": [
                    "auto",
                    "base64",
                    "base64url",
                    "hex",
                    "url",
                    "html",
                    "unicode_escape",
                ],
                "description": "Encoding to apply (default auto).",
            },
        },
        "required": ["input"],
        "additionalProperties": False,
    },
}


def _envelope(**overrides) -> dict:
    envelope = {
        "input": None,
        "format": None,
        "detected_format": None,
        "output": None,
        "output_encoding": None,
        "is_binary": None,
        "input_chars": None,
        "output_bytes": None,
        "truncated": False,
        "error": None,
    }
    envelope.update(overrides)
    return envelope


@dataclass
class Toolset:
    """Utility tools sharing one config."""

    config: UtilConfig

    @classmethod
    def from_env(cls) -> "Toolset":
        return cls(config=UtilConfig.from_env())

    def schemas(self) -> list[dict]:
        return [DECODE_SCHEMA]

    def health(self) -> dict:
        return {
            "status": "ok",
            "version": "0.1.0",
            "tools": ["decode"],
            "max_input_chars": self.config.max_input_chars,
            "max_output_bytes": self.config.max_output_bytes,
        }

    async def decode(
        self,
        *,
        input: str,
        format: str = "auto",
    ) -> dict:
        import asyncio

        try:
            result = await asyncio.to_thread(
                run_decode,
                input,
                format=format,
                config=self.config,
            )
            return result_to_dict(result)
        except DecodeError as exc:
            return _envelope(input=input, format=format, error=str(exc))
        except Exception as exc:  # noqa: BLE001
            log.exception("decode failed")
            return _envelope(
                input=input,
                format=format,
                error=f"decode failed: {exc}",
            )


__all__ = [
    "DECODE_SCHEMA",
    "Toolset",
    "TOOL_NAMES",
    "call_tool",
    "tool_schemas",
]


TOOL_NAMES = ("decode",)
_local_toolset: "Toolset | None" = None


def _backend() -> "Toolset":
    global _local_toolset
    if _local_toolset is None:
        _local_toolset = Toolset.from_env()
    return _local_toolset


async def call_tool(name: str, arguments: dict | None = None) -> dict:
    args = arguments or {}
    if name == "decode":
        return await _backend().decode(**args)
    raise KeyError(f"unknown tool: {name}")


def tool_schemas() -> list[dict]:
    return _backend().schemas()

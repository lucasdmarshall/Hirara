"""The tool layer: schema and JSON-ready results.

Tools: ``decode``, ``hash``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from .config import UtilConfig
from .decode import DecodeError, decode as run_decode
from .decode import result_to_dict as decode_result_to_dict
from .hashing import HashError, hash_input
from .hashing import result_to_dict as hash_result_to_dict

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


HASH_SCHEMA = {
    "name": "hash",
    "description": (
        "Compute message digests (md5, sha1, sha256, sha512, sha3_*, blake2*). "
        "Pass algorithms as a string, list, or \"all\" for a common set. "
        "Input may be utf-8 text (default), base64, or hex. Digests return as "
        "hex (default) or base64."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "input": {
                "type": "string",
                "description": "String to hash (text, or encoded bytes).",
            },
            "algorithms": {
                "description": (
                    "Algorithm name, list of names, comma-separated string, "
                    "or \"all\" for md5/sha1/sha256/sha512. Default sha256."
                ),
                "oneOf": [
                    {"type": "string"},
                    {"type": "array", "items": {"type": "string"}},
                ],
            },
            "encoding": {
                "type": "string",
                "enum": ["utf-8", "ascii", "latin-1", "base64", "hex"],
                "description": "How to interpret input before hashing (default utf-8).",
            },
            "output_format": {
                "type": "string",
                "enum": ["hex", "base64"],
                "description": "Digest encoding (default hex).",
            },
        },
        "required": ["input"],
        "additionalProperties": False,
    },
}


def _decode_envelope(**overrides) -> dict:
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


def _hash_envelope(**overrides) -> dict:
    envelope = {
        "input": None,
        "input_encoding": None,
        "input_chars": None,
        "input_bytes": None,
        "algorithms": [],
        "digests": {},
        "digest": None,
        "algorithm": None,
        "output_format": None,
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
        return [DECODE_SCHEMA, HASH_SCHEMA]

    def health(self) -> dict:
        return {
            "status": "ok",
            "version": "0.1.0",
            "tools": ["decode", "hash"],
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
            return decode_result_to_dict(result)
        except DecodeError as exc:
            return _decode_envelope(input=input, format=format, error=str(exc))
        except Exception as exc:  # noqa: BLE001
            log.exception("decode failed")
            return _decode_envelope(
                input=input,
                format=format,
                error=f"decode failed: {exc}",
            )

    async def hash(
        self,
        *,
        input: str,
        algorithms: list[str] | str | None = None,
        encoding: str | None = None,
        output_format: str | None = None,
    ) -> dict:
        import asyncio

        try:
            result = await asyncio.to_thread(
                hash_input,
                input,
                algorithms=algorithms,
                encoding=encoding,
                output_format=output_format,
                config=self.config,
            )
            return hash_result_to_dict(result)
        except HashError as exc:
            return _hash_envelope(input=input, error=str(exc))
        except Exception as exc:  # noqa: BLE001
            log.exception("hash failed")
            return _hash_envelope(input=input, error=f"hash failed: {exc}")


__all__ = [
    "DECODE_SCHEMA",
    "HASH_SCHEMA",
    "Toolset",
    "TOOL_NAMES",
    "call_tool",
    "tool_schemas",
]


TOOL_NAMES = ("decode", "hash")
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
    if name == "hash":
        return await _backend().hash(**args)
    raise KeyError(f"unknown tool: {name}")


def tool_schemas() -> list[dict]:
    return _backend().schemas()

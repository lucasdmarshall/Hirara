"""Decode common encodings into text or base64.

Formats: auto, base64, base64url, hex, url, html, unicode_escape.
"""

from __future__ import annotations

import base64
import binascii
import html
import re
from dataclasses import dataclass
from urllib.parse import unquote_to_bytes

from .config import UtilConfig

FORMATS = (
    "auto",
    "base64",
    "base64url",
    "hex",
    "url",
    "html",
    "unicode_escape",
)

_HEX_RE = re.compile(r"^[0-9a-fA-F]+$")
_B64_RE = re.compile(r"^[A-Za-z0-9+/_-]+={0,2}$")


class DecodeError(ValueError):
    """Caller-facing decode validation failure."""


@dataclass
class DecodeResult:
    input: str | None = None
    format: str | None = None
    detected_format: str | None = None
    output: str | None = None
    output_encoding: str | None = None
    is_binary: bool | None = None
    input_chars: int | None = None
    output_bytes: int | None = None
    truncated: bool = False
    error: str | None = None


def result_to_dict(result: DecodeResult) -> dict:
    return {
        "input": result.input,
        "format": result.format,
        "detected_format": result.detected_format,
        "output": result.output,
        "output_encoding": result.output_encoding,
        "is_binary": result.is_binary,
        "input_chars": result.input_chars,
        "output_bytes": result.output_bytes,
        "truncated": result.truncated,
        "error": result.error,
    }


def _strip_ws(value: str) -> str:
    return "".join(value.split())


def _decode_base64(raw: str, *, urlsafe: bool) -> bytes:
    cleaned = _strip_ws(raw)
    if not cleaned:
        raise DecodeError("input is empty after whitespace strip")
    pad = (-len(cleaned)) % 4
    if pad:
        cleaned += "=" * pad
    try:
        if urlsafe:
            return base64.urlsafe_b64decode(cleaned)
        return base64.b64decode(cleaned, validate=False)
    except (binascii.Error, ValueError) as exc:
        raise DecodeError(f"invalid base64: {exc}") from exc


def _decode_hex(raw: str) -> bytes:
    cleaned = _strip_ws(raw)
    if cleaned.lower().startswith("0x"):
        cleaned = cleaned[2:]
    if not cleaned:
        raise DecodeError("hex input is empty")
    if len(cleaned) % 2 == 1:
        raise DecodeError("hex input must have an even number of digits")
    if not _HEX_RE.fullmatch(cleaned):
        raise DecodeError("hex input contains non-hex characters")
    try:
        return binascii.unhexlify(cleaned)
    except binascii.Error as exc:
        raise DecodeError(f"invalid hex: {exc}") from exc


def _decode_url(raw: str) -> bytes:
    try:
        return unquote_to_bytes(raw)
    except Exception as exc:  # noqa: BLE001
        raise DecodeError(f"invalid url encoding: {exc}") from exc


def _decode_html(raw: str) -> str:
    return html.unescape(raw)


def _decode_unicode_escape(raw: str) -> str:
    # codecs.decode with unicode_escape expects bytes-like latin-1 source.
    try:
        return raw.encode("utf-8").decode("unicode_escape")
    except UnicodeDecodeError as exc:
        raise DecodeError(f"invalid unicode_escape: {exc}") from exc


def _looks_like_hex(raw: str) -> bool:
    cleaned = _strip_ws(raw)
    if cleaned.lower().startswith("0x"):
        cleaned = cleaned[2:]
    return len(cleaned) >= 2 and len(cleaned) % 2 == 0 and bool(_HEX_RE.fullmatch(cleaned))


def _looks_like_base64(raw: str) -> bool:
    cleaned = _strip_ws(raw)
    if len(cleaned) < 4:
        return False
    if not _B64_RE.fullmatch(cleaned):
        return False
    # Prefer urlsafe when -/_ present.
    return True


def _auto_format(raw: str) -> str | None:
    stripped = raw.strip()
    if not stripped:
        return None
    if "%" in stripped and any(ch == "%" for ch in stripped):
        # Heuristic: has %XX sequences
        if re.search(r"%[0-9A-Fa-f]{2}", stripped):
            return "url"
    if "&" in stripped and (";" in stripped) and re.search(r"&(#\d+|#x[0-9A-Fa-f]+|\w+);", stripped):
        return "html"
    if "\\u" in stripped or "\\x" in stripped or "\\n" in stripped:
        return "unicode_escape"
    if _looks_like_hex(stripped) and len(_strip_ws(stripped).removeprefix("0x").removeprefix("0X")) >= 8:
        return "hex"
    cleaned = _strip_ws(stripped)
    if _looks_like_base64(cleaned):
        if "-" in cleaned or "_" in cleaned:
            return "base64url"
        return "base64"
    if _looks_like_hex(stripped):
        return "hex"
    return None


def _to_output(data: bytes | str, *, max_output_bytes: int) -> tuple[str, str, bool, int, bool]:
    """Return (output, output_encoding, is_binary, output_bytes, truncated)."""
    if isinstance(data, str):
        encoded = data.encode("utf-8")
        truncated = len(encoded) > max_output_bytes
        if truncated:
            # Truncate on character boundary approximately by cutting bytes then
            # decoding with ignore — callers see truncated=true.
            cut = encoded[:max_output_bytes].decode("utf-8", errors="ignore")
            return cut, "utf-8", False, min(len(encoded), max_output_bytes), True
        return data, "utf-8", False, len(encoded), False

    truncated = len(data) > max_output_bytes
    chunk = data[:max_output_bytes]
    try:
        text = chunk.decode("utf-8")
        return text, "utf-8", False, len(chunk), truncated
    except UnicodeDecodeError:
        return (
            base64.b64encode(chunk).decode("ascii"),
            "base64",
            True,
            len(chunk),
            truncated,
        )


def decode(
    value: str,
    *,
    format: str = "auto",
    config: UtilConfig | None = None,
) -> DecodeResult:
    """Decode ``value`` using ``format`` (or auto-detect)."""
    cfg = config or UtilConfig()
    requested = value if isinstance(value, str) else None

    if not isinstance(value, str):
        return DecodeResult(error="input must be a string")
    if value == "":
        return DecodeResult(input="", format=format, input_chars=0, error="input is required")

    fmt = (format or "auto").strip().lower()
    if fmt not in FORMATS:
        return DecodeResult(
            input=requested,
            format=fmt,
            input_chars=len(value),
            error=f"unsupported format: {format!r} (use {', '.join(FORMATS)})",
        )

    if len(value) > cfg.max_input_chars:
        return DecodeResult(
            input=requested[:200] + "…" if len(value) > 200 else requested,
            format=fmt,
            input_chars=len(value),
            error=f"input exceeds max_input_chars ({len(value)} > {cfg.max_input_chars})",
        )

    detected: str | None = None
    use = fmt
    if fmt == "auto":
        detected = _auto_format(value)
        if detected is None:
            return DecodeResult(
                input=requested,
                format="auto",
                input_chars=len(value),
                error="could not detect encoding; pass format= explicitly",
            )
        use = detected

    try:
        if use == "base64":
            data: bytes | str = _decode_base64(value, urlsafe=False)
        elif use == "base64url":
            data = _decode_base64(value, urlsafe=True)
        elif use == "hex":
            data = _decode_hex(value)
        elif use == "url":
            data = _decode_url(value)
        elif use == "html":
            data = _decode_html(value)
        elif use == "unicode_escape":
            data = _decode_unicode_escape(value)
        else:
            return DecodeResult(
                input=requested,
                format=fmt,
                detected_format=detected,
                input_chars=len(value),
                error=f"unsupported format: {use}",
            )
    except DecodeError as exc:
        return DecodeResult(
            input=requested,
            format=fmt,
            detected_format=detected or use,
            input_chars=len(value),
            error=str(exc),
        )

    output, out_enc, is_binary, out_bytes, truncated = _to_output(
        data, max_output_bytes=cfg.max_output_bytes
    )
    return DecodeResult(
        input=requested if len(requested) <= 256 else requested[:253] + "…",
        format=fmt,
        detected_format=detected or use,
        output=output,
        output_encoding=out_enc,
        is_binary=is_binary,
        input_chars=len(value),
        output_bytes=out_bytes,
        truncated=truncated,
    )


__all__ = [
    "FORMATS",
    "DecodeError",
    "DecodeResult",
    "decode",
    "result_to_dict",
]

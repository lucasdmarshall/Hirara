"""Hash strings with stdlib digest algorithms."""

from __future__ import annotations

import base64
import binascii
import hashlib
from dataclasses import dataclass, field

from .config import UtilConfig

ALGORITHMS = (
    "md5",
    "sha1",
    "sha224",
    "sha256",
    "sha384",
    "sha512",
    "sha3_224",
    "sha3_256",
    "sha3_384",
    "sha3_512",
    "blake2b",
    "blake2s",
)

_DEFAULT_ALGS = ("md5", "sha1", "sha256", "sha512")
_INPUT_ENCODINGS = frozenset({"utf-8", "utf8", "ascii", "latin-1", "latin1", "base64", "hex"})
_OUTPUT_FORMATS = frozenset({"hex", "base64"})


class HashError(ValueError):
    """Caller-facing hash validation failure."""


@dataclass
class HashResult:
    input: str | None = None
    input_encoding: str | None = None
    input_chars: int | None = None
    input_bytes: int | None = None
    algorithms: list[str] = field(default_factory=list)
    digests: dict[str, str] = field(default_factory=dict)
    digest: str | None = None
    algorithm: str | None = None
    output_format: str | None = None
    error: str | None = None


def result_to_dict(result: HashResult) -> dict:
    return {
        "input": result.input,
        "input_encoding": result.input_encoding,
        "input_chars": result.input_chars,
        "input_bytes": result.input_bytes,
        "algorithms": list(result.algorithms),
        "digests": dict(result.digests),
        "digest": result.digest,
        "algorithm": result.algorithm,
        "output_format": result.output_format,
        "error": result.error,
    }


def _normalize_input_encoding(raw: str | None) -> str:
    value = (raw or "utf-8").strip().lower()
    if value in {"utf8"}:
        return "utf-8"
    if value in {"latin1"}:
        return "latin-1"
    return value


def _normalize_output(raw: str | None) -> str:
    value = (raw or "hex").strip().lower()
    if value in {"b64"}:
        return "base64"
    return value


def _parse_algorithms(algorithms: list[str] | str | None) -> list[str]:
    if algorithms is None:
        return ["sha256"]
    if isinstance(algorithms, str):
        items = [p.strip() for p in algorithms.replace("\n", ",").split(",") if p.strip()]
    elif isinstance(algorithms, list):
        items = [str(p).strip() for p in algorithms if str(p).strip()]
    else:
        raise HashError("algorithms must be a string or list of strings")

    if not items:
        raise HashError("algorithms must be non-empty")

    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        name = item.lower().replace("-", "_")
        if name in {"all", "*"}:
            for alg in _DEFAULT_ALGS:
                if alg not in seen:
                    seen.add(alg)
                    out.append(alg)
            continue
        if name not in ALGORITHMS:
            raise HashError(
                f"unsupported algorithm: {item!r} "
                f"(use {', '.join(ALGORITHMS)}, or all)"
            )
        if name not in seen:
            seen.add(name)
            out.append(name)
    return out


def _to_bytes(value: str, encoding: str) -> tuple[bytes, str]:
    if encoding in {"base64"}:
        cleaned = "".join(value.split())
        pad = (-len(cleaned)) % 4
        if pad:
            cleaned += "=" * pad
        try:
            return base64.b64decode(cleaned, validate=False), "base64"
        except (binascii.Error, ValueError) as exc:
            raise HashError(f"invalid base64 input: {exc}") from exc
    if encoding == "hex":
        cleaned = "".join(value.split())
        if cleaned.lower().startswith("0x"):
            cleaned = cleaned[2:]
        if len(cleaned) % 2 == 1:
            raise HashError("hex input must have an even number of digits")
        try:
            return binascii.unhexlify(cleaned), "hex"
        except binascii.Error as exc:
            raise HashError(f"invalid hex input: {exc}") from exc
    if encoding not in {"utf-8", "ascii", "latin-1"}:
        raise HashError(
            f"unsupported input encoding: {encoding!r} "
            "(use utf-8, ascii, latin-1, base64, or hex)"
        )
    try:
        return value.encode(encoding), encoding
    except UnicodeEncodeError as exc:
        raise HashError(f"encode failed as {encoding}: {exc}") from exc


def _format_digest(digest: bytes, output_format: str) -> str:
    if output_format == "base64":
        return base64.b64encode(digest).decode("ascii")
    return digest.hex()


def hash_input(
    value: str,
    *,
    algorithms: list[str] | str | None = None,
    encoding: str | None = None,
    output_format: str | None = None,
    config: UtilConfig | None = None,
) -> HashResult:
    """Hash ``value`` with one or more algorithms."""
    cfg = config or UtilConfig()
    preview = value if isinstance(value, str) else None

    if not isinstance(value, str):
        return HashResult(error="input must be a string")
    if value == "" and encoding not in (None, "utf-8", "utf8", "ascii", "latin-1", "latin1"):
        # empty string is a valid hash input for text encodings
        pass
    # Allow empty string hashing (common for checksums of empty files).

    if len(value) > cfg.max_input_chars:
        return HashResult(
            input=(preview[:200] + "…") if preview and len(preview) > 200 else preview,
            input_chars=len(value),
            error=f"input exceeds max_input_chars ({len(value)} > {cfg.max_input_chars})",
        )

    enc = _normalize_input_encoding(encoding)
    if enc not in _INPUT_ENCODINGS:
        return HashResult(
            input=preview,
            input_chars=len(value),
            error=(
                f"unsupported input encoding: {encoding!r} "
                "(use utf-8, ascii, latin-1, base64, or hex)"
            ),
        )

    out_fmt = _normalize_output(output_format)
    if out_fmt not in _OUTPUT_FORMATS:
        return HashResult(
            input=preview,
            input_chars=len(value),
            error=f"unsupported output_format: {output_format!r} (use hex or base64)",
        )

    try:
        algs = _parse_algorithms(algorithms)
        data, used_enc = _to_bytes(value, enc)
    except HashError as exc:
        return HashResult(
            input=preview if preview and len(preview) <= 256 else (preview[:253] + "…" if preview else None),
            input_encoding=enc,
            input_chars=len(value),
            output_format=out_fmt,
            error=str(exc),
        )

    digests: dict[str, str] = {}
    for name in algs:
        try:
            h = hashlib.new(name)
        except ValueError as exc:
            return HashResult(
                input=preview,
                input_encoding=used_enc,
                input_chars=len(value),
                input_bytes=len(data),
                algorithms=algs,
                output_format=out_fmt,
                error=f"algorithm unavailable: {name}: {exc}",
            )
        h.update(data)
        digests[name] = _format_digest(h.digest(), out_fmt)

    single = algs[0] if len(algs) == 1 else None
    shown = preview if len(value) <= 256 else value[:253] + "…"
    return HashResult(
        input=shown,
        input_encoding=used_enc,
        input_chars=len(value),
        input_bytes=len(data),
        algorithms=algs,
        digests=digests,
        digest=digests[single] if single else None,
        algorithm=single,
        output_format=out_fmt,
    )


__all__ = [
    "ALGORITHMS",
    "HashError",
    "HashResult",
    "hash_input",
    "result_to_dict",
]

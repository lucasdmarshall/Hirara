"""JWT inspect / decode helpers (stdlib; HMAC verify optional)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass, field
from typing import Any

from .config import UtilConfig

_HS_ALGS = {
    "HS256": hashlib.sha256,
    "HS384": hashlib.sha384,
    "HS512": hashlib.sha512,
}


class JwtError(ValueError):
    """Caller-facing JWT validation failure."""


@dataclass
class JwtInspectResult:
    input: str | None = None
    input_chars: int | None = None
    segment_count: int | None = None
    signed: bool | None = None
    algorithm: str | None = None
    typ: str | None = None
    kid: str | None = None
    header: dict[str, Any] = field(default_factory=dict)
    claim_keys: list[str] = field(default_factory=list)
    claims: dict[str, Any] | None = None
    exp: int | float | None = None
    iat: int | float | None = None
    nbf: int | float | None = None
    expired: bool | None = None
    not_yet_valid: bool | None = None
    seconds_to_expiry: float | None = None
    error: str | None = None


@dataclass
class JwtDecodeResult:
    input: str | None = None
    input_chars: int | None = None
    segment_count: int | None = None
    signed: bool | None = None
    header: dict[str, Any] = field(default_factory=dict)
    payload: dict[str, Any] = field(default_factory=dict)
    signature: str | None = None
    algorithm: str | None = None
    verified: bool | None = None
    verify_attempted: bool = False
    error: str | None = None


def inspect_result_to_dict(result: JwtInspectResult) -> dict:
    return {
        "input": result.input,
        "input_chars": result.input_chars,
        "segment_count": result.segment_count,
        "signed": result.signed,
        "algorithm": result.algorithm,
        "typ": result.typ,
        "kid": result.kid,
        "header": dict(result.header),
        "claim_keys": list(result.claim_keys),
        "claims": None if result.claims is None else dict(result.claims),
        "exp": result.exp,
        "iat": result.iat,
        "nbf": result.nbf,
        "expired": result.expired,
        "not_yet_valid": result.not_yet_valid,
        "seconds_to_expiry": result.seconds_to_expiry,
        "error": result.error,
    }


def decode_result_to_dict(result: JwtDecodeResult) -> dict:
    return {
        "input": result.input,
        "input_chars": result.input_chars,
        "segment_count": result.segment_count,
        "signed": result.signed,
        "header": dict(result.header),
        "payload": dict(result.payload),
        "signature": result.signature,
        "algorithm": result.algorithm,
        "verified": result.verified,
        "verify_attempted": result.verify_attempted,
        "error": result.error,
    }


def _strip_bearer(raw: str) -> str:
    value = raw.strip()
    if value.lower().startswith("bearer "):
        return value[7:].strip()
    return value


def _b64url_decode(segment: str) -> bytes:
    cleaned = segment.strip()
    pad = "=" * ((4 - len(cleaned) % 4) % 4)
    try:
        return base64.urlsafe_b64decode(cleaned + pad)
    except Exception as exc:  # noqa: BLE001
        raise JwtError(f"invalid base64url segment: {exc}") from exc


def _parse_json_segment(segment: str, *, label: str) -> dict[str, Any]:
    try:
        raw = _b64url_decode(segment)
    except JwtError:
        raise
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise JwtError(f"invalid JWT {label} JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise JwtError(f"JWT {label} must be a JSON object")
    return data


def _split_token(token: str) -> tuple[str, list[str]]:
    cleaned = _strip_bearer(token)
    if not cleaned:
        raise JwtError("input is required")
    parts = cleaned.split(".")
    if len(parts) not in {2, 3}:
        raise JwtError(
            f"JWT must have 2 or 3 dot-separated segments, got {len(parts)}"
        )
    return cleaned, parts


def _as_numeric_time(value: Any) -> int | float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        try:
            return float(value) if "." in value else int(value)
        except ValueError:
            return None
    return None


def _verify_hmac(
    *,
    header_b64: str,
    payload_b64: str,
    signature_b64: str,
    algorithm: str,
    secret: str,
) -> bool:
    digestmod = _HS_ALGS.get(algorithm)
    if digestmod is None:
        raise JwtError(
            f"HMAC verification only supports {', '.join(sorted(_HS_ALGS))}; "
            f"got {algorithm!r}"
        )
    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    expected = hmac.new(
        secret.encode("utf-8"), signing_input, digestmod
    ).digest()
    try:
        actual = _b64url_decode(signature_b64)
    except JwtError:
        return False
    return hmac.compare_digest(expected, actual)


def jwt_inspect(
    input: str,
    *,
    include_claims: bool = False,
    config: UtilConfig | None = None,
    now: float | None = None,
) -> JwtInspectResult:
    """Inspect JWT structure, header, and time claims (no signature verify)."""
    cfg = config or UtilConfig()
    if not isinstance(input, str):
        return JwtInspectResult(error="input must be a string")
    if len(input) > cfg.max_input_chars:
        return JwtInspectResult(
            input=input[:200],
            input_chars=len(input),
            error=(
                f"input exceeds max_input_chars "
                f"({len(input)} > {cfg.max_input_chars})"
            ),
        )

    try:
        cleaned, parts = _split_token(input)
        header = _parse_json_segment(parts[0], label="header")
        payload = _parse_json_segment(parts[1], label="payload")
    except JwtError as exc:
        return JwtInspectResult(
            input=input[:200] if isinstance(input, str) else None,
            input_chars=len(input) if isinstance(input, str) else None,
            error=str(exc),
        )

    signed = len(parts) == 3 and bool(parts[2])
    exp = _as_numeric_time(payload.get("exp"))
    iat = _as_numeric_time(payload.get("iat"))
    nbf = _as_numeric_time(payload.get("nbf"))
    clock = time.time() if now is None else float(now)

    expired: bool | None = None
    not_yet_valid: bool | None = None
    seconds_to_expiry: float | None = None
    if exp is not None:
        expired = clock >= float(exp)
        seconds_to_expiry = float(exp) - clock
    if nbf is not None:
        not_yet_valid = clock < float(nbf)

    return JwtInspectResult(
        input=cleaned,
        input_chars=len(cleaned),
        segment_count=len(parts),
        signed=signed,
        algorithm=header.get("alg") if isinstance(header.get("alg"), str) else None,
        typ=header.get("typ") if isinstance(header.get("typ"), str) else None,
        kid=header.get("kid") if isinstance(header.get("kid"), str) else None,
        header=header,
        claim_keys=sorted(payload.keys()),
        claims=payload if include_claims else None,
        exp=exp,
        iat=iat,
        nbf=nbf,
        expired=expired,
        not_yet_valid=not_yet_valid,
        seconds_to_expiry=seconds_to_expiry,
    )


def jwt_decode(
    input: str,
    *,
    verify: bool = False,
    secret: str | None = None,
    include_signature: bool = False,
    config: UtilConfig | None = None,
) -> JwtDecodeResult:
    """Decode JWT header and payload; optionally verify HS* with a secret."""
    cfg = config or UtilConfig()
    if not isinstance(input, str):
        return JwtDecodeResult(error="input must be a string")
    if len(input) > cfg.max_input_chars:
        return JwtDecodeResult(
            input=input[:200],
            input_chars=len(input),
            error=(
                f"input exceeds max_input_chars "
                f"({len(input)} > {cfg.max_input_chars})"
            ),
        )

    try:
        cleaned, parts = _split_token(input)
        header = _parse_json_segment(parts[0], label="header")
        payload = _parse_json_segment(parts[1], label="payload")
    except JwtError as exc:
        return JwtDecodeResult(
            input=input[:200] if isinstance(input, str) else None,
            input_chars=len(input) if isinstance(input, str) else None,
            error=str(exc),
        )

    signature = parts[2] if len(parts) == 3 else None
    signed = bool(signature)
    algorithm = header.get("alg") if isinstance(header.get("alg"), str) else None

    verified: bool | None = None
    verify_attempted = bool(verify)
    if verify:
        if not secret:
            return JwtDecodeResult(
                input=cleaned,
                input_chars=len(cleaned),
                segment_count=len(parts),
                signed=signed,
                header=header,
                payload=payload,
                signature=signature if include_signature else None,
                algorithm=algorithm,
                verified=None,
                verify_attempted=True,
                error="secret is required when verify=true",
            )
        if not signed or signature is None:
            return JwtDecodeResult(
                input=cleaned,
                input_chars=len(cleaned),
                segment_count=len(parts),
                signed=False,
                header=header,
                payload=payload,
                signature=None,
                algorithm=algorithm,
                verified=False,
                verify_attempted=True,
                error="token has no signature to verify",
            )
        if algorithm == "none":
            return JwtDecodeResult(
                input=cleaned,
                input_chars=len(cleaned),
                segment_count=len(parts),
                signed=signed,
                header=header,
                payload=payload,
                signature=signature if include_signature else None,
                algorithm=algorithm,
                verified=False,
                verify_attempted=True,
                error="refusing to verify alg=none",
            )
        try:
            verified = _verify_hmac(
                header_b64=parts[0],
                payload_b64=parts[1],
                signature_b64=signature,
                algorithm=algorithm or "",
                secret=secret,
            )
        except JwtError as exc:
            return JwtDecodeResult(
                input=cleaned,
                input_chars=len(cleaned),
                segment_count=len(parts),
                signed=signed,
                header=header,
                payload=payload,
                signature=signature if include_signature else None,
                algorithm=algorithm,
                verified=None,
                verify_attempted=True,
                error=str(exc),
            )
        if not verified:
            return JwtDecodeResult(
                input=cleaned,
                input_chars=len(cleaned),
                segment_count=len(parts),
                signed=signed,
                header=header,
                payload=payload,
                signature=signature if include_signature else None,
                algorithm=algorithm,
                verified=False,
                verify_attempted=True,
                error="signature verification failed",
            )

    return JwtDecodeResult(
        input=cleaned,
        input_chars=len(cleaned),
        segment_count=len(parts),
        signed=signed,
        header=header,
        payload=payload,
        signature=signature if include_signature else None,
        algorithm=algorithm,
        verified=verified,
        verify_attempted=verify_attempted,
    )


__all__ = [
    "JwtDecodeResult",
    "JwtError",
    "JwtInspectResult",
    "decode_result_to_dict",
    "inspect_result_to_dict",
    "jwt_decode",
    "jwt_inspect",
]

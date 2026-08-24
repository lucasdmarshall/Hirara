"""jwt_inspect / jwt_decode unit tests."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

from hirarautil.config import UtilConfig
from hirarautil.jwt import jwt_decode, jwt_inspect


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _make_token(
    header: dict,
    payload: dict,
    *,
    secret: str | None = "secret",
    include_sig: bool = True,
) -> str:
    h = _b64url(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    p = _b64url(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    if not include_sig:
        return f"{h}.{p}."
    if secret is None:
        return f"{h}.{p}"
    alg = header.get("alg", "HS256")
    digestmod = {
        "HS256": hashlib.sha256,
        "HS384": hashlib.sha384,
        "HS512": hashlib.sha512,
    }[alg]
    sig = hmac.new(
        secret.encode("utf-8"), f"{h}.{p}".encode("ascii"), digestmod
    ).digest()
    return f"{h}.{p}.{_b64url(sig)}"


def test_jwt_inspect_basic():
    now = int(time.time())
    token = _make_token(
        {"alg": "HS256", "typ": "JWT", "kid": "k1"},
        {"sub": "user", "exp": now + 3600, "iat": now, "role": "admin"},
    )
    r = jwt_inspect(token, now=float(now))
    assert r.error is None
    assert r.algorithm == "HS256"
    assert r.typ == "JWT"
    assert r.kid == "k1"
    assert r.signed is True
    assert r.expired is False
    assert set(r.claim_keys) == {"sub", "exp", "iat", "role"}
    assert r.claims is None
    assert r.seconds_to_expiry == 3600


def test_jwt_inspect_include_claims_and_bearer():
    token = _make_token({"alg": "HS256", "typ": "JWT"}, {"hello": "world"})
    r = jwt_inspect(f"Bearer {token}", include_claims=True)
    assert r.error is None
    assert r.claims == {"hello": "world"}
    assert not r.input.startswith("Bearer")


def test_jwt_inspect_expired():
    now = 1_700_000_000
    token = _make_token({"alg": "HS256"}, {"exp": now - 10, "nbf": now + 100})
    r = jwt_inspect(token, now=float(now))
    assert r.expired is True
    assert r.not_yet_valid is True


def test_jwt_decode_and_verify():
    token = _make_token({"alg": "HS256", "typ": "JWT"}, {"sub": "a"})
    r = jwt_decode(token)
    assert r.error is None
    assert r.payload["sub"] == "a"
    assert r.verified is None
    assert r.verify_attempted is False
    assert r.signature is None

    ok = jwt_decode(token, verify=True, secret="secret", include_signature=True)
    assert ok.error is None
    assert ok.verified is True
    assert ok.signature

    bad = jwt_decode(token, verify=True, secret="wrong")
    assert bad.verified is False
    assert bad.error is not None


def test_jwt_decode_missing_secret_and_bad_token():
    token = _make_token({"alg": "HS256"}, {"a": 1})
    r = jwt_decode(token, verify=True)
    assert r.error is not None
    assert "secret" in r.error

    bad = jwt_decode("not-a-jwt")
    assert bad.error is not None


def test_jwt_input_cap():
    token = _make_token({"alg": "HS256"}, {"a": 1})
    r = jwt_inspect(token, config=UtilConfig(max_input_chars=5))
    assert r.error is not None
    assert "max_input_chars" in r.error

"""hash unit tests."""

from __future__ import annotations

import hashlib

from hirarautil.config import UtilConfig
from hirarautil.hashing import hash_input


def test_sha256_default():
    r = hash_input("hello")
    assert r.error is None
    assert r.algorithm == "sha256"
    assert r.digest == hashlib.sha256(b"hello").hexdigest()
    assert r.digests["sha256"] == r.digest


def test_all_algorithms():
    r = hash_input("x", algorithms="all")
    assert r.error is None
    assert set(r.algorithms) == {"md5", "sha1", "sha256", "sha512"}
    assert r.digest is None
    assert r.digests["md5"] == hashlib.md5(b"x").hexdigest()


def test_base64_input():
    r = hash_input("aGVsbG8=", encoding="base64", algorithms="sha256")
    assert r.error is None
    assert r.digest == hashlib.sha256(b"hello").hexdigest()


def test_hex_input_and_base64_output():
    import base64

    r = hash_input(
        "68656c6c6f",
        encoding="hex",
        algorithms="md5",
        output_format="base64",
    )
    assert r.error is None
    assert r.output_format == "base64"
    assert r.digest == base64.b64encode(hashlib.md5(b"hello").digest()).decode("ascii")


def test_empty_string():
    r = hash_input("", algorithms="sha256")
    assert r.error is None
    assert r.digest == hashlib.sha256(b"").hexdigest()


def test_bad_algorithm():
    r = hash_input("x", algorithms="nope")
    assert r.error and "unsupported algorithm" in r.error


def test_input_cap():
    r = hash_input("ab", config=UtilConfig(max_input_chars=1))
    assert r.error and "max_input_chars" in r.error

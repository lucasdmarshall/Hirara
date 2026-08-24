"""decode unit tests."""

from __future__ import annotations

import base64

from hirarautil.config import UtilConfig
from hirarautil.decode import decode


def test_base64():
    r = decode("aGVsbG8=", format="base64")
    assert r.error is None
    assert r.output == "hello"
    assert r.output_encoding == "utf-8"
    assert r.is_binary is False


def test_base64url():
    # "hello?" -> urlsafe without padding quirks
    raw = base64.urlsafe_b64encode(b"hello?").decode("ascii").rstrip("=")
    r = decode(raw, format="base64url")
    assert r.error is None
    assert r.output == "hello?"


def test_hex():
    r = decode("68656c6c6f", format="hex")
    assert r.output == "hello"


def test_url():
    r = decode("hello%20world%21", format="url")
    assert r.output == "hello world!"


def test_html():
    r = decode("a &amp; b &lt;c&gt;", format="html")
    assert r.output == "a & b <c>"


def test_unicode_escape():
    r = decode(r"hi\n\u0041", format="unicode_escape")
    assert r.output == "hi\nA"


def test_auto_base64():
    r = decode("aGVsbG8=", format="auto")
    assert r.error is None
    assert r.detected_format == "base64"
    assert r.output == "hello"


def test_auto_url():
    r = decode("a%20b", format="auto")
    assert r.detected_format == "url"
    assert r.output == "a b"


def test_binary_as_base64():
    data = bytes(range(256))
    enc = base64.b64encode(data).decode("ascii")
    r = decode(enc, format="base64")
    assert r.is_binary is True
    assert r.output_encoding == "base64"
    assert base64.b64decode(r.output) == data


def test_bad_hex():
    r = decode("zz", format="hex")
    assert r.error and "hex" in r.error.lower()


def test_empty():
    r = decode("")
    assert r.error and "required" in r.error


def test_input_cap():
    r = decode("aa", format="hex", config=UtilConfig(max_input_chars=1))
    assert r.error and "max_input_chars" in r.error

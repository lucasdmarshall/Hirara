"""file_read — temp files, no network."""

from __future__ import annotations

import base64

import pytest

from hirarafs.config import FsConfig
from hirarafs.reader import file_read, resolve_path


def test_read_text(tmp_path):
    f = tmp_path / "hello.txt"
    f.write_text("hello hirara\n", encoding="utf-8")
    r = file_read(str(f), config=FsConfig(allow_any_path=True))
    assert r.error is None
    assert r.content == "hello hirara\n"
    assert r.encoding == "utf-8"
    assert r.is_binary is False
    assert r.size == len("hello hirara\n")
    assert r.bytes_read == r.size
    assert r.truncated is False


def test_read_binary_auto(tmp_path):
    f = tmp_path / "blob.bin"
    data = bytes(range(256))
    f.write_bytes(data)
    r = file_read(str(f), config=FsConfig(allow_any_path=True))
    assert r.error is None
    assert r.encoding == "base64"
    assert r.is_binary is True
    assert base64.b64decode(r.content) == data


def test_max_bytes_truncates(tmp_path):
    f = tmp_path / "big.txt"
    f.write_text("abcdefghij", encoding="utf-8")
    r = file_read(
        str(f),
        max_bytes=4,
        config=FsConfig(allow_any_path=True, max_bytes=100),
    )
    assert r.error is None
    assert r.content == "abcd"
    assert r.truncated is True
    assert r.bytes_read == 4
    assert r.size == 10


def test_offset(tmp_path):
    f = tmp_path / "offset.txt"
    f.write_text("0123456789", encoding="utf-8")
    r = file_read(
        str(f),
        offset=3,
        max_bytes=4,
        config=FsConfig(allow_any_path=True),
    )
    assert r.content == "3456"
    assert r.offset == 3
    assert r.truncated is True


def test_roots_allow_and_deny(tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    ok = allowed / "ok.txt"
    ok.write_text("ok", encoding="utf-8")
    outside = tmp_path / "secret.txt"
    outside.write_text("nope", encoding="utf-8")

    cfg = FsConfig(roots=(str(allowed),), allow_any_path=False)
    good = file_read(str(ok), config=cfg)
    assert good.error is None
    assert good.content == "ok"

    bad = file_read(str(outside), config=cfg)
    assert bad.error and "outside allowed roots" in bad.error


def test_roots_required_when_locked(tmp_path):
    f = tmp_path / "x.txt"
    f.write_text("x", encoding="utf-8")
    r = file_read(str(f), config=FsConfig(roots=(), allow_any_path=False))
    assert r.error and "no filesystem roots" in r.error


def test_missing_file(tmp_path):
    r = file_read(str(tmp_path / "missing.txt"), config=FsConfig(allow_any_path=True))
    assert r.error and "not found" in r.error


def test_directory_rejected(tmp_path):
    r = file_read(str(tmp_path), config=FsConfig(allow_any_path=True))
    assert r.error and "not a regular file" in r.error


def test_resolve_path(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("a", encoding="utf-8")
    resolved = resolve_path(str(f), config=FsConfig(allow_any_path=True))
    assert resolved == f.resolve()


def test_explicit_base64(tmp_path):
    f = tmp_path / "t.txt"
    f.write_text("hi", encoding="utf-8")
    r = file_read(str(f), encoding="base64", config=FsConfig(allow_any_path=True))
    assert r.encoding == "base64"
    assert base64.b64decode(r.content) == b"hi"

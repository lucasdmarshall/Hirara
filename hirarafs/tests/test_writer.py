"""file_write — temp files, no network."""

from __future__ import annotations

import base64

from hirarafs.config import FsConfig
from hirarafs.reader import file_read
from hirarafs.writer import file_write


def test_write_and_read_roundtrip(tmp_path):
    f = tmp_path / "out.txt"
    cfg = FsConfig(allow_any_path=True)
    w = file_write(str(f), "hello\n", config=cfg)
    assert w.error is None
    assert w.created is True
    assert w.bytes_written == 6
    assert f.read_text(encoding="utf-8") == "hello\n"

    r = file_read(str(f), config=cfg)
    assert r.content == "hello\n"


def test_append(tmp_path):
    f = tmp_path / "a.txt"
    cfg = FsConfig(allow_any_path=True)
    file_write(str(f), "ab", config=cfg)
    w = file_write(str(f), "cd", append=True, config=cfg)
    assert w.error is None
    assert w.appended is True
    assert w.created is False
    assert f.read_text(encoding="utf-8") == "abcd"


def test_overwrite_false(tmp_path):
    f = tmp_path / "x.txt"
    f.write_text("old", encoding="utf-8")
    w = file_write(
        str(f),
        "new",
        overwrite=False,
        config=FsConfig(allow_any_path=True),
    )
    assert w.error and "already exists" in w.error
    assert f.read_text(encoding="utf-8") == "old"


def test_create_parents(tmp_path):
    target = tmp_path / "nested" / "dir" / "f.txt"
    cfg = FsConfig(roots=(str(tmp_path),), allow_any_path=False)
    w = file_write(str(target), "ok", create_parents=True, config=cfg)
    assert w.error is None
    assert target.read_text(encoding="utf-8") == "ok"


def test_create_parents_required(tmp_path):
    target = tmp_path / "missing" / "f.txt"
    w = file_write(
        str(target),
        "x",
        create_parents=False,
        config=FsConfig(allow_any_path=True),
    )
    assert w.error and "parent directory does not exist" in w.error


def test_roots_deny_write(tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "nope.txt"
    cfg = FsConfig(roots=(str(allowed),), allow_any_path=False)
    w = file_write(str(outside), "x", config=cfg)
    assert w.error and "outside allowed roots" in w.error
    assert not outside.exists()


def test_base64_write(tmp_path):
    f = tmp_path / "b.bin"
    data = bytes(range(32))
    w = file_write(
        str(f),
        base64.b64encode(data).decode("ascii"),
        encoding="base64",
        config=FsConfig(allow_any_path=True),
    )
    assert w.error is None
    assert f.read_bytes() == data


def test_max_write_bytes(tmp_path):
    f = tmp_path / "big.txt"
    w = file_write(
        str(f),
        "hello",
        max_bytes=2,
        config=FsConfig(allow_any_path=True),
    )
    assert w.error and "exceeds max_bytes" in w.error
    assert not f.exists()


def test_allow_write_false(tmp_path):
    f = tmp_path / "x.txt"
    w = file_write(
        str(f),
        "x",
        config=FsConfig(allow_any_path=True, allow_write=False),
    )
    assert w.error and "disabled" in w.error
    assert not f.exists()

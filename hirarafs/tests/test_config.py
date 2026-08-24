"""Config defaults / env."""

from hirarafs.config import FsConfig


def test_defaults():
    cfg = FsConfig()
    assert cfg.max_bytes == 2_000_000
    assert cfg.max_write_bytes == 2_000_000
    assert cfg.roots == ()
    assert cfg.allow_any_path is True
    assert cfg.allow_write is True
    assert cfg.default_encoding == "auto"


def test_from_env(monkeypatch):
    monkeypatch.setenv("CFS_MAX_BYTES", "1000")
    monkeypatch.setenv("CFS_MAX_WRITE_BYTES", "500")
    monkeypatch.setenv("CFS_ROOTS", "/data,/tmp/ws")
    monkeypatch.setenv("CFS_ALLOW_ANY_PATH", "false")
    monkeypatch.setenv("CFS_ALLOW_WRITE", "false")
    monkeypatch.setenv("CFS_DEFAULT_ENCODING", "base64")
    cfg = FsConfig.from_env()
    assert cfg.max_bytes == 1000
    assert cfg.max_write_bytes == 500
    assert cfg.roots == ("/data", "/tmp/ws")
    assert cfg.allow_any_path is False
    assert cfg.allow_write is False
    assert cfg.default_encoding == "base64"

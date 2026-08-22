"""Config defaults / env."""

from hirarahttp.config import HttpConfig


def test_defaults():
    cfg = HttpConfig()
    assert cfg.timeout == 30.0
    assert cfg.max_bytes == 2_000_000
    assert cfg.max_redirects == 5
    assert cfg.allow_private_ips is True


def test_from_env(monkeypatch):
    monkeypatch.setenv("CHTTP_TIMEOUT", "12")
    monkeypatch.setenv("CHTTP_MAX_BYTES", "1000")
    monkeypatch.setenv("CHTTP_MAX_REDIRECTS", "2")
    monkeypatch.setenv("CHTTP_ALLOW_PRIVATE_IPS", "false")
    cfg = HttpConfig.from_env()
    assert cfg.timeout == 12.0
    assert cfg.max_bytes == 1000
    assert cfg.max_redirects == 2
    assert cfg.allow_private_ips is False

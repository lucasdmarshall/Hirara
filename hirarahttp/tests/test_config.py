"""Config defaults / env."""

from hirarahttp.config import HttpConfig


def test_defaults():
    cfg = HttpConfig()
    assert cfg.timeout == 30.0
    assert cfg.max_bytes == 2_000_000
    assert cfg.max_redirects == 5
    assert cfg.allow_private_ips is True
    assert cfg.history_size == 100
    assert cfg.history_body_chars == 32_768
    assert cfg.enum_concurrency == 8
    assert cfg.enum_max_paths == 200
    assert cfg.enum_timeout == 10.0
    assert cfg.param_test_max_values == 20
    assert cfg.param_test_concurrency == 4


def test_from_env(monkeypatch):
    monkeypatch.setenv("CHTTP_TIMEOUT", "12")
    monkeypatch.setenv("CHTTP_MAX_BYTES", "1000")
    monkeypatch.setenv("CHTTP_MAX_REDIRECTS", "2")
    monkeypatch.setenv("CHTTP_ALLOW_PRIVATE_IPS", "false")
    monkeypatch.setenv("CHTTP_HISTORY_SIZE", "25")
    monkeypatch.setenv("CHTTP_HISTORY_BODY_CHARS", "500")
    monkeypatch.setenv("CHTTP_ENUM_CONCURRENCY", "4")
    monkeypatch.setenv("CHTTP_ENUM_MAX_PATHS", "50")
    monkeypatch.setenv("CHTTP_ENUM_TIMEOUT", "3.5")
    monkeypatch.setenv("CHTTP_PARAM_TEST_MAX_VALUES", "7")
    monkeypatch.setenv("CHTTP_PARAM_TEST_CONCURRENCY", "2")
    cfg = HttpConfig.from_env()
    assert cfg.timeout == 12.0
    assert cfg.max_bytes == 1000
    assert cfg.max_redirects == 2
    assert cfg.allow_private_ips is False
    assert cfg.history_size == 25
    assert cfg.history_body_chars == 500
    assert cfg.enum_concurrency == 4
    assert cfg.enum_max_paths == 50
    assert cfg.enum_timeout == 3.5
    assert cfg.param_test_max_values == 7
    assert cfg.param_test_concurrency == 2

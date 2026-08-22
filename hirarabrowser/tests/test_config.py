"""Config defaults / env."""

from hirarabrowser.config import BrowserConfig


def test_defaults():
    cfg = BrowserConfig()
    assert cfg.headless is True
    assert cfg.nav_timeout == 30.0
    assert cfg.max_sessions == 8
    assert cfg.allow_private_urls is True


def test_from_env(monkeypatch):
    monkeypatch.setenv("CBRO_HEADLESS", "false")
    monkeypatch.setenv("CBRO_NAV_TIMEOUT", "12")
    monkeypatch.setenv("CBRO_MAX_SESSIONS", "3")
    monkeypatch.setenv("CBRO_ALLOW_PRIVATE_URLS", "false")
    monkeypatch.setenv("CBRO_BROWSER", "firefox")
    cfg = BrowserConfig.from_env()
    assert cfg.headless is False
    assert cfg.nav_timeout == 12.0
    assert cfg.max_sessions == 3
    assert cfg.allow_private_urls is False
    assert cfg.browser_channel == "firefox"

"""Config defaults and env overrides."""

from __future__ import annotations

from hiraranet.config import DEFAULT_RECORD_TYPES, NetConfig


def test_defaults():
    cfg = NetConfig()
    assert cfg.default_record_types == DEFAULT_RECORD_TYPES
    assert cfg.timeout == 5.0
    assert cfg.max_types == 8
    assert cfg.annotate_ips is True
    assert cfg.nameserver is None


def test_from_env(monkeypatch):
    monkeypatch.setenv("CNET_TIMEOUT", "2.5")
    monkeypatch.setenv("CNET_MAX_TYPES", "3")
    monkeypatch.setenv("CNET_MAX_ANSWERS", "10")
    monkeypatch.setenv("CNET_DEFAULT_RECORD_TYPES", "mx, txt")
    monkeypatch.setenv("CNET_NAMESERVER", "1.1.1.1")
    monkeypatch.setenv("CNET_ANNOTATE_IPS", "false")
    cfg = NetConfig.from_env()
    assert cfg.timeout == 2.5
    assert cfg.max_types == 3
    assert cfg.max_answers == 10
    assert cfg.default_record_types == ("MX", "TXT")
    assert cfg.nameserver == "1.1.1.1"
    assert cfg.annotate_ips is False

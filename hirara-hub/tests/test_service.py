"""Auth dependency + config behaviour."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

import hirara_hub.service as svc
from hirara_hub.config import HubConfig


def test_auth_disabled_without_token():
    assert HubConfig(token=None).auth_enabled is False
    assert HubConfig(token="x").auth_enabled is True


@pytest.mark.asyncio
async def test_require_auth_enforced_only_when_token_set(monkeypatch):
    # token configured → header must match
    monkeypatch.setattr(svc, "_config", HubConfig(token="secret"))
    with pytest.raises(HTTPException):
        await svc.require_auth(None)
    with pytest.raises(HTTPException):
        await svc.require_auth("Bearer wrong")
    await svc.require_auth("Bearer secret")  # correct → no raise

    # no token → open, any header (or none) passes
    monkeypatch.setattr(svc, "_config", HubConfig(token=None))
    await svc.require_auth(None)


def test_from_env_reads_token_and_urls(monkeypatch):
    monkeypatch.setenv("HUB_TOKEN", "abc")
    monkeypatch.setenv("HUB_HIRARAREADER_URL", "http://reader:9999")
    monkeypatch.setenv("HUB_HIRARANET_URL", "http://net:8600")
    cfg = HubConfig.from_env()
    assert cfg.token == "abc"
    assert cfg.service_urls["hirarareader"] == "http://reader:9999"
    assert cfg.service_urls["hiraranet"] == "http://net:8600"

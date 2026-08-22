"""Toolset orchestration — schema and envelope."""

from __future__ import annotations

import dns.rdatatype
import pytest

from hiraranet.config import NetConfig
from hiraranet.tools import DNS_LOOKUP_SCHEMA, Toolset

from conftest import FakeAnswer, FakeResolver, FakeRRset


def _toolset(**cfg) -> Toolset:
    return Toolset(config=NetConfig(**cfg))


def test_schema_is_agent_ready():
    assert DNS_LOOKUP_SCHEMA["name"] == "dns_lookup"
    props = DNS_LOOKUP_SCHEMA["input_schema"]["properties"]
    assert {"name", "record_types", "nameserver"} <= set(props)
    assert "name" in DNS_LOOKUP_SCHEMA["input_schema"]["required"]


@pytest.mark.asyncio
async def test_dns_lookup_happy_path(monkeypatch):
    import hiraranet.tools as tools_module
    from hiraranet import lookup as lookup_module

    FakeResolver.responses = {
        ("example.com", dns.rdatatype.A): FakeAnswer(
            FakeRRset(dns.rdatatype.A, 60, ["93.184.216.34"])
        ),
        ("example.com", dns.rdatatype.AAAA): FakeAnswer(
            FakeRRset(dns.rdatatype.AAAA, 60, ["2606:2800::1"])
        ),
    }

    def fake_lookup(name, **kwargs):
        kwargs = {**kwargs, "resolver_factory": lambda **kw: FakeResolver()}
        return lookup_module.lookup_dns(name, **kwargs)

    monkeypatch.setattr(tools_module, "lookup_dns", fake_lookup)

    r = await _toolset().dns_lookup(name="example.com")
    assert r["error"] is None
    assert r["name"] == "example.com"
    assert r["answer_count"] >= 1
    assert r["answers"][0]["type"] == "A"


@pytest.mark.asyncio
async def test_missing_name_returns_envelope():
    r = await _toolset().dns_lookup(name="")
    assert r["error"]
    assert set(r) >= {
        "name",
        "record_types",
        "answers",
        "answer_count",
        "truncated",
        "nameserver",
        "error",
    }


@pytest.mark.asyncio
async def test_health_and_schemas():
    ts = _toolset()
    h = ts.health()
    assert h["status"] == "ok"
    assert "dns_lookup" in h["tools"]
    schemas = ts.schemas()
    assert schemas[0]["name"] == "dns_lookup"

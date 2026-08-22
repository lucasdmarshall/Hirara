"""Toolset orchestration — schema and envelope."""

from __future__ import annotations

import dns.rdatatype
import pytest

from hiraranet.config import NetConfig
from hiraranet.tools import DNS_LOOKUP_SCHEMA, PORT_SCAN_SCHEMA, SERVICE_ENUM_SCHEMA, Toolset

from conftest import FakeAnswer, FakeResolver, FakeRRset


def _toolset(**cfg) -> Toolset:
    return Toolset(config=NetConfig(**cfg))


def test_schema_is_agent_ready():
    assert DNS_LOOKUP_SCHEMA["name"] == "dns_lookup"
    props = DNS_LOOKUP_SCHEMA["input_schema"]["properties"]
    assert {"name", "record_types", "nameserver"} <= set(props)
    assert "name" in DNS_LOOKUP_SCHEMA["input_schema"]["required"]

    assert PORT_SCAN_SCHEMA["name"] == "port_scan"
    scan_props = PORT_SCAN_SCHEMA["input_schema"]["properties"]
    assert {"host", "ports", "timeout", "concurrency"} <= set(scan_props)
    assert "host" in PORT_SCAN_SCHEMA["input_schema"]["required"]

    assert SERVICE_ENUM_SCHEMA["name"] == "service_enum"
    enum_props = SERVICE_ENUM_SCHEMA["input_schema"]["properties"]
    assert {"host", "ports", "timeout", "concurrency", "tls"} <= set(enum_props)


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
async def test_port_scan_happy_path(monkeypatch):
    import hiraranet.tools as tools_module
    from hiraranet import scan as scan_module

    async def _open_connector(host, port, timeout):
        return "open" if port == 443 else "closed"

    async def fake_scan(host, **kwargs):
        kwargs = {
            **kwargs,
            "connector": _open_connector,
            "resolver": lambda h: ("203.0.113.9", True, None),
        }
        return await scan_module.scan_ports(host, **kwargs)

    monkeypatch.setattr(tools_module, "scan_ports", fake_scan)
    r = await _toolset().port_scan(host="example.com", ports=[80, 443])
    assert r["error"] is None
    assert r["open_ports"] == [443]
    assert r["open_count"] == 1


@pytest.mark.asyncio
async def test_service_enum_happy_path(monkeypatch):
    import hiraranet.tools as tools_module
    from hiraranet import enum_svc as enum_module

    async def _prober(host, port, timeout, use_tls):
        return {
            "status": "open",
            "banner": "SSH-2.0-OpenSSH_9.6",
            "service": "ssh",
            "product": "OpenSSH_9.6",
            "tls": False,
            "error": None,
        }

    async def fake_enum(host, **kwargs):
        kwargs = {
            **kwargs,
            "prober": _prober,
            "resolver": lambda h: ("203.0.113.9", True, None),
        }
        return await enum_module.enum_services(host, **kwargs)

    monkeypatch.setattr(tools_module, "enum_services", fake_enum)
    r = await _toolset().service_enum(host="example.com", ports=[22])
    assert r["error"] is None
    assert r["service_count"] == 1
    assert r["services"][0]["service"] == "ssh"


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
    assert h["tools"] == ["dns_lookup", "port_scan", "service_enum"]
    names = [s["name"] for s in ts.schemas()]
    assert names == ["dns_lookup", "port_scan", "service_enum"]

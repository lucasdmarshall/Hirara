"""service_enum domain logic — fake prober, no network."""

from __future__ import annotations

import pytest

from hiraranet.config import NetConfig
from hiraranet.enum_svc import classify_banner, enum_result_to_dict, enum_services


def test_classify_ssh_banner():
    service, product = classify_banner("SSH-2.0-OpenSSH_9.6", 22)
    assert service == "ssh"
    assert product == "OpenSSH_9.6"


def test_classify_http_server_header():
    banner = "HTTP/1.1 200 OK\nServer: nginx/1.24.0\n"
    service, product = classify_banner(banner, 80)
    assert service == "http"
    assert product == "nginx/1.24.0"


def test_classify_falls_back_to_port_hint():
    service, product = classify_banner(None, 5432)
    assert service == "postgresql"
    assert product is None


@pytest.mark.asyncio
async def test_enum_identifies_open_services():
    async def prober(host: str, port: int, timeout: float, use_tls: bool) -> dict:
        assert host == "203.0.113.50"
        if port == 22:
            return {
                "status": "open",
                "banner": "SSH-2.0-OpenSSH_9.6",
                "service": "ssh",
                "product": "OpenSSH_9.6",
                "tls": False,
                "error": None,
            }
        if port == 80:
            return {
                "status": "open",
                "banner": "HTTP/1.1 200 OK\nServer: demo\n",
                "service": "http",
                "product": "demo",
                "tls": False,
                "error": None,
            }
        return {
            "status": "closed",
            "banner": None,
            "service": None,
            "product": None,
            "tls": False,
            "error": None,
        }

    r = await enum_services(
        "203.0.113.50",
        ports=[22, 80, 81],
        prober=prober,
        resolver=lambda h: (h, True, None),
    )
    assert r.error is None
    assert len(r.services) == 2
    assert {s["port"] for s in r.services} == {22, 80}
    by_port = {x.port: x for x in r.results}
    assert by_port[22].service == "ssh"
    assert by_port[80].product == "demo"
    assert by_port[81].status == "closed"


@pytest.mark.asyncio
async def test_enum_missing_host():
    r = await enum_services("")
    assert r.error and "required" in r.error


@pytest.mark.asyncio
async def test_enum_result_to_dict_shape():
    async def prober(host, port, timeout, use_tls):
        return {
            "status": "open",
            "banner": "SSH-2.0-x",
            "service": "ssh",
            "product": "x",
            "tls": False,
            "error": None,
        }

    r = await enum_services(
        "203.0.113.7",
        ports=[22],
        prober=prober,
        resolver=lambda h: (h, True, None),
        config=NetConfig(annotate_ips=True),
    )
    d = enum_result_to_dict(r)
    assert set(d) >= {
        "host",
        "ip",
        "ports",
        "results",
        "services",
        "service_count",
        "duration_ms",
        "routable",
        "block_reason",
        "truncated",
        "error",
    }
    assert d["service_count"] == 1

"""port_scan domain logic — fake connector, no network."""

from __future__ import annotations

import pytest

from hiraranet.config import NetConfig
from hiraranet.scan import parse_ports, scan_ports, scan_result_to_dict


def test_parse_ports_list_and_ranges():
    assert parse_ports([80, 443], default=(), max_ports=10) == [80, 443]
    assert parse_ports(["22", "8000-8002"], default=(), max_ports=10) == [
        22,
        8000,
        8001,
        8002,
    ]
    assert parse_ports("80,443,22", default=(), max_ports=10) == [80, 443, 22]


def test_parse_ports_rejects_bad_input():
    with pytest.raises(Exception, match="empty"):
        parse_ports([], default=(), max_ports=10)
    with pytest.raises(Exception, match="out of range"):
        parse_ports([0], default=(), max_ports=10)
    with pytest.raises(Exception, match="at most"):
        parse_ports(list(range(1, 20)), default=(), max_ports=5)


@pytest.mark.asyncio
async def test_scan_open_closed_timeout():
    async def connector(host: str, port: int, timeout: float) -> str:
        assert host == "203.0.113.10"
        return {80: "open", 81: "closed", 82: "timeout"}[port]

    r = await scan_ports(
        "203.0.113.10",
        ports=[80, 81, 82],
        connector=connector,
        resolver=lambda h: (h, True, None),
        config=NetConfig(annotate_ips=True),
    )
    assert r.error is None
    assert r.ip == "203.0.113.10"
    assert r.open_ports == [80]
    by_port = {x.port: x.status for x in r.results}
    assert by_port == {80: "open", 81: "closed", 82: "timeout"}
    assert r.routable is True


@pytest.mark.asyncio
async def test_scan_annotates_private_ip():
    async def connector(host: str, port: int, timeout: float) -> str:
        return "open"

    r = await scan_ports(
        "127.0.0.1",
        ports=[80],
        connector=connector,
        # use real resolve_host path via IP literal
    )
    assert r.error is None
    assert r.ip == "127.0.0.1"
    assert r.routable is False
    assert r.block_reason and "not globally routable" in r.block_reason
    assert r.open_ports == [80]


@pytest.mark.asyncio
async def test_scan_missing_host():
    r = await scan_ports("")
    assert r.error and "required" in r.error


@pytest.mark.asyncio
async def test_scan_uses_default_ports_when_omitted():
    seen: list[int] = []

    async def connector(host: str, port: int, timeout: float) -> str:
        seen.append(port)
        return "closed"

    cfg = NetConfig(default_scan_ports=(22, 80), max_scan_ports=10)
    r = await scan_ports(
        "203.0.113.1",
        ports=None,
        connector=connector,
        resolver=lambda h: ("203.0.113.1", True, None),
        config=cfg,
    )
    assert r.error is None
    assert seen == [22, 80]


@pytest.mark.asyncio
async def test_scan_result_to_dict_shape():
    async def connector(host: str, port: int, timeout: float) -> str:
        return "open"

    r = await scan_ports(
        "203.0.113.5",
        ports=[443],
        connector=connector,
        resolver=lambda h: (h, True, None),
    )
    d = scan_result_to_dict(r)
    assert set(d) >= {
        "host",
        "ip",
        "ports",
        "results",
        "open_ports",
        "open_count",
        "duration_ms",
        "routable",
        "block_reason",
        "truncated",
        "error",
    }
    assert d["open_count"] == 1

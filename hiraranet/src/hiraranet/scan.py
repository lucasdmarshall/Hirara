"""TCP port scanning — connect probes, no raw packets.

Resolves the target once, then tries a TCP connect against each requested
port under a concurrency cap. Injectable ``connector`` keeps unit tests
offline.
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import socket
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable

from hirara_core import check_ip

from .config import DEFAULT_SCAN_PORTS, NetConfig

log = logging.getLogger(__name__)

# Back-compat alias for callers/tests that imported DEFAULT_PORTS from here.
DEFAULT_PORTS = DEFAULT_SCAN_PORTS

# connector(host, port, timeout) -> "open" | "closed" | "timeout" | "error:<msg>"
Connector = Callable[[str, int, float], Awaitable[str]]


class ScanError(ValueError):
    """Caller-facing port_scan failure (bad input)."""


@dataclass(frozen=True)
class PortResult:
    port: int
    status: str  # open | closed | timeout | error
    latency_ms: float | None = None
    error: str | None = None


@dataclass
class ScanResult:
    host: str
    ip: str | None = None
    ports: list[int] = field(default_factory=list)
    results: list[PortResult] = field(default_factory=list)
    open_ports: list[int] = field(default_factory=list)
    duration_ms: float | None = None
    routable: bool | None = None
    block_reason: str | None = None
    truncated: bool = False
    error: str | None = None


def _normalize_host(host: str) -> str:
    cleaned = (host or "").strip().rstrip(".")
    if not cleaned:
        raise ScanError("host is required")
    if len(cleaned) > 253:
        raise ScanError("host exceeds 253 characters")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in cleaned):
        raise ScanError("host contains control characters")
    return cleaned


def parse_ports(
    ports: list[int | str] | str | None,
    *,
    default: tuple[int, ...],
    max_ports: int,
) -> list[int]:
    """Parse a ports argument into a sorted unique list of ints.

    Accepts:
    - ``None`` → ``default``
    - ``[80, 443]`` or ``["80", "443", "8000-8010"]``
    - ``"80,443,8000-8010"``
    """
    if ports is None:
        raw_items: list[int | str] = list(default)
    elif isinstance(ports, str):
        raw_items = [p.strip() for p in ports.split(",") if p.strip()]
    else:
        raw_items = list(ports)

    if not raw_items:
        raise ScanError("ports must not be empty")

    seen: set[int] = set()
    ordered: list[int] = []

    def _add(port: int) -> None:
        if port < 1 or port > 65535:
            raise ScanError(f"port out of range: {port}")
        if port not in seen:
            seen.add(port)
            ordered.append(port)

    for item in raw_items:
        if isinstance(item, int):
            _add(item)
            continue
        text = str(item).strip()
        if not text:
            raise ScanError("empty port entry")
        if "-" in text:
            left, _, right = text.partition("-")
            try:
                start, end = int(left.strip()), int(right.strip())
            except ValueError as exc:
                raise ScanError(f"invalid port range: {text!r}") from exc
            if start > end:
                raise ScanError(f"invalid port range: {text!r}")
            if end - start + 1 > max_ports:
                raise ScanError(
                    f"port range {text!r} exceeds max_ports ({max_ports})"
                )
            for p in range(start, end + 1):
                _add(p)
        else:
            try:
                _add(int(text))
            except ValueError as exc:
                raise ScanError(f"invalid port: {text!r}") from exc

    if len(ordered) > max_ports:
        raise ScanError(f"at most {max_ports} ports per call (got {len(ordered)})")
    return ordered


def resolve_host(host: str) -> tuple[str, str | None, str | None]:
    """Return (ip, routable, block_reason). Prefer IPv4 when available."""
    try:
        ipaddress.ip_address(host)
        reason = check_ip(host)
        return host, reason is None, reason
    except ValueError:
        pass

    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ScanError(f"cannot resolve {host!r}: {exc}") from exc
    if not infos:
        raise ScanError(f"{host!r} resolved to no addresses")

    # Prefer IPv4 for simpler connect semantics; fall back to first address.
    addresses = [info[4][0] for info in infos]
    v4 = [a for a in addresses if ":" not in a]
    ip = v4[0] if v4 else addresses[0]
    reason = check_ip(ip)
    return ip, reason is None, reason


async def _default_connector(host: str, port: int, timeout: float) -> str:
    try:
        _reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=timeout,
        )
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:  # noqa: BLE001
            pass
        return "open"
    except asyncio.TimeoutError:
        return "timeout"
    except ConnectionRefusedError:
        return "closed"
    except OSError as exc:
        # Network unreachable / no route / filtered-ish failures.
        return f"error:{exc}"


async def _probe(
    connector: Connector,
    host: str,
    port: int,
    timeout: float,
) -> PortResult:
    started = time.perf_counter()
    outcome = await connector(host, port, timeout)
    elapsed = (time.perf_counter() - started) * 1000.0
    if outcome.startswith("error:"):
        return PortResult(
            port=port,
            status="error",
            latency_ms=round(elapsed, 2),
            error=outcome[len("error:") :],
        )
    return PortResult(
        port=port,
        status=outcome,
        latency_ms=round(elapsed, 2),
    )


async def scan_ports(
    host: str,
    *,
    ports: list[int | str] | str | None = None,
    timeout: float | None = None,
    concurrency: int | None = None,
    config: NetConfig | None = None,
    connector: Connector | None = None,
    resolver: Callable[[str], tuple[str, str | None, str | None]] | None = None,
) -> ScanResult:
    """TCP-connect scan ``host`` for the requested ports."""
    cfg = config or NetConfig()
    try:
        target = _normalize_host(host)
        port_list = parse_ports(
            ports, default=cfg.default_scan_ports, max_ports=cfg.max_scan_ports
        )
        resolve = resolver or resolve_host
        ip, routable, block_reason = resolve(target)
    except ScanError as exc:
        return ScanResult(host=(host or "").strip(), error=str(exc))

    per_port_timeout = cfg.scan_timeout if timeout is None else float(timeout)
    if per_port_timeout <= 0:
        return ScanResult(host=target, ip=ip, error="timeout must be > 0")
    workers = cfg.scan_concurrency if concurrency is None else int(concurrency)
    if workers < 1:
        return ScanResult(host=target, ip=ip, error="concurrency must be >= 1")
    workers = min(workers, len(port_list))

    connect = connector or _default_connector
    sem = asyncio.Semaphore(workers)
    started = time.perf_counter()

    async def _one(port: int) -> PortResult:
        async with sem:
            return await _probe(connect, ip, port, per_port_timeout)

    results = list(await asyncio.gather(*[_one(p) for p in port_list]))
    results.sort(key=lambda r: r.port)
    open_ports = [r.port for r in results if r.status == "open"]
    duration_ms = round((time.perf_counter() - started) * 1000.0, 2)

    return ScanResult(
        host=target,
        ip=ip,
        ports=port_list,
        results=results,
        open_ports=open_ports,
        duration_ms=duration_ms,
        routable=routable if cfg.annotate_ips else None,
        block_reason=block_reason if cfg.annotate_ips else None,
        truncated=False,
        error=None,
    )


def scan_result_to_dict(result: ScanResult) -> dict:
    return {
        "host": result.host,
        "ip": result.ip,
        "ports": result.ports,
        "results": [
            {
                "port": r.port,
                "status": r.status,
                "latency_ms": r.latency_ms,
                "error": r.error,
            }
            for r in result.results
        ],
        "open_ports": result.open_ports,
        "open_count": len(result.open_ports),
        "duration_ms": result.duration_ms,
        "routable": result.routable,
        "block_reason": result.block_reason,
        "truncated": result.truncated,
        "error": result.error,
    }


__all__ = [
    "DEFAULT_PORTS",
    "PortResult",
    "ScanError",
    "ScanResult",
    "parse_ports",
    "resolve_host",
    "scan_ports",
    "scan_result_to_dict",
]

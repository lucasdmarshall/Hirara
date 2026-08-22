"""Service enumeration — TCP connect + banner / lightweight probes.

For each port: connect, read an optional greeting, optionally send a short
probe, classify the response. Injectable ``prober`` keeps unit tests offline.
"""

from __future__ import annotations

import asyncio
import logging
import re
import ssl
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable

from .config import NetConfig
from .scan import ScanError, parse_ports, resolve_host

log = logging.getLogger(__name__)

# Well-known port → likely service when no banner is available.
PORT_HINTS: dict[int, str] = {
    21: "ftp",
    22: "ssh",
    23: "telnet",
    25: "smtp",
    53: "dns",
    80: "http",
    110: "pop3",
    111: "rpcbind",
    135: "msrpc",
    139: "netbios-ssn",
    143: "imap",
    443: "https",
    445: "smb",
    465: "smtps",
    587: "submission",
    993: "imaps",
    995: "pop3s",
    1433: "mssql",
    1521: "oracle",
    2049: "nfs",
    3306: "mysql",
    3389: "rdp",
    5432: "postgresql",
    5900: "vnc",
    6379: "redis",
    8080: "http-alt",
    8443: "https-alt",
    9200: "elasticsearch",
    27017: "mongodb",
}

# Ports where we send an HTTP-ish probe if the peer stays silent.
HTTP_PROBE_PORTS = frozenset({80, 443, 8080, 8000, 8008, 8081, 8443, 8888, 9000})

# Ports where we attempt a TLS handshake before reading.
TLS_PORTS = frozenset({443, 465, 993, 995, 8443})

_BANNER_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^SSH-", re.I), "ssh"),
    (re.compile(r"^HTTP/", re.I), "http"),
    (re.compile(r"^220[\s-].*SMTP", re.I), "smtp"),
    (re.compile(r"^220[\s-].*FTP", re.I), "ftp"),
    (re.compile(r"^220[\s-]", re.I), "smtp-or-ftp"),
    (re.compile(r"^\+OK", re.I), "pop3"),
    (re.compile(r"^\* OK", re.I), "imap"),
    (re.compile(r"^RFB ", re.I), "vnc"),
    (re.compile(r"^-ERR", re.I), "pop3"),
    (re.compile(r"^ redis_version", re.I), "redis"),
    (re.compile(r"^\$\d+", re.I), "redis"),
    (re.compile(r"elasticsearch", re.I), "elasticsearch"),
    (re.compile(r"mongodb|ismaster|ismaster", re.I), "mongodb"),
    (re.compile(r"mysql|mariadb", re.I), "mysql"),
    (re.compile(r"postgres|postgresql", re.I), "postgresql"),
]

# prober(host, port, timeout, use_tls) -> dict with keys:
#   status, banner, service, product, tls, error
Prober = Callable[[str, int, float, bool], Awaitable[dict]]


@dataclass(frozen=True)
class ServiceResult:
    port: int
    status: str  # open | closed | timeout | error
    service: str | None = None
    product: str | None = None
    banner: str | None = None
    tls: bool = False
    latency_ms: float | None = None
    error: str | None = None


@dataclass
class EnumResult:
    host: str
    ip: str | None = None
    ports: list[int] = field(default_factory=list)
    results: list[ServiceResult] = field(default_factory=list)
    services: list[dict] = field(default_factory=list)
    duration_ms: float | None = None
    routable: bool | None = None
    block_reason: str | None = None
    truncated: bool = False
    error: str | None = None


def _sanitize_banner(raw: bytes, *, max_chars: int) -> str:
    text = raw.decode("utf-8", errors="replace")
    # Collapse binary noise for agent readability.
    text = "".join(ch if 32 <= ord(ch) < 127 or ch in "\t\n\r" else "." for ch in text)
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if len(text) > max_chars:
        text = text[:max_chars]
    return text


def classify_banner(banner: str | None, port: int) -> tuple[str | None, str | None]:
    """Return (service, product) from a banner + port hint."""
    product = None
    service = None
    if banner:
        for pattern, name in _BANNER_RULES:
            if pattern.search(banner):
                service = name
                break
        # Product guesses from common Server: / OpenSSH lines.
        m = re.search(r"Server:\s*([^\r\n]+)", banner, re.I)
        if m:
            product = m.group(1).strip()
            if service is None:
                service = "http"
        m = re.search(r"SSH-2\.0-(\S+)", banner)
        if m:
            product = m.group(1)
            service = "ssh"
        m = re.search(r"^(220[\s-].+)$", banner, re.M)
        if m and product is None:
            product = m.group(1).strip()[:120]

    if service is None:
        service = PORT_HINTS.get(port)
    return service, product


def _should_tls(port: int, tls: bool | None) -> bool:
    if tls is not None:
        return tls
    return port in TLS_PORTS


async def _read_some(reader: asyncio.StreamReader, *, timeout: float, limit: int) -> bytes:
    try:
        return await asyncio.wait_for(reader.read(limit), timeout=timeout)
    except asyncio.TimeoutError:
        return b""


async def _default_prober(host: str, port: int, timeout: float, use_tls: bool) -> dict:
    ssl_ctx = None
    if use_tls:
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE

    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port, ssl=ssl_ctx, server_hostname=host if use_tls else None),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        return {"status": "timeout", "banner": None, "service": None, "product": None, "tls": use_tls, "error": None}
    except ConnectionRefusedError:
        return {"status": "closed", "banner": None, "service": None, "product": None, "tls": use_tls, "error": None}
    except ssl.SSLError as exc:
        # TLS failed — report as open-but-not-tls if we forced TLS; caller may retry plain.
        return {
            "status": "open",
            "banner": None,
            "service": PORT_HINTS.get(port),
            "product": None,
            "tls": False,
            "error": f"tls: {exc}",
        }
    except OSError as exc:
        return {
            "status": "error",
            "banner": None,
            "service": None,
            "product": None,
            "tls": use_tls,
            "error": str(exc),
        }

    banner_raw = b""
    try:
        # Many services greet first (SSH/SMTP/FTP). Wait briefly.
        banner_raw = await _read_some(reader, timeout=min(timeout, 1.0), limit=1024)

        if not banner_raw and (port in HTTP_PROBE_PORTS or port not in PORT_HINTS):
            probe = (
                f"HEAD / HTTP/1.0\r\nHost: {host}\r\nUser-Agent: hiraranet/0.1\r\n"
                f"Connection: close\r\n\r\n"
            ).encode()
            writer.write(probe)
            await writer.drain()
            banner_raw = await _read_some(reader, timeout=min(timeout, 1.5), limit=2048)

        if not banner_raw and port == 6379:
            writer.write(b"PING\r\n")
            await writer.drain()
            banner_raw = await _read_some(reader, timeout=min(timeout, 1.0), limit=256)

        if not banner_raw and port in {3306, 5432, 27017}:
            # Just keep whatever greeting arrived; binary protocols often greet.
            pass
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:  # noqa: BLE001
            pass

    banner = _sanitize_banner(banner_raw, max_chars=512) if banner_raw else None
    service, product = classify_banner(banner, port)
    return {
        "status": "open",
        "banner": banner,
        "service": service,
        "product": product,
        "tls": use_tls,
        "error": None,
    }


async def _probe_one(
    prober: Prober,
    host: str,
    port: int,
    timeout: float,
    tls: bool | None,
    max_banner: int,
) -> ServiceResult:
    started = time.perf_counter()
    use_tls = _should_tls(port, tls)
    outcome = await prober(host, port, timeout, use_tls)

    # If TLS was assumed and failed hard, retry plain once.
    if (
        use_tls
        and outcome.get("status") == "open"
        and outcome.get("error")
        and str(outcome.get("error", "")).startswith("tls:")
        and tls is None
    ):
        outcome = await prober(host, port, timeout, False)

    elapsed = (time.perf_counter() - started) * 1000.0
    banner = outcome.get("banner")
    if isinstance(banner, str) and len(banner) > max_banner:
        banner = banner[:max_banner]

    return ServiceResult(
        port=port,
        status=str(outcome.get("status") or "error"),
        service=outcome.get("service"),
        product=outcome.get("product"),
        banner=banner,
        tls=bool(outcome.get("tls")),
        latency_ms=round(elapsed, 2),
        error=outcome.get("error"),
    )


async def enum_services(
    host: str,
    *,
    ports: list[int | str] | str | None = None,
    timeout: float | None = None,
    concurrency: int | None = None,
    tls: bool | None = None,
    config: NetConfig | None = None,
    prober: Prober | None = None,
    resolver: Callable[[str], tuple[str, bool | None, str | None]] | None = None,
) -> EnumResult:
    """Identify services on ``host`` for the requested ports."""
    cfg = config or NetConfig()
    try:
        target = (host or "").strip().rstrip(".")
        if not target:
            raise ScanError("host is required")
        port_list = parse_ports(
            ports, default=cfg.default_scan_ports, max_ports=cfg.max_scan_ports
        )
        resolve = resolver or resolve_host
        ip, routable, block_reason = resolve(target)
    except ScanError as exc:
        return EnumResult(host=(host or "").strip(), error=str(exc))
    except Exception as exc:  # noqa: BLE001
        return EnumResult(host=(host or "").strip(), error=str(exc))

    per_port_timeout = cfg.scan_timeout if timeout is None else float(timeout)
    if per_port_timeout <= 0:
        return EnumResult(host=target, ip=ip, error="timeout must be > 0")
    workers = cfg.scan_concurrency if concurrency is None else int(concurrency)
    if workers < 1:
        return EnumResult(host=target, ip=ip, error="concurrency must be >= 1")
    workers = min(workers, len(port_list))

    probe = prober or _default_prober
    sem = asyncio.Semaphore(workers)
    started = time.perf_counter()

    async def _one(port: int) -> ServiceResult:
        async with sem:
            return await _probe_one(
                probe, ip, port, per_port_timeout, tls, cfg.max_banner_chars
            )

    results = list(await asyncio.gather(*[_one(p) for p in port_list]))
    results.sort(key=lambda r: r.port)
    services = [
        {
            "port": r.port,
            "service": r.service,
            "product": r.product,
            "tls": r.tls,
            "banner": r.banner,
        }
        for r in results
        if r.status == "open"
    ]
    duration_ms = round((time.perf_counter() - started) * 1000.0, 2)

    return EnumResult(
        host=target,
        ip=ip,
        ports=port_list,
        results=results,
        services=services,
        duration_ms=duration_ms,
        routable=routable if cfg.annotate_ips else None,
        block_reason=block_reason if cfg.annotate_ips else None,
        truncated=False,
        error=None,
    )


def enum_result_to_dict(result: EnumResult) -> dict:
    return {
        "host": result.host,
        "ip": result.ip,
        "ports": result.ports,
        "results": [
            {
                "port": r.port,
                "status": r.status,
                "service": r.service,
                "product": r.product,
                "banner": r.banner,
                "tls": r.tls,
                "latency_ms": r.latency_ms,
                "error": r.error,
            }
            for r in result.results
        ],
        "services": result.services,
        "service_count": len(result.services),
        "duration_ms": result.duration_ms,
        "routable": result.routable,
        "block_reason": result.block_reason,
        "truncated": result.truncated,
        "error": result.error,
    }


__all__ = [
    "PORT_HINTS",
    "EnumResult",
    "ServiceResult",
    "classify_banner",
    "enum_result_to_dict",
    "enum_services",
]

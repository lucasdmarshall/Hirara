"""SSRF perimeter — the shared egress guard for every Hirara tool.

The threat model: the URL is attacker-influenced. A tool picked it off a
search result page, out of a fetched document, out of an audio-URL argument,
or straight out of a prompt. Any of those can be authored by someone who
wants your egress.

Two rules make this safe, and both are load-bearing:

1. Resolve the hostname ourselves and reject if *any* returned address is
   non-global. Rejecting only the first address lets a resolver hand back one
   good IP and one bad one and gamble on which the client picks.
2. Connect to the exact IP we validated, carrying the original hostname in the
   ``Host`` header and in SNI. Validating a name and then letting the HTTP
   client resolve it again is a DNS-rebinding hole: the second lookup can
   return a different answer than the one we approved.

Callers must run every redirect hop back through :func:`resolve_target`.
:func:`hirara_core.download.safe_download` does this for you.
"""

from __future__ import annotations

import ipaddress
import socket
from .policy import private_targets_allowed
from dataclasses import dataclass
from urllib.parse import urlsplit

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address

ALLOWED_SCHEMES = frozenset({"http", "https"})
ALLOWED_PORTS = frozenset({80, 443, 8080, 8443})
_DEFAULT_PORT = {"http": 80, "https": 443}

# Ranges that are routable enough to slip past ``is_global`` on some Python
# versions, or that are simply never a legitimate fetch target.
_EXTRA_DENY = (
    ipaddress.ip_network("100.64.0.0/10"),  # CGNAT
    ipaddress.ip_network("198.18.0.0/15"),  # benchmarking
    ipaddress.ip_network("192.0.0.0/24"),   # IETF protocol assignments
    ipaddress.ip_network("64:ff9b::/96"),   # NAT64, can wrap a private v4
)


class BlockedURL(ValueError):
    """The URL failed the security perimeter. Never retried, never followed."""


@dataclass(frozen=True)
class Target:
    """A URL that has been cleared for one connection to one specific IP."""

    url: str
    scheme: str
    host: str
    port: int
    ip: str

    @property
    def host_header(self) -> str:
        default = _DEFAULT_PORT[self.scheme]
        return self.host if self.port == default else f"{self.host}:{self.port}"


def _unwrap(ip: IPAddress) -> IPAddress:
    """Collapse v6 tunnelling formats down to the v4 address they carry.

    ``::ffff:169.254.169.254`` must be judged as the link-local v4 address it
    really is, not as an unremarkable v6 address.
    """
    if isinstance(ip, ipaddress.IPv6Address):
        for candidate in (ip.ipv4_mapped, ip.sixtofour):
            if candidate is not None:
                return candidate
        if ip.teredo is not None:
            return ip.teredo[1]
    return ip


def check_ip(raw: str) -> str | None:
    """Return a rejection reason for ``raw``, or ``None`` if it is fetchable."""
    try:
        ip = _unwrap(ipaddress.ip_address(raw))
    except ValueError:
        return f"not an IP address: {raw!r}"

    if not ip.is_global:
        return f"{ip} is not globally routable"
    for net in _EXTRA_DENY:
        if ip.version == net.version and ip in net:
            return f"{ip} is in reserved range {net}"
    return None


def resolve_target(
    url: str,
    *,
    allow_private_ips: bool = False,
    resolver=socket.getaddrinfo,
) -> Target:
    """Validate ``url`` and pin it to a single vetted IP.

    Raises :class:`BlockedURL` on anything we are not willing to connect to.
    """
    parts = urlsplit(url)

    if parts.scheme not in ALLOWED_SCHEMES:
        raise BlockedURL(f"scheme {parts.scheme!r} is not allowed")
    if not parts.hostname:
        raise BlockedURL(f"no host in URL: {url!r}")
    if parts.username or parts.password:
        # user:pass@host is almost always an attempt to make the real host
        # hard to read, and we have no use for it.
        raise BlockedURL("credentials in URL are not allowed")

    host = parts.hostname
    try:
        port = parts.port or _DEFAULT_PORT[parts.scheme]
    except ValueError as exc:
        raise BlockedURL(f"invalid port in URL: {url!r}") from exc
    if port not in ALLOWED_PORTS:
        raise BlockedURL(f"port {port} is not allowed")

    try:
        infos = resolver(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise BlockedURL(f"cannot resolve {host!r}: {exc}") from exc
    if not infos:
        raise BlockedURL(f"{host!r} resolved to no addresses")

    addresses = [info[4][0] for info in infos]
    if not private_targets_allowed(allow_private_ips):
        for address in addresses:
            reason = check_ip(address)
            if reason is not None:
                raise BlockedURL(f"{host} -> {reason}")

    return Target(url=url, scheme=parts.scheme, host=host, port=port, ip=addresses[0])

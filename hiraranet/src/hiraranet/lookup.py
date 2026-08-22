"""DNS lookup — pure resolution, no connect.

Uses dnspython. Answer values that look like IP addresses are annotated with
``hirara_core.check_ip`` so an agent can tell public vs private/reserved
without having to re-implement the hub's IP deny list.
"""

from __future__ import annotations

import ipaddress
import logging
from dataclasses import dataclass, field
from typing import Callable

import dns.exception
import dns.resolver
import dns.reversename

from hirara_core import check_ip

from .config import ALLOWED_RECORD_TYPES, NetConfig

log = logging.getLogger(__name__)

# Injected in tests. Signature matches what we call below.
ResolverFactory = Callable[..., dns.resolver.Resolver]


class LookupError(ValueError):
    """Caller-facing lookup failure (bad input or DNS error)."""


@dataclass(frozen=True)
class Answer:
    """One DNS resource-record answer, agent-ready."""

    type: str
    value: str
    ttl: int | None = None
    # For A/AAAA (and PTR targets that are IPs): None = public / fetchable;
    # otherwise the hirara-core rejection reason (private, CGNAT, …).
    block_reason: str | None = None
    routable: bool | None = None


@dataclass
class LookupResult:
    """Full result of one ``dns_lookup`` call."""

    name: str
    record_types: list[str]
    answers: list[Answer] = field(default_factory=list)
    truncated: bool = False
    nameserver: str | None = None
    error: str | None = None


def _normalize_name(name: str) -> str:
    cleaned = (name or "").strip().rstrip(".")
    if not cleaned:
        raise LookupError("name is required")
    if len(cleaned) > 253:
        raise LookupError("name exceeds 253 characters")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in cleaned):
        raise LookupError("name contains control characters")
    return cleaned


def _normalize_types(
    record_types: list[str] | None,
    *,
    default: tuple[str, ...],
    max_types: int,
) -> list[str]:
    raw = record_types if record_types is not None else list(default)
    if not raw:
        raise LookupError("record_types must not be empty")
    if len(raw) > max_types:
        raise LookupError(f"at most {max_types} record_types per call")

    seen: list[str] = []
    for item in raw:
        t = (item or "").strip().upper()
        if not t:
            raise LookupError("empty record type")
        if t not in ALLOWED_RECORD_TYPES:
            allowed = ", ".join(sorted(ALLOWED_RECORD_TYPES))
            raise LookupError(f"unsupported record type {t!r}; allowed: {allowed}")
        if t not in seen:
            seen.append(t)
    return seen


def _annotate_value(value: str, *, annotate: bool) -> tuple[bool | None, str | None]:
    if not annotate:
        return None, None
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return None, None
    reason = check_ip(value)
    return reason is None, reason


def _rr_values(rrset) -> list[str]:
    """Render each rdata as a stable string."""
    out: list[str] = []
    for rdata in rrset:
        # MX: preference + exchange; TXT: joined strings; else str(rdata).
        text = rdata.to_text()
        # dnspython quotes TXT; strip outer quotes for agent readability when
        # the whole rdata is one quoted string.
        if rrset.rdtype == dns.rdatatype.TXT and text.startswith('"') and text.endswith('"'):
            text = text[1:-1].replace('\\"', '"')
        out.append(text)
    return out


def _build_resolver(
    *,
    nameserver: str | None,
    timeout: float,
    factory: ResolverFactory | None = None,
) -> dns.resolver.Resolver:
    make = factory or dns.resolver.Resolver
    resolver = make(configure=True)
    resolver.lifetime = timeout
    resolver.timeout = timeout
    if nameserver:
        resolver.nameservers = [nameserver]
    return resolver


def lookup_dns(
    name: str,
    *,
    record_types: list[str] | None = None,
    nameserver: str | None = None,
    config: NetConfig | None = None,
    resolver_factory: ResolverFactory | None = None,
) -> LookupResult:
    """Resolve ``name`` for the requested record types.

    Never connects to the resolved addresses — DNS queries only.
    """
    cfg = config or NetConfig()
    try:
        host = _normalize_name(name)
        types = _normalize_types(
            record_types,
            default=cfg.default_record_types,
            max_types=cfg.max_types,
        )
    except LookupError as exc:
        return LookupResult(
            name=(name or "").strip(),
            record_types=[],
            error=str(exc),
            nameserver=nameserver or cfg.nameserver,
        )

    ns = nameserver or cfg.nameserver
    resolver = _build_resolver(
        nameserver=ns, timeout=cfg.timeout, factory=resolver_factory
    )

    # PTR: if the caller passed an IP, convert to the in-addr/ip6.arpa form.
    query_name = host
    if "PTR" in types:
        try:
            ipaddress.ip_address(host)
            query_name = str(dns.reversename.from_address(host)).rstrip(".")
        except ValueError:
            pass  # already an arpa name or hostname — query as-is

    answers: list[Answer] = []
    truncated = False
    errors: list[str] = []

    for rtype in types:
        qname = query_name if rtype == "PTR" else host
        try:
            response = resolver.resolve(qname, rtype)
        except dns.resolver.NXDOMAIN:
            errors.append(f"{rtype}: NXDOMAIN")
            continue
        except dns.resolver.NoAnswer:
            # Name exists but this type has no records — not an error.
            continue
        except dns.resolver.NoNameservers as exc:
            errors.append(f"{rtype}: no nameservers ({exc})")
            continue
        except dns.exception.Timeout:
            errors.append(f"{rtype}: timeout")
            continue
        except dns.exception.DNSException as exc:
            errors.append(f"{rtype}: {exc}")
            continue

        ttl = int(response.rrset.ttl) if response.rrset is not None else None
        for value in _rr_values(response.rrset):
            if len(answers) >= cfg.max_answers:
                truncated = True
                break
            routable, reason = _annotate_value(value, annotate=cfg.annotate_ips)
            # Also annotate the left-hand side when the query itself was an IP
            # (A/AAAA of a literal is uncommon; skip). For A/AAAA values only.
            if rtype not in {"A", "AAAA"} and routable is None:
                # Non-IP rdata (CNAME target etc.): try annotating if it parses.
                routable, reason = _annotate_value(value.split()[-1], annotate=cfg.annotate_ips)
            answers.append(
                Answer(
                    type=rtype,
                    value=value,
                    ttl=ttl,
                    routable=routable,
                    block_reason=reason,
                )
            )
        if truncated:
            break

    error = None
    if not answers and errors:
        error = "; ".join(errors)
    elif errors and answers:
        # Partial success — surface soft failures without failing the call.
        error = None

    return LookupResult(
        name=host,
        record_types=types,
        answers=answers,
        truncated=truncated,
        nameserver=ns,
        error=error,
    )


def result_to_dict(result: LookupResult) -> dict:
    return {
        "name": result.name,
        "record_types": result.record_types,
        "answers": [
            {
                "type": a.type,
                "value": a.value,
                "ttl": a.ttl,
                "routable": a.routable,
                "block_reason": a.block_reason,
            }
            for a in result.answers
        ],
        "answer_count": len(result.answers),
        "truncated": result.truncated,
        "nameserver": result.nameserver,
        "error": result.error,
    }


__all__ = [
    "Answer",
    "LookupError",
    "LookupResult",
    "lookup_dns",
    "result_to_dict",
]

"""Shared fake DNS resolver for unit tests (no network)."""

from __future__ import annotations

from types import SimpleNamespace

import dns.rdatatype


class FakeRdata:
    def __init__(self, text: str):
        self._text = text

    def to_text(self) -> str:
        return self._text


class FakeRRset:
    def __init__(self, rdtype: int, ttl: int, values: list[str]):
        self.rdtype = rdtype
        self.ttl = ttl
        self._values = values

    def __iter__(self):
        return iter(FakeRdata(v) for v in self._values)


class FakeAnswer:
    def __init__(self, rrset: FakeRRset):
        self.rrset = rrset


class FakeResolver:
    """Minimal stand-in for dns.resolver.Resolver."""

    responses: dict = {}

    def __init__(self, configure: bool = True):
        self.lifetime = 5.0
        self.timeout = 5.0
        self.nameservers: list[str] = []

    def resolve(self, qname, rdtype):
        import dns.resolver

        if isinstance(rdtype, str):
            rdtype_int = dns.rdatatype.from_text(rdtype)
        else:
            rdtype_int = int(rdtype)
        key = (str(qname).rstrip(".").lower(), rdtype_int)
        item = self.responses.get(key)
        if item is None:
            raise dns.resolver.NoAnswer(request=SimpleNamespace())
        if isinstance(item, Exception):
            raise item
        return item


def fake_resolver_factory(**_kwargs):
    return FakeResolver()

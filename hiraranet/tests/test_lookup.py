"""DNS lookup domain logic — fake resolver, no network."""

from __future__ import annotations

import dns.rdatatype
import dns.resolver

from hiraranet.config import NetConfig
from hiraranet.lookup import lookup_dns, result_to_dict

from conftest import FakeAnswer, FakeResolver, FakeRRset, fake_resolver_factory


def test_rejects_empty_name():
    r = lookup_dns("")
    assert r.error and "required" in r.error


def test_rejects_unknown_type():
    r = lookup_dns("example.com", record_types=["FOO"])
    assert r.error and "unsupported" in r.error


def test_rejects_too_many_types():
    types = ["A", "AAAA", "MX", "TXT", "NS", "SOA", "PTR", "SRV", "CAA"]
    r = lookup_dns("example.com", record_types=types, config=NetConfig(max_types=8))
    assert r.error and "at most 8" in r.error


def test_a_and_aaaa_happy_path():
    FakeResolver.responses = {
        ("example.com", dns.rdatatype.A): FakeAnswer(
            FakeRRset(dns.rdatatype.A, 300, ["93.184.216.34"])
        ),
        ("example.com", dns.rdatatype.AAAA): FakeAnswer(
            FakeRRset(dns.rdatatype.AAAA, 300, ["2606:2800:220:1:248:1893:25c8:1946"])
        ),
    }
    r = lookup_dns("example.com", resolver_factory=fake_resolver_factory)
    assert r.error is None
    assert r.record_types == ["A", "AAAA"]
    assert len(r.answers) == 2
    assert r.answers[0].type == "A"
    assert r.answers[0].value == "93.184.216.34"
    assert r.answers[0].routable is True
    assert r.answers[0].block_reason is None
    assert r.answers[1].type == "AAAA"
    assert r.answers[1].routable is True


def test_private_ip_is_annotated_not_dropped():
    FakeResolver.responses = {
        ("localhost.test", dns.rdatatype.A): FakeAnswer(
            FakeRRset(dns.rdatatype.A, 60, ["127.0.0.1"])
        ),
    }
    r = lookup_dns(
        "localhost.test",
        record_types=["A"],
        resolver_factory=fake_resolver_factory,
    )
    assert r.error is None
    assert len(r.answers) == 1
    assert r.answers[0].value == "127.0.0.1"
    assert r.answers[0].routable is False
    assert r.answers[0].block_reason and "not globally routable" in r.answers[0].block_reason


def test_nxdomain_surfaces_error():
    FakeResolver.responses = {
        ("missing.example", dns.rdatatype.A): dns.resolver.NXDOMAIN(),
        ("missing.example", dns.rdatatype.AAAA): dns.resolver.NXDOMAIN(),
    }
    r = lookup_dns("missing.example", resolver_factory=fake_resolver_factory)
    assert not r.answers
    assert r.error and "NXDOMAIN" in r.error


def test_mx_records():
    FakeResolver.responses = {
        ("example.com", dns.rdatatype.MX): FakeAnswer(
            FakeRRset(dns.rdatatype.MX, 600, ["10 mail.example.com."])
        ),
    }
    r = lookup_dns(
        "example.com",
        record_types=["MX"],
        resolver_factory=fake_resolver_factory,
    )
    assert r.error is None
    assert r.answers[0].type == "MX"
    assert "mail.example.com" in r.answers[0].value


def test_max_answers_truncates():
    values = [f"93.184.216.{i}" for i in range(1, 6)]
    FakeResolver.responses = {
        ("example.com", dns.rdatatype.A): FakeAnswer(
            FakeRRset(dns.rdatatype.A, 60, values)
        ),
    }
    r = lookup_dns(
        "example.com",
        record_types=["A"],
        config=NetConfig(max_answers=3),
        resolver_factory=fake_resolver_factory,
    )
    assert r.truncated is True
    assert len(r.answers) == 3


def test_result_to_dict_shape():
    FakeResolver.responses = {
        ("example.com", dns.rdatatype.A): FakeAnswer(
            FakeRRset(dns.rdatatype.A, 60, ["1.2.3.4"])
        ),
    }
    r = lookup_dns("example.com", record_types=["A"], resolver_factory=fake_resolver_factory)
    d = result_to_dict(r)
    assert set(d) >= {
        "name",
        "record_types",
        "answers",
        "answer_count",
        "truncated",
        "nameserver",
        "error",
    }
    assert d["answer_count"] == 1


def test_custom_nameserver_is_applied():
    seen: list[str] = []

    class TrackingResolver(FakeResolver):
        def __init__(self, configure: bool = True):
            super().__init__(configure=configure)
            self._ns: list[str] = []

        @property
        def nameservers(self):
            return self._ns

        @nameservers.setter
        def nameservers(self, value):
            self._ns = list(value)
            seen.extend(value)

    def factory(**_kwargs):
        return TrackingResolver()

    TrackingResolver.responses = {
        ("example.com", dns.rdatatype.A): FakeAnswer(
            FakeRRset(dns.rdatatype.A, 60, ["1.2.3.4"])
        ),
    }

    r = lookup_dns(
        "example.com",
        record_types=["A"],
        nameserver="9.9.9.9",
        resolver_factory=factory,
    )
    assert r.nameserver == "9.9.9.9"
    assert "9.9.9.9" in seen

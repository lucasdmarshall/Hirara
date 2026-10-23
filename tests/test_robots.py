from __future__ import annotations

import httpx
import pytest

from hiraraweb.config import RobotsConfig
from hiraraweb.robots import RobotsCache, RobotsRules, robots_url_for

DISALLOW_ALL = "User-agent: *\nDisallow: /\n"
ALLOW_ALL = "User-agent: *\nDisallow:\n"
PARTIAL = "User-agent: *\nDisallow: /private/\nAllow: /private/public.html\n"
TARGETED = "User-agent: hirara-web\nDisallow: /no-bots/\n\nUser-agent: *\nDisallow:\n"


def cache_returning(status, text, *, config=None, calls=None):
    """A RobotsCache whose network layer is replaced by a fixed response."""
    robots = RobotsCache(config or RobotsConfig())

    async def fake_get(robots_url, cfg, allow_private_ips):
        if calls is not None:
            calls.append(robots_url)
        if isinstance(status, Exception):
            raise status
        return status, text

    import hiraraweb.robots as module

    module._get_robots_text = fake_get
    return robots


@pytest.fixture(autouse=True)
def restore_fetcher():
    import hiraraweb.robots as module

    original = module._get_robots_text
    yield
    module._get_robots_text = original


# --- URL derivation --------------------------------------------------------

@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://example.com/a/b?c=d", "https://example.com/robots.txt"),
        ("http://example.com:8080/x", "http://example.com:8080/robots.txt"),
        ("https://EXAMPLE.com/", "https://EXAMPLE.com/robots.txt"),
    ],
)
def test_robots_url_derivation(url, expected):
    assert robots_url_for(url) == expected


def test_robots_url_for_hostless_url():
    assert robots_url_for("not-a-url") is None


# --- rule evaluation -------------------------------------------------------

async def test_disallow_all_blocks():
    robots = cache_returning(200, DISALLOW_ALL)
    verdict = await robots.check("https://example.com/page")
    assert verdict.allowed is False
    assert "disallows" in verdict.reason


async def test_allow_all_permits():
    robots = cache_returning(200, ALLOW_ALL)
    assert (await robots.check("https://example.com/page")).allowed is True


async def test_partial_rules_are_path_specific():
    robots = cache_returning(200, PARTIAL)
    assert (await robots.check("https://example.com/open")).allowed is True
    assert (await robots.check("https://example.com/private/x")).allowed is False
    assert (await robots.check("https://example.com/private/public.html")).allowed is True


async def test_rules_targeting_our_token_are_honoured():
    """A site addressing `hirara-web` by name must win over the wildcard group."""
    robots = cache_returning(200, TARGETED)
    assert (await robots.check("https://example.com/no-bots/x")).allowed is False
    assert (await robots.check("https://example.com/elsewhere")).allowed is True


async def test_custom_user_agent_token_is_used():
    config = RobotsConfig(user_agent_token="octopilot")
    robots = cache_returning(200, "User-agent: octopilot\nDisallow: /x/\n", config=config)
    assert (await robots.check("https://example.com/x/y")).allowed is False
    assert (await robots.check("https://example.com/y")).allowed is True


# --- failure modes: all fail open ------------------------------------------

@pytest.mark.parametrize("status", [404, 410, 401, 403])
async def test_missing_or_forbidden_robots_allows(status):
    robots = cache_returning(status, "")
    verdict = await robots.check("https://example.com/page")
    assert verdict.allowed is True
    assert verdict.reason == "no usable robots.txt"


@pytest.mark.parametrize("status", [500, 502, 503])
async def test_server_error_allows_rather_than_locking_the_site_out(status):
    """RFC 9309 permits fail-closed here; a user-directed fetcher shouldn't."""
    robots = cache_returning(status, "")
    assert (await robots.check("https://example.com/page")).allowed is True


async def test_network_failure_allows():
    robots = cache_returning(httpx.ConnectError("refused"), "")
    assert (await robots.check("https://example.com/page")).allowed is True


async def test_blocked_robots_url_allows():
    """robots.txt on a guard-refused host must not wedge the fetch."""
    from hiraraweb.guard import BlockedURL

    robots = cache_returning(BlockedURL("nope"), "")
    assert (await robots.check("https://example.com/page")).allowed is True


async def test_disabled_config_skips_everything():
    calls: list[str] = []
    robots = cache_returning(200, DISALLOW_ALL, config=RobotsConfig(enabled=False), calls=calls)
    assert (await robots.check("https://example.com/page")).allowed is True
    assert calls == []


# --- caching ---------------------------------------------------------------

async def test_robots_is_fetched_once_per_host():
    calls: list[str] = []
    robots = cache_returning(200, PARTIAL, calls=calls)

    for path in ("/a", "/b", "/private/c"):
        await robots.check(f"https://example.com{path}")

    assert calls == ["https://example.com/robots.txt"]


async def test_different_hosts_are_cached_separately():
    calls: list[str] = []
    robots = cache_returning(200, ALLOW_ALL, calls=calls)
    await robots.check("https://a.example/x")
    await robots.check("https://b.example/x")
    assert len(calls) == 2


async def test_expired_entry_is_refetched():
    calls: list[str] = []
    robots = cache_returning(200, ALLOW_ALL, config=RobotsConfig(ttl=0), calls=calls)
    await robots.check("https://example.com/x")
    await robots.check("https://example.com/y")
    assert len(calls) == 2


# --- RFC 9309 matching ------------------------------------------------------


@pytest.mark.parametrize(
    "path,allowed",
    [
        ("/private/public.html", True),   # longer Allow beats shorter Disallow
        ("/private/other.html", False),
        ("/page", True),                  # equal length: Allow wins
        ("/files/a.pdf", False),          # * wildcard
        ("/files/a.pdf?x=1", True),       # $ anchors the end
        ("/search?q=x", False),           # query string is part of the path
        ("/robots.txt", True),            # always fetchable
    ],
)
def test_longest_match_wildcards_and_ties(path, allowed):
    rules = RobotsRules(
        "User-agent: *\n"
        "Disallow: /private/\n"
        "Allow: /private/public.html\n"
        "Disallow: /page\n"
        "Allow: /page\n"
        "Disallow: /*.pdf$\n"
        "Disallow: /search?q=\n"
        "Disallow: /robots\n"
    )
    assert rules.can_fetch("hirara-web", f"https://example.com{path}") is allowed


def test_groups_for_the_same_agent_are_merged_and_versions_ignored():
    rules = RobotsRules(
        "User-agent: Hirara-Web/1.0\nDisallow: /a/\n\n"
        "User-agent: *\nDisallow: /\n\n"
        "User-agent: hirara-web\nDisallow: /b/\n"
    )
    assert rules.can_fetch("hirara-web", "https://example.com/a/x") is False
    assert rules.can_fetch("hirara-web", "https://example.com/b/x") is False
    # The named group wins outright: the wildcard's "Disallow: /" does not apply.
    assert rules.can_fetch("hirara-web", "https://example.com/c") is True
    assert rules.can_fetch("other-bot", "https://example.com/c") is False


def test_percent_encoding_is_compared_decoded():
    rules = RobotsRules("User-agent: *\nDisallow: /caf%C3%A9/\n")
    assert rules.can_fetch("x", "https://example.com/café/menu") is False
    assert rules.can_fetch("x", "https://example.com/caf%c3%a9/menu") is False

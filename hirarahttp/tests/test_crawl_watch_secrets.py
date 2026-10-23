"""link_check, site_map, web_watch and scoped secrets — fake sites, no network."""

from __future__ import annotations

import functools
import json
import socket

import httpx
import pytest

from hirarahttp import crawl, pagewatch
from hirarahttp.config import HttpConfig
from hirarahttp.request import http_request as real_http_request
from hirarahttp.secrets import SecretError, load_secrets
from hirarahttp.tools import Toolset


def resolver(host, port, *args, **kwargs):
    # Names resolve to a public address; IP literals stay what they are.
    address = host if host.replace(".", "").isdigit() else "93.184.216.34"
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port))]


def html(body: str, title: str = "") -> tuple[int, str, str]:
    return 200, "text/html; charset=utf-8", f"<html><head><title>{title}</title></head><body>{body}</body></html>"


class Site:
    """Serves pages keyed by (host, path); records every request."""

    def __init__(self, pages: dict) -> None:
        self.pages = pages
        self.requests: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        key = (request.headers["host"], request.url.path)
        status, ctype, body = self.pages.get(key, (404, "text/plain", "missing"))
        if status in (301, 302):
            return httpx.Response(status, headers={"location": body})
        if request.method == "HEAD":
            body = ""
        return httpx.Response(status, headers={"content-type": ctype}, text=body)

    def patch(self, monkeypatch, *modules):
        fn = functools.partial(real_http_request, resolver=resolver,
                               transport=httpx.MockTransport(self.handler))
        for module in modules:
            monkeypatch.setattr(module, "http_request", fn)


SITE = {
    ("example.com", "/robots.txt"): (200, "text/plain", "User-agent: *\nDisallow: /private\n"),
    ("example.com", "/"): html('<a href="/about">About</a> <a href="/blog/">Blog</a> '
                               '<a href="/private/x">P</a> <img src="/logo.png"> '
                               '<a href="https://other.org/gone">Gone</a> '
                               '<a href="mailto:a@b.c">mail</a>', "Home"),
    ("example.com", "/about"): html('<a href="/">Home</a> <a href="/missing">Broken</a>', "About"),
    ("example.com", "/blog/"): html('<a href="post-1">Post</a>', "Blog"),
    ("example.com", "/blog/post-1"): html("hello", "Post 1"),
    ("example.com", "/logo.png"): (200, "image/png", "png"),
    ("other.org", "/gone"): (410, "text/plain", "gone"),
}


@pytest.fixture
def ts():
    return Toolset(HttpConfig())


async def test_site_map_crawls_same_host_and_honours_robots(ts, monkeypatch):
    site = Site(SITE)
    site.patch(monkeypatch, crawl)
    r = await ts.site_map(url="https://example.com/")
    assert r["error"] is None
    urls = [p["url"] for p in r["pages"]]
    assert urls == ["https://example.com/", "https://example.com/about",
                    "https://example.com/blog/", "https://example.com/blog/post-1",
                    "https://example.com/missing"]
    assert "https://example.com/private/x" in r["skipped_by_robots"]
    assert not any(req.headers["host"] == "other.org" for req in site.requests)
    assert r["by_status"] == {"200": 4, "404": 1}
    assert "Post 1" in r["text"]


async def test_site_map_limits(ts, monkeypatch):
    Site(SITE).patch(monkeypatch, crawl)
    r = await ts.site_map(url="https://example.com/", max_pages=2)
    assert r["count"] == 2 and r["truncated"] is True
    r = await ts.site_map(url="https://example.com/", max_depth=0)
    assert r["count"] == 1
    r = await ts.site_map(url="ftp://example.com/")
    assert "http(s)" in r["error"]


async def test_link_check_page_and_site(ts, monkeypatch):
    Site(SITE).patch(monkeypatch, crawl)
    r = await ts.link_check(url="https://example.com/")
    assert r["error"] is None
    broken = {b["url"]: b for b in r["broken"]}
    assert set(broken) == {"https://other.org/gone"}
    assert r["skipped_by_robots"] == ["https://example.com/private/x"]
    assert broken["https://other.org/gone"]["status"] == 410
    assert broken["https://other.org/gone"]["text"] == "Gone"
    r = await ts.link_check(url="https://example.com/", scope="site")
    assert "https://example.com/missing" in {b["url"] for b in r["broken"]}
    assert r["broken"][0]["found_on"]
    r = await ts.link_check(url="https://example.com/", check_external=False)
    assert r["broken"] == []


async def test_link_check_reports_blocked(monkeypatch):
    pages = {("example.com", "/"): html('<a href="http://127.0.0.1/admin">x</a>')}
    Site(pages).patch(monkeypatch, crawl)
    ts = Toolset(HttpConfig(allow_private_ips=False))
    r = await ts.link_check(url="https://example.com/", respect_robots=False)
    assert [b["url"] for b in r["blocked"]] == ["http://127.0.0.1/admin"]
    assert r["broken"] == []


async def test_web_watch_baseline_change_and_ignore(ts, monkeypatch, tmp_path):
    pages = {("example.com", "/price"): html("<h1>Plan</h1><p>Price: $10</p><p>Updated 10:01</p>")}
    site = Site(pages)
    site.patch(monkeypatch, pagewatch)
    ts = Toolset(HttpConfig(watch_db=str(tmp_path / "w.db")))
    r = await ts.web_watch(url="https://example.com/price", ignore=[r"Updated \d+:\d+"])
    assert r["first_check"] is True and r["changed"] is False
    pages[("example.com", "/price")] = html("<h1>Plan</h1><p>Price: $10</p><p>Updated 10:07</p>")
    r = await ts.web_watch(url="https://example.com/price")
    assert r["changed"] is False  # only the ignored timestamp moved
    pages[("example.com", "/price")] = html("<h1>Plan</h1><p>Price: $12</p><p>Updated 10:09</p>")
    r = await ts.web_watch(watch_id=r["watch_id"])
    assert r["changed"] is True and r["added_lines"] == 1 and r["removed_lines"] == 1
    assert "-Price: $10" in r["diff"] and "+Price: $12" in r["diff"]
    # Persisted: a new toolset on the same DB still remembers.
    again = Toolset(HttpConfig(watch_db=str(tmp_path / "w.db")))
    listed = await again.web_watch(action="list")
    assert listed["watches"][0]["changes"] == 1
    assert (await again.web_watch(action="remove", watch_id=r["watch_id"]))["removed"] is True


async def test_web_watch_keeps_baseline_on_error(ts, monkeypatch):
    pages = {("example.com", "/p"): html("<p>a</p>")}
    Site(pages).patch(monkeypatch, pagewatch)
    await ts.web_watch(url="https://example.com/p")
    pages[("example.com", "/p")] = (503, "text/plain", "down")
    r = await ts.web_watch(url="https://example.com/p")
    assert "baseline kept" in r["error"]
    pages[("example.com", "/p")] = html("<p>a</p>")
    assert (await ts.web_watch(url="https://example.com/p"))["changed"] is False
    r = await ts.web_watch(url="https://example.com/p", ignore=["("])
    assert "invalid ignore regex" in r["error"]


# --- secrets -------------------------------------------------------------------

SECRETS = json.dumps({
    "api": {"hosts": ["api.example.com"], "header": "Authorization", "prefix": "Bearer ",
            "value": "tok-123456"},
    "weather": {"hosts": ["*.weather.test"], "query": "appid", "value": "wkey-999"},
})


def test_secret_config_validation():
    with pytest.raises(SecretError, match="exactly one of header or query"):
        load_secrets('{"x": {"hosts": ["a.com"], "value": "v"}}', None)
    with pytest.raises(SecretError, match="bare"):
        load_secrets('{"x": {"hosts": ["*"], "header": "A", "value": "v"}}', None)
    specs = load_secrets(SECRETS, None)
    assert specs["weather"].allows("eu.weather.test") and not specs["weather"].allows("weather.test")


async def test_secret_header_only_to_allowed_host_and_redacted(monkeypatch):
    seen = []

    def handler(request):
        seen.append(request)
        # A careless API that echoes the credential back.
        return httpx.Response(200, text=f"you sent {request.headers.get('authorization')}")

    import hirarahttp.tools as tools_mod

    monkeypatch.setattr(tools_mod, "http_request", functools.partial(
        real_http_request, resolver=resolver, transport=httpx.MockTransport(handler)))
    ts = Toolset(HttpConfig(secrets_json=SECRETS))
    r = await ts.http_request(url="https://api.example.com/v1", secret="api",
                              headers={"authorization": "caller-value"})
    assert r["error"] is None
    assert seen[0].headers["authorization"] == "Bearer tok-123456"
    assert "tok-123456" not in json.dumps(r)
    assert r["request_headers"]["Authorization"] == "[secret:api]"
    hist = await ts.http_history(include_body=True)
    assert "tok-123456" not in json.dumps(hist)

    r = await ts.http_request(url="https://evil.example.org/", secret="api")
    assert "may only be sent to api.example.com" in r["error"]
    assert len(seen) == 1
    r = await ts.http_request(url="https://api.example.com/", secret="nope")
    assert "unknown secret" in r["error"]


async def test_secret_dropped_on_cross_host_redirect(monkeypatch):
    seen = []

    def handler(request):
        seen.append(request)
        if request.headers["host"] == "api.example.com":
            return httpx.Response(302, headers={"location": "https://collector.test/x"})
        return httpx.Response(200, text="ok")

    import hirarahttp.tools as tools_mod

    monkeypatch.setattr(tools_mod, "http_request", functools.partial(
        real_http_request, resolver=resolver, transport=httpx.MockTransport(handler)))
    ts = Toolset(HttpConfig(secrets_json=SECRETS))
    r = await ts.http_request(url="https://api.example.com/", secret="api")
    assert r["status"] == 200
    assert "authorization" in seen[0].headers
    assert "authorization" not in seen[1].headers


async def test_secret_query_and_listing(monkeypatch):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, text=str(request.url))

    import hirarahttp.tools as tools_mod

    monkeypatch.setattr(tools_mod, "http_request", functools.partial(
        real_http_request, resolver=resolver, transport=httpx.MockTransport(handler)))
    ts = Toolset(HttpConfig(secrets_json=SECRETS))
    r = await ts.http_request(url="https://eu.weather.test/now?q=Yangon", secret="weather")
    assert seen[0].url.params["appid"] == "wkey-999"
    assert "wkey-999" not in json.dumps(r)
    listed = await ts.secret_list()
    assert {s["name"] for s in listed["secrets"]} == {"api", "weather"}
    assert "wkey-999" not in json.dumps(listed)
    broken = Toolset(HttpConfig(secrets_json="{bad"))
    assert "not valid JSON" in (await broken.secret_list())["error"]
    assert broken.health()["status"] == "ok"

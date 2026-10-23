"""site_map and link_check: a small, polite, same-site crawler.

Every fetch goes through ``http_request`` and so through the SSRF guard, hop
by hop. The crawler stays on the start URL's host, honours robots.txt by
default, caps pages, depth and concurrency, and never executes anything: it
reads links out of HTML and nothing more.
"""

from __future__ import annotations

import asyncio
import posixpath
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import urldefrag, urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

from .config import HttpConfig
from .request import http_request

ASSET_EXTS = frozenset({
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico", ".css", ".js", ".mjs",
    ".pdf", ".zip", ".gz", ".mp3", ".mp4", ".webm", ".woff", ".woff2", ".ttf", ".xml",
    ".json", ".txt", ".csv", ".avif", ".bmp", ".tar", ".dmg", ".exe",
})
SKIP_SCHEMES = ("mailto:", "tel:", "javascript:", "data:", "sms:", "about:", "blob:")
LINK_ATTRS = {"a": "href", "link": "href", "img": "src", "script": "src", "iframe": "src",
              "source": "src", "video": "src", "audio": "src", "area": "href"}


class CrawlError(ValueError):
    """Caller-facing crawl failure."""


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str, str]] = []  # (tag, url, text)
        self.base: str | None = None
        self.title_parts: list[str] = []
        self._in_title = False
        self._anchor: list | None = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "base" and a.get("href") and self.base is None:
            self.base = a["href"]
        if tag == "title":
            self._in_title = True
        attr = LINK_ATTRS.get(tag)
        if attr and a.get(attr):
            if tag == "link" and "stylesheet" not in (a.get("rel") or "") and \
                    "icon" not in (a.get("rel") or ""):
                return
            entry = [tag, a[attr].strip(), ""]
            self.links.append(entry)  # type: ignore[arg-type]
            if tag == "a":
                self._anchor = entry

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        if tag == "a":
            self._anchor = None

    def handle_data(self, data):
        if self._in_title:
            self.title_parts.append(data)
        if self._anchor is not None and len(self._anchor[2]) < 120:
            self._anchor[2] = (self._anchor[2] + " " + data.strip()).strip()[:120]


def normalise(url: str, *, keep_query: bool = True) -> str:
    url, _ = urldefrag(url)
    parts = urlsplit(url)
    path = parts.path or "/"
    if path != "/" and "//" in path:
        path = posixpath.normpath(path) + ("/" if path.endswith("/") else "")
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path,
                       parts.query if keep_query else "", ""))


def _is_asset(url: str) -> bool:
    return posixpath.splitext(urlsplit(url).path.lower())[1] in ASSET_EXTS


@dataclass
class Page:
    url: str
    depth: int
    status: int | None = None
    content_type: str | None = None
    title: str | None = None
    bytes: int | None = None
    elapsed_ms: int | None = None
    final_url: str | None = None
    error: str | None = None
    links: list[tuple[str, str, str]] = field(default_factory=list)  # (tag, absolute url, text)

    def as_dict(self) -> dict:
        return {
            "url": self.url,
            "depth": self.depth,
            "status": self.status,
            "content_type": self.content_type,
            "title": self.title,
            "bytes": self.bytes,
            "elapsed_ms": self.elapsed_ms,
            "final_url": self.final_url if self.final_url != self.url else None,
            "links_out": len(self.links),
            "error": self.error,
        }


async def _robots(start: str, config: HttpConfig, agent: str) -> RobotFileParser | None:
    parts = urlsplit(start)
    result = await http_request(urlunsplit((parts.scheme, parts.netloc, "/robots.txt", "", "")),
                                config=config, max_bytes=512_000)
    if result.status is None or not 200 <= result.status < 300 or not result.body:
        return None
    parser = RobotFileParser()
    parser.parse(result.body.splitlines())
    return parser


async def crawl(start: str, *, config: HttpConfig, max_pages: int = 50, max_depth: int = 3,
                respect_robots: bool = True, keep_query: bool = False,
                concurrency: int = 4) -> tuple[list[Page], dict]:
    start = (start or "").strip()
    parts = urlsplit(start)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise CrawlError("url must be an absolute http(s) URL")
    max_pages = max(1, min(int(max_pages), 1000))
    max_depth = max(0, min(int(max_depth), 10))
    host = parts.netloc.lower()
    agent = "hirara"
    robots = await _robots(start, config, agent) if respect_robots else None

    root = normalise(start, keep_query=True)
    seen = {root}
    queue: list[tuple[str, int]] = [(root, 0)]
    pages: list[Page] = []
    blocked_by_robots: list[str] = []
    sem = asyncio.Semaphore(max(1, min(int(concurrency), 16)))

    async def fetch(url: str, depth: int) -> Page:
        page = Page(url=url, depth=depth)
        async with sem:
            result = await http_request(url, config=config)
        page.status, page.error = result.status, result.error
        page.elapsed_ms, page.final_url = result.elapsed_ms, result.final_url
        page.bytes = result.bytes_downloaded
        ctype = (result.response_headers or {}).get("content-type", "")
        page.content_type = ctype.split(";")[0].strip() or None
        if result.body and "html" in ctype.lower() and result.body_encoding != "base64":
            parser = _LinkParser()
            try:
                parser.feed(result.body)
            except Exception:  # noqa: BLE001 — malformed HTML yields what it yields
                pass
            page.title = " ".join("".join(parser.title_parts).split())[:200] or None
            base = urljoin(result.final_url or url, parser.base) if parser.base else (result.final_url or url)
            for tag, href, text in parser.links:
                if href.lower().startswith(SKIP_SCHEMES) or href.startswith("#"):
                    continue
                absolute = urljoin(base, href)
                if urlsplit(absolute).scheme not in ("http", "https"):
                    continue
                page.links.append((tag, normalise(absolute, keep_query=True), text))
        return page

    while queue and len(pages) < max_pages:
        batch = queue[: max_pages - len(pages)]
        queue = queue[len(batch):]
        results = await asyncio.gather(*(fetch(u, d) for u, d in batch))
        for page in results:
            pages.append(page)
            if page.depth >= max_depth:
                continue
            for tag, link, _ in page.links:
                if tag != "a":
                    continue
                if urlsplit(link).netloc.lower() != host or _is_asset(link):
                    continue
                key = normalise(link, keep_query=keep_query)
                if key in seen:
                    continue
                seen.add(key)
                if robots is not None and not robots.can_fetch(agent, key):
                    blocked_by_robots.append(key)
                    continue
                queue.append((key, page.depth + 1))
    meta = {
        "robots": robots,
        "robots_txt": robots is not None,
        "skipped_by_robots": blocked_by_robots[:200],
        "unvisited": len(queue),
        "truncated": bool(queue),
    }
    return pages, meta


async def site_map(url: str, *, config: HttpConfig, max_pages: int = 50, max_depth: int = 3,
                   respect_robots: bool = True, keep_query: bool = False) -> dict:
    pages, meta = await crawl(url, config=config, max_pages=max_pages, max_depth=max_depth,
                              respect_robots=respect_robots, keep_query=keep_query)
    meta.pop("robots")
    by_status: dict[str, int] = {}
    for p in pages:
        key = str(p.status) if p.status is not None else "error"
        by_status[key] = by_status.get(key, 0) + 1
    lines = [f"{len(pages)} page(s) from {url}" + (" (more not visited)" if meta["truncated"] else "")]
    for p in sorted(pages, key=lambda x: (x.depth, x.url))[:200]:
        status = p.status if p.status is not None else "ERR"
        lines.append(f"{'  ' * p.depth}{status} {urlsplit(p.url).path or '/'}"
                     + (f" — {p.title}" if p.title else ""))
    return {
        "url": url,
        "pages": [p.as_dict() for p in sorted(pages, key=lambda x: (x.depth, x.url))],
        "count": len(pages),
        "by_status": by_status,
        **meta,
        "text": "\n".join(lines),
        "error": None,
    }


async def link_check(url: str, *, config: HttpConfig, scope: str = "page", max_pages: int = 20,
                     max_links: int = 500, check_external: bool = True,
                     respect_robots: bool = True, concurrency: int = 8) -> dict:
    if scope not in ("page", "site"):
        raise CrawlError("scope must be page or site")
    pages, meta = await crawl(url, config=config, max_pages=1 if scope == "page" else max_pages,
                              max_depth=0 if scope == "page" else 5,
                              respect_robots=respect_robots, keep_query=False)
    if pages and pages[0].status is None:
        raise CrawlError(f"could not fetch {url}: {pages[0].error}")

    robots = meta.pop("robots")
    known = {p.url: p for p in pages}
    host = urlsplit(url).netloc.lower()
    found_on: dict[str, list[str]] = {}
    texts: dict[str, str] = {}
    skipped: set[str] = set()
    for p in pages:
        for _tag, link, text in p.links:
            internal = urlsplit(link).netloc.lower() == host
            if not check_external and not internal:
                continue
            if internal and robots is not None and not robots.can_fetch("hirara", link):
                skipped.add(link)
                continue
            found_on.setdefault(link, [])
            if p.url not in found_on[link]:
                found_on[link].append(p.url)
            if text and link not in texts:
                texts[link] = text
    links = list(found_on)[: max(1, min(int(max_links), 5000))]
    sem = asyncio.Semaphore(max(1, min(int(concurrency), 32)))

    async def check(link: str) -> dict:
        page = known.get(link)
        if page is not None:
            return {"url": link, "status": page.status, "final_url": page.final_url,
                    "error": page.error}
        async with sem:
            r = await http_request(link, method="HEAD", config=config)
            if r.status in (403, 405, 501) or (r.status is None and not (r.error or "").startswith("blocked")):
                r = await http_request(link, config=config, max_bytes=1024)
        return {"url": link, "status": r.status, "final_url": r.final_url, "error": r.error}

    results = await asyncio.gather(*(check(link) for link in links))
    broken, redirected, blocked, ok = [], [], [], 0
    for res in results:
        item = {**res, "found_on": found_on[res["url"]][:5], "text": texts.get(res["url"])}
        err = res.get("error") or ""
        if err.startswith("blocked"):
            blocked.append(item)
        elif res["status"] is None or res["status"] >= 400:
            broken.append(item)
        else:
            ok += 1
            if res.get("final_url") and normalise(res["final_url"]) != res["url"]:
                redirected.append(item)
    lines = [f"checked {len(results)} link(s) on {len(pages)} page(s): {len(broken)} broken, "
             f"{len(redirected)} redirected, {len(blocked)} blocked by policy"]
    for b in broken[:30]:
        lines.append(f"BROKEN {b['status'] or b['error']} {b['url']} (on {b['found_on'][0]})")
    return {
        "url": url,
        "scope": scope,
        "pages_checked": len(pages),
        "links_checked": len(results),
        "links_found": len(found_on),
        "ok": ok,
        "broken": broken,
        "redirected": redirected[:200],
        "blocked": blocked[:200],
        "skipped_by_robots": sorted(skipped)[:200],
        "truncated": len(found_on) > len(links) or meta["truncated"],
        "text": "\n".join(lines),
        "error": None,
    }


__all__ = ["CrawlError", "crawl", "link_check", "normalise", "site_map"]

"""robots.txt support.

Three things this does *not* do, all deliberate:

It does not use :func:`urllib.robotparser.RobotFileParser.read`. That method
fetches the URL itself with ``urllib.request.urlopen`` — bypassing the SSRF
perimeter entirely. A hostile redirect on a robots.txt fetch would reach
straight into your network. We fetch the file ourselves through
:mod:`hiraraweb.guard` and hand the parser only the text.

It does not use :class:`urllib.robotparser.RobotFileParser` at all. That parser
applies rules in file order, so ``Disallow: /private/`` followed by
``Allow: /private/public.html`` blocks the page RFC 9309 says is allowed, and
it has no ``*`` or ``$`` support. :class:`RobotsRules` implements the RFC's
longest-match rule instead.

It does not fail closed. RFC 9309 permits treating a 5xx as "disallow
everything", which is right for a bulk crawler hammering a site unattended.
This tool fetches one page because something asked it to, so a flaky robots.txt
returning 503 should not silently make a site unreadable. Unreachable robots
means allowed, and the reason is reported so the caller can see it happened.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from urllib.parse import unquote, urlsplit, urlunsplit

import httpx

from .config import RobotsConfig
from .guard import BlockedURL, resolve_target

# RFC 9309 says parsers must handle at least 500 KiB.
_MAX_ROBOTS_BYTES = 512_000
_MAX_ROBOTS_REDIRECTS = 3


@dataclass(slots=True)
class RobotsVerdict:
    allowed: bool
    reason: str | None = None


@dataclass(slots=True)
class _Rule:
    allow: bool
    length: int
    pattern: re.Pattern[str]


def _compile(path: str) -> re.Pattern[str]:
    """``*`` matches any run of characters; a trailing ``$`` anchors the end."""
    anchored = path.endswith("$")
    if anchored:
        path = path[:-1]
    body = ".*".join(re.escape(part) for part in unquote(path).split("*"))
    return re.compile(body + ("$" if anchored else ""), re.DOTALL)


class RobotsRules:
    """Parsed robots.txt, evaluated per RFC 9309.

    The group naming our product token wins over ``*``; groups for the same
    agent are merged. Among the rules that match a path the longest one
    decides, and on a tie Allow wins.
    """

    def __init__(self, text: str) -> None:
        # lowercased agent -> rules from every group naming it
        self._groups: dict[str, list[_Rule]] = {}
        agents: list[str] = []
        in_rules = False

        for raw in text.splitlines():
            line = raw.split("#", 1)[0].strip()
            key, sep, value = line.partition(":")
            if not sep:
                continue
            key = key.strip().lower()
            value = value.strip()

            if key == "user-agent":
                if in_rules:
                    agents, in_rules = [], False
                # Only the product token counts: "Foo/1.0" addresses "foo".
                agent = value.split("/", 1)[0].strip().lower()
                agents.append(agent)
                self._groups.setdefault(agent, [])
            elif key in ("allow", "disallow"):
                in_rules = True
                # An empty path matches nothing (``Disallow:`` means allow all).
                if not agents or not value:
                    continue
                rule = _Rule(key == "allow", len(value), _compile(value))
                for agent in agents:
                    self._groups[agent].append(rule)

    def can_fetch(self, token: str, url: str) -> bool:
        parts = urlsplit(url)
        path = parts.path or "/"
        if path == "/robots.txt":
            return True
        if parts.query:
            path = f"{path}?{parts.query}"
        path = unquote(path)

        rules = self._groups.get(token.lower())
        if rules is None:
            rules = self._groups.get("*", [])

        best: _Rule | None = None
        for rule in rules:
            if not rule.pattern.match(path):
                continue
            if (
                best is None
                or rule.length > best.length
                or (rule.length == best.length and rule.allow)
            ):
                best = rule
        return best is None or best.allow


def robots_url_for(url: str) -> str | None:
    """The robots.txt that governs ``url``, or ``None`` if it has no host."""
    parts = urlsplit(url)
    if not parts.scheme or not parts.netloc:
        return None
    return urlunsplit((parts.scheme, parts.netloc, "/robots.txt", "", ""))


async def _get_robots_text(robots_url: str, config: RobotsConfig, allow_private_ips: bool):
    """Fetch robots.txt through the guard. Returns ``(status, text)``.

    ``status`` is ``None`` when the file could not be retrieved at all.
    """
    current = robots_url
    timeout = httpx.Timeout(connect=config.timeout, read=config.timeout,
                            write=config.timeout, pool=config.timeout)

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
        for _ in range(_MAX_ROBOTS_REDIRECTS + 1):
            # Every hop re-validated and re-pinned, exactly as in web_fetch.
            target = resolve_target(current, allow_private_ips=allow_private_ips)
            response = await client.get(
                httpx.URL(current).copy_with(host=target.ip),
                headers={
                    "Host": target.host_header,
                    "User-Agent": config.user_agent,
                    "Accept": "text/plain, */*;q=0.5",
                },
                extensions={"sni_hostname": target.host},
            )

            if response.is_redirect:
                location = response.headers.get("location")
                if not location:
                    return response.status_code, ""
                current = str(httpx.URL(current).join(location))
                continue

            body = response.content[:_MAX_ROBOTS_BYTES]
            return response.status_code, body.decode("utf-8", errors="replace")

    return None, ""


class RobotsCache:
    """Per-host robots.txt rules, cached so one file is fetched once per host."""

    def __init__(self, config: RobotsConfig | None = None) -> None:
        self.config = config or RobotsConfig.from_env()
        # host key -> (expires_at, parser or None)
        self._entries: dict[str, tuple[float, RobotsRules | None]] = {}

    def _key(self, robots_url: str) -> str:
        parts = urlsplit(robots_url)
        return f"{parts.scheme}://{parts.netloc.lower()}"

    def clear(self) -> None:
        self._entries.clear()

    async def _parser_for(self, robots_url: str, allow_private_ips: bool):
        key = self._key(robots_url)
        now = time.monotonic()

        entry = self._entries.get(key)
        if entry is not None and entry[0] > now:
            return entry[1]

        parser: RobotsRules | None = None
        try:
            status, text = await _get_robots_text(robots_url, self.config, allow_private_ips)
        except (httpx.HTTPError, BlockedURL):
            status, text = None, ""

        # 2xx: parse it. Anything else (missing, forbidden, server error,
        # unreachable) means "no rules we can honour" — see module docstring.
        if status is not None and 200 <= status < 300:
            parser = RobotsRules(text)

        self._entries[key] = (now + self.config.ttl, parser)
        return parser

    async def check(self, url: str, *, allow_private_ips: bool = False) -> RobotsVerdict:
        if not self.config.enabled:
            return RobotsVerdict(True)

        robots_url = robots_url_for(url)
        if robots_url is None:
            return RobotsVerdict(True)

        try:
            parser = await self._parser_for(robots_url, allow_private_ips)
        except Exception:
            # Never let a robots problem break a fetch.
            return RobotsVerdict(True, "robots.txt could not be evaluated")

        if parser is None:
            return RobotsVerdict(True, "no usable robots.txt")

        if parser.can_fetch(self.config.user_agent_token, url):
            return RobotsVerdict(True)

        return RobotsVerdict(
            False,
            f"robots.txt at {robots_url} disallows {self.config.user_agent_token}",
        )

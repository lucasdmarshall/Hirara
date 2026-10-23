"""Named, host-scoped credentials for http_request.

An agent that needs to call an authenticated API should not be handed the
key: it can leak it into a prompt, a log or a request to the wrong host. The
operator lists secrets in CHTTP_SECRETS (JSON) or CHTTP_SECRETS_FILE; the
agent only names one (``secret="github"``). The value is attached as a header
or query parameter only when the pinned destination host is on that secret's
allowlist, is dropped on a redirect to any other host, and is redacted from
everything returned or recorded.

    {"github": {"hosts": ["api.github.com"], "header": "Authorization",
                "prefix": "Bearer ", "value_env": "GITHUB_TOKEN"},
     "weather": {"hosts": ["*.openweathermap.org"], "query": "appid",
                 "value": "..."}}
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


class SecretError(ValueError):
    """Bad secret configuration or a secret used where it may not go."""


@dataclass(frozen=True)
class SecretSpec:
    name: str
    hosts: tuple[str, ...]
    header: str | None
    query: str | None
    value: str | None
    description: str | None = None

    def allows(self, host: str) -> bool:
        host = (host or "").lower().rstrip(".")
        for pattern in self.hosts:
            p = pattern.lower().rstrip(".")
            if p.startswith("*."):
                if host.endswith(p[1:]) and host != p[2:]:
                    return True
            elif host == p:
                return True
        return False

    def placeholder(self) -> str:
        return f"[secret:{self.name}]"

    def public(self) -> dict:
        return {
            "name": self.name,
            "hosts": list(self.hosts),
            "sent_as": f"header {self.header}" if self.header else f"query parameter {self.query}",
            "available": bool(self.value),
            "description": self.description,
        }


def _parse(raw: dict) -> dict[str, SecretSpec]:
    if not isinstance(raw, dict):
        raise SecretError("secrets config must be a JSON object of name -> spec")
    out: dict[str, SecretSpec] = {}
    for name, spec in raw.items():
        if not isinstance(spec, dict):
            raise SecretError(f"secret {name!r}: spec must be an object")
        hosts = spec.get("hosts")
        if isinstance(hosts, str):
            hosts = [hosts]
        if not hosts or not all(isinstance(h, str) and h.strip() for h in hosts):
            raise SecretError(f"secret {name!r}: hosts must list at least one host")
        if any(h.strip() in ("*", "*.") for h in hosts):
            raise SecretError(f"secret {name!r}: a bare * host would send it anywhere")
        header, query = spec.get("header"), spec.get("query")
        if bool(header) == bool(query):
            raise SecretError(f"secret {name!r}: set exactly one of header or query")
        value = spec.get("value")
        if value is None and spec.get("value_env"):
            value = os.getenv(str(spec["value_env"]))
        if value is not None:
            value = f"{spec.get('prefix', '')}{value}"
        out[str(name)] = SecretSpec(
            name=str(name),
            hosts=tuple(h.strip() for h in hosts),
            header=str(header) if header else None,
            query=str(query) if query else None,
            value=value,
            description=spec.get("description"),
        )
    return out


def load_secrets(inline: str | None, path: str | None) -> dict[str, SecretSpec]:
    secrets: dict[str, SecretSpec] = {}
    if path:
        try:
            raw = json.loads(Path(path).expanduser().read_text())
        except OSError as exc:
            raise SecretError(f"cannot read CHTTP_SECRETS_FILE: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise SecretError(f"CHTTP_SECRETS_FILE is not valid JSON: {exc.msg}") from exc
        secrets.update(_parse(raw))
    if inline:
        try:
            raw = json.loads(inline)
        except json.JSONDecodeError as exc:
            raise SecretError(f"CHTTP_SECRETS is not valid JSON: {exc.msg}") from exc
        secrets.update(_parse(raw))
    return secrets


def redact(obj, specs: list[SecretSpec]):
    """Replace every secret value inside strings of a JSON-like object."""
    pairs = [(s.value, s.placeholder()) for s in specs if s.value]
    # Also catch the bare token when a prefix such as "Bearer " was added.
    for s in specs:
        if s.value and " " in s.value:
            token = s.value.split(" ", 1)[1]
            if len(token) >= 6:
                pairs.append((token, s.placeholder()))
    if not pairs:
        return obj

    def walk(value):
        if isinstance(value, str):
            for secret, mark in pairs:
                if secret in value:
                    value = value.replace(secret, mark)
            return value
        if isinstance(value, dict):
            return {k: walk(v) for k, v in value.items()}
        if isinstance(value, list):
            return [walk(v) for v in value]
        return value

    return walk(obj)


__all__ = ["SecretError", "SecretSpec", "load_secrets", "redact"]

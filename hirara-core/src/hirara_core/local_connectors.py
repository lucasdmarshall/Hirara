"""Discover the Rust local runtime; verify its identity before sending secrets/data."""
from dataclasses import dataclass, field
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import stat as statlib
import sys
from urllib.parse import urlsplit

import httpx


@dataclass(frozen=True)
class LocalConnector:
    url: str
    token: str = field(repr=False)


def data_dir() -> Path:
    override = os.getenv("HIRARA_CONNECTOR_LOCAL_DIR")
    if override:
        return Path(override)
    if sys.platform == "win32":
        return Path(os.environ["LOCALAPPDATA"]) / "Hirara/connectors"
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/Hirara/connectors"
    return Path(os.getenv("XDG_DATA_HOME", str(Path.home() / ".local/share"))) / "hirara/connectors"


def discover() -> LocalConnector | None:
    try:
        directory = data_dir()
        path = directory / "local.json"
        if path.is_symlink() or directory.is_symlink():
            return None
        stat = path.stat()
        if not statlib.S_ISREG(stat.st_mode) or stat.st_size > 16384:
            return None
        if os.name != "nt" and (stat.st_uid != os.getuid() or stat.st_mode & 0o077
                                or directory.stat().st_mode & 0o077):
            return None
        value = json.loads(path.read_text())
        if not isinstance(value, dict) or not isinstance(value.get("url"), str):
            return None
        url, token = value["url"], value["token"]
        parsed = urlsplit(url)
        if (value.get("version") != 1 or parsed.scheme != "http" or parsed.hostname != "127.0.0.1"
                or parsed.port is None or parsed.path or parsed.query or parsed.fragment
                or parsed.username or parsed.password):
            return None
        if not isinstance(token, str) or len(token) != 48 or any(c not in "0123456789abcdef" for c in token):
            return None
        return LocalConnector(url, token)
    except (OSError, ValueError, KeyError, TypeError):
        return None


async def verify(client: httpx.AsyncClient, local: LocalConnector, timeout: float) -> None:
    challenge = secrets.token_hex(24)
    async with client.stream("POST", local.url + "/local/proof", json={"challenge": challenge},
                             headers={"Authorization": ""}, timeout=timeout) as response:
        response.raise_for_status()
        if response.headers.get("content-encoding", "identity").lower() != "identity":
            raise httpx.TransportError("compressed local identity responses are not accepted")
        body = bytearray()
        async for chunk in response.aiter_bytes():
            body.extend(chunk)
            if len(body) > 16384:
                raise httpx.TransportError("local connector identity response exceeds limit")
    try:
        proof = json.loads(body)["proof"]
    except (ValueError, KeyError, TypeError):
        raise httpx.TransportError("invalid local connector identity response") from None
    expected = hmac.new(local.token.encode(),
                        f"Hirara local service v1:{local.url}:{challenge}".encode(), hashlib.sha256).hexdigest()
    if not isinstance(proof, str) or not hmac.compare_digest(proof, expected):
        raise httpx.TransportError("local connector identity verification failed")


def hub_proof(token: str, port: int, challenge: str) -> str:
    return hmac.new(token.encode(), f"Hirara local hub v1:http://127.0.0.1:{port}:{challenge}".encode(), hashlib.sha256).hexdigest()


def verify_hub(client: httpx.Client, local: LocalConnector, url: str) -> None:
    parsed = urlsplit(url)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
        raise httpx.TransportError("automatic connector authentication requires a local HTTP hub")
    challenge = secrets.token_hex(24)
    with client.stream("POST", "/connectors/local-proof", json={"challenge": challenge},
                       headers={"Authorization": ""}) as response:
        response.raise_for_status()
        if response.headers.get("content-encoding", "identity").lower() != "identity":
            raise httpx.TransportError("compressed local identity responses are not accepted")
        body = bytearray()
        for chunk in response.iter_bytes():
            body.extend(chunk)
            if len(body) > 16384:
                raise httpx.TransportError("local hub identity response exceeds limit")
    try:
        proof = json.loads(body)["proof"]
    except (ValueError, TypeError, KeyError):
        raise httpx.TransportError("invalid local hub identity response") from None
    if not isinstance(proof, str) or not hmac.compare_digest(proof, hub_proof(local.token, parsed.port or 80, challenge)):
        raise httpx.TransportError("local hub identity verification failed")

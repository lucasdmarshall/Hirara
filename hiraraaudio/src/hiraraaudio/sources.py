"""Resolve an audio source (path, URL, base64 or upload) to a local file.

Every tool takes its input the same way, so the safety rules live here once:
local paths can be switched off for network-exposed services, and URL fetches
go through hirara-core's SSRF guard with a hard byte cap.
"""

from __future__ import annotations

import base64
import binascii
import mimetypes
import os
import tempfile
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from hirara_core import BlockedURL, DownloadError, safe_download

from .config import AudioConfig
from .errors import AudioError


@dataclass(slots=True)
class Source:
    path: Path
    label: str
    is_temp: bool

    def cleanup(self) -> None:
        if self.is_temp:
            try:
                self.path.unlink()
            except OSError:
                pass


def _suffix(filename: str | None, content_type: str | None = None) -> str:
    if filename:
        suffix = Path(filename).suffix
        if suffix:
            return suffix.lower()
    if content_type:
        guessed = mimetypes.guess_extension(content_type.split(";")[0].strip())
        if guessed:
            return guessed
    return ".bin"


def write_temp(data: bytes, suffix: str = ".bin") -> Path:
    fd, name = tempfile.mkstemp(prefix="hiraraaudio-", suffix=suffix)
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)
    return Path(name)


async def resolve(
    config: AudioConfig,
    *,
    path: str | None = None,
    url: str | None = None,
    data_base64: str | None = None,
    data: bytes | None = None,
    filename: str | None = None,
    prefix: str = "audio",
) -> Source:
    """Turn exactly one of the given inputs into a readable local file."""
    given = [v for v in (path, url, data_base64, data) if v is not None and v != ""]
    names = f"{prefix}_path, {prefix}_url or {prefix}_base64"
    if not given:
        raise AudioError(f"provide exactly one of {names}")
    if len(given) > 1:
        raise AudioError(f"provide only one of {names}")

    if data is not None:
        _check_size(len(data), config)
        return Source(write_temp(data, _suffix(filename)), filename or "upload", True)

    if path:
        if not config.allow_local_path:
            raise AudioError(
                f"{prefix}_path is disabled on this server (HA_ALLOW_LOCAL_PATH=false). "
                f"Send {prefix}_base64 or an upload instead."
            )
        local = Path(path).expanduser()
        if not local.is_file():
            raise AudioError(f"file not found: {local}")
        _check_size(local.stat().st_size, config)
        return Source(local, str(local), False)

    if data_base64:
        try:
            raw = base64.b64decode(data_base64, validate=False)
        except (binascii.Error, ValueError) as exc:
            raise AudioError(f"invalid {prefix}_base64: {exc}") from exc
        if not raw:
            raise AudioError(f"{prefix}_base64 decoded to zero bytes")
        _check_size(len(raw), config)
        return Source(write_temp(raw, _suffix(filename)), filename or f"{prefix}_base64", True)

    assert url is not None
    if not config.allow_url_fetch:
        raise AudioError(
            f"{prefix}_url is disabled (HA_ALLOW_URL_FETCH=false). "
            f"Send {prefix}_path or {prefix}_base64 instead."
        )
    try:
        result = await safe_download(url, max_bytes=config.max_bytes, timeout=config.url_timeout)
    except BlockedURL as exc:
        raise AudioError(f"{prefix}_url blocked: {exc}") from exc
    except DownloadError as exc:
        raise AudioError(f"{prefix}_url download failed: {exc}") from exc
    if result.truncated:
        raise AudioError(f"{prefix}_url exceeds HA_MAX_BYTES ({config.max_bytes} bytes)")
    name = filename or os.path.basename(urlparse(url).path) or "remote-audio"
    return Source(write_temp(result.content, _suffix(name, result.content_type)), url, True)


def _check_size(size: int, config: AudioConfig) -> None:
    if size > config.max_bytes:
        raise AudioError(f"input exceeds HA_MAX_BYTES ({config.max_bytes} bytes)")


@asynccontextmanager
async def opened(config: AudioConfig, **kwargs):
    """``async with opened(cfg, path=...) as src:`` — temp files are removed after."""
    source = await resolve(config, **kwargs)
    try:
        yield source
    finally:
        source.cleanup()


__all__ = ["Source", "opened", "resolve", "write_temp"]

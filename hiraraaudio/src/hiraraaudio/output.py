"""Deliver a produced file: write it where the caller asked, or inline it."""

from __future__ import annotations

import base64
import shutil
from pathlib import Path

from .config import AudioConfig
from .errors import AudioError


def check_output_path(output_path: str | None, config: AudioConfig) -> Path | None:
    """Validate ``output_path`` up front, before any expensive work."""
    if not output_path:
        return None
    if not config.allow_output_path:
        raise AudioError(
            "output_path is disabled on this server (HA_ALLOW_OUTPUT_PATH=false); "
            "the result is returned as base64 instead"
        )
    target = Path(output_path).expanduser()
    if target.exists() and target.is_dir():
        raise AudioError(f"output_path is a directory: {target}")
    if not target.parent.is_dir():
        raise AudioError(f"output directory does not exist: {target.parent}")
    return target


def check_output_dir(output_dir: str | None, config: AudioConfig) -> Path | None:
    if not output_dir:
        return None
    if not config.allow_output_path:
        raise AudioError("output_dir is disabled on this server (HA_ALLOW_OUTPUT_PATH=false)")
    target = Path(output_dir).expanduser()
    if not target.is_dir():
        raise AudioError(f"output_dir does not exist: {target}")
    return target


def deliver(produced: Path, output_path: Path | None, config: AudioConfig,
            *, inline: bool | None = None) -> dict:
    """Move ``produced`` to ``output_path`` and/or return it as base64.

    With an output_path the bytes are written there and not inlined unless the
    caller asks (``inline=True``): a multi-megabyte base64 blob in an agent's
    context is the thing to avoid.
    """
    size = produced.stat().st_size
    result: dict = {"output_path": None, "audio_base64": None, "bytes": size}
    if output_path is not None:
        shutil.copyfile(produced, output_path)
        result["output_path"] = str(output_path)
        if not inline:
            return result
    if size > config.max_output_bytes:
        raise AudioError(
            f"result is {size} bytes, over HA_MAX_OUTPUT_BYTES ({config.max_output_bytes}); "
            "pass output_path to write it to disk instead"
        )
    result["audio_base64"] = base64.b64encode(produced.read_bytes()).decode("ascii")
    return result


__all__ = ["check_output_dir", "check_output_path", "deliver"]

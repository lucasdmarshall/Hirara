"""Deliver a produced image: write it where the caller asked, and/or inline it."""

from __future__ import annotations

import base64
from pathlib import Path

from .config import MediaConfig
from .errors import MediaError


def check_output_path(output_path: str | None, config: MediaConfig) -> Path | None:
    if not output_path:
        return None
    if not config.allow_output_path:
        raise MediaError("output_path is disabled on this server (HM_ALLOW_OUTPUT_PATH=false)")
    target = Path(output_path).expanduser()
    if target.exists() and target.is_dir():
        raise MediaError(f"output_path is a directory: {target}")
    if not target.parent.is_dir():
        raise MediaError(f"output directory does not exist: {target.parent}")
    return target


def deliver(data: bytes, fmt: str, target: Path | None, config: MediaConfig) -> dict:
    """Raster images go back as base64, SVG as text; both also written to target if given."""
    if target is not None:
        target.write_bytes(data)
    if len(data) > config.max_output_bytes:
        if target is None:
            raise MediaError(f"result is {len(data)} bytes, over HM_MAX_OUTPUT_BYTES; "
                            "pass output_path")
        return {"format": fmt, "bytes": len(data), "output_path": str(target),
                "image_base64": None, "svg": None}
    return {
        "format": fmt,
        "bytes": len(data),
        "output_path": str(target) if target else None,
        "image_base64": base64.b64encode(data).decode("ascii") if fmt != "svg" else None,
        "svg": data.decode("utf-8") if fmt == "svg" else None,
    }


__all__ = ["check_output_path", "deliver"]

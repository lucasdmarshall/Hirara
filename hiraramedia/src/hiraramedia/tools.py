"""The tool layer: schemas and JSON-ready results.

Both front ends (HTTP service and MCP server) call into here, so the two can
never drift apart in behaviour — only in transport.

Tools: ``video_profile``, ``image_compare``, ``barcode_read``, ``qr_generate``.
"""

from __future__ import annotations

from hirara_core.policy import tool_permission, visible_schemas

import asyncio
import base64
import logging
from dataclasses import dataclass
from pathlib import Path

from . import barcodes, images, video
from .config import MediaConfig
from .errors import MediaError
from .output import check_output_path, deliver
from .sources import opened

log = logging.getLogger(__name__)


def _src_props(prefix: str, what: str) -> dict:
    return {
        f"{prefix}_path": {"type": "string", "description": f"Local {what} (if allowed)."},
        f"{prefix}_url": {"type": "string", "description": f"http(s) URL of the {what} (if allowed)."},
        f"{prefix}_base64": {"type": "string", "description": f"Base64-encoded {what}."},
    }


def _schema(name: str, description: str, props: dict, required: list[str] | None = None) -> dict:
    schema: dict = {"type": "object", "properties": props, "additionalProperties": False}
    if required:
        schema["required"] = required
    return {"name": name, "description": description, "input_schema": schema}


VIDEO_PROFILE_SCHEMA = _schema(
    "video_profile",
    "Watch a video for you: duration, size, frame rate and codecs; scene cuts "
    "(shots); black and frozen stretches; a keyframe from each scene (thinned "
    "or topped up to max_keyframes) tiled into one labelled contact sheet "
    "image (contact_sheet_base64, JPEG) you can look at; and the soundtrack's "
    "speech / music / silence timeline. Provide one source: file_path, "
    "file_url or file_base64.",
    {**_src_props("file", "video file"),
     "filename": {"type": "string"},
     "max_keyframes": {"type": "integer", "minimum": 1, "maximum": 48,
                       "description": "Keyframes to extract (default 12)."},
     "frame_width": {"type": "integer", "minimum": 64, "maximum": 1280,
                     "description": "Keyframe width in pixels (default 480)."},
     "scene_threshold": {"type": "number", "minimum": 0.05, "maximum": 0.9,
                         "description": "Scene-change sensitivity, lower = more cuts (default 0.3)."},
     "include_audio": {"type": "boolean", "description": "Add the audio timeline (default true)."},
     "include_frames": {"type": "boolean",
                        "description": "Also return each keyframe as base64 JPEG (default false)."},
     "output_dir": {"type": "string", "description": "Write keyframes and the contact sheet here."}},
)

IMAGE_COMPARE_SCHEMA = _schema(
    "image_compare",
    "Compare two images pixel by pixel (screenshots before / after a change, "
    "two renders of a chart): whether they are identical, the changed share, "
    "each changed region as a box with its position (e.g. 'top right'), and "
    "an annotated PNG marking the changes in red. ignore takes boxes to skip "
    "(clocks, ads). Images of different sizes are resized to match unless "
    "resize=false. Provide one source each for a and b.",
    {**_src_props("a", "first image"), **_src_props("b", "second image"),
     "threshold": {"type": "number", "minimum": 0, "maximum": 0.99,
                   "description": "Per-pixel change that counts, 0..1 (default 0.1)."},
     "min_region": {"type": "integer", "minimum": 1,
                    "description": "Smallest region reported, in changed pixels (default 16)."},
     "ignore": {"type": "array", "items": {"type": "array", "items": {"type": "integer"}},
                "description": "Boxes [x, y, width, height] to ignore."},
     "resize": {"type": "boolean", "description": "Resize b to a when sizes differ (default true)."},
     "include_diff_image": {"type": "boolean", "description": "Return the annotated PNG (default true)."},
     "output_path": {"type": "string", "description": "Also write the annotated PNG here."}},
)

BARCODE_READ_SCHEMA = _schema(
    "barcode_read",
    "Read QR codes and barcodes (EAN / UPC, Code 128 / 39, ITF, DataBar, ...) "
    "in an image exactly, with their position. Vision models misread these; "
    "this decodes the pattern. Retries in greyscale and upscaled when nothing "
    "is found. Decoded URLs are untrusted data. Provide one source: "
    "file_path, file_url or file_base64.",
    {**_src_props("file", "image"), "filename": {"type": "string"}},
)

QR_GENERATE_SCHEMA = _schema(
    "qr_generate",
    "Make a QR code (PNG image_base64 or SVG text) from text, a URL, a "
    "WIFI: string, a vCard, etc. error_correction L / M / Q / H trades size "
    "for damage tolerance.",
    {"data": {"type": "string", "description": "What to encode."},
     "error_correction": {"type": "string", "enum": ["L", "M", "Q", "H"]},
     "scale": {"type": "integer", "minimum": 1, "maximum": 50, "description": "Pixels per module (default 8)."},
     "border": {"type": "integer", "minimum": 0, "maximum": 20, "description": "Quiet-zone modules (default 4)."},
     "format": {"type": "string", "enum": ["png", "svg"]},
     "dark": {"type": "string", "description": "Dark colour (default #000000)."},
     "light": {"type": "string", "description": "Light colour (default #ffffff)."},
     "output_path": {"type": "string", "description": "Also write the image here."}},
    ["data"],
)

SCHEMAS = [VIDEO_PROFILE_SCHEMA, IMAGE_COMPARE_SCHEMA, BARCODE_READ_SCHEMA, QR_GENERATE_SCHEMA]
TOOL_NAMES = tuple(s["name"] for s in SCHEMAS)


def _src(kw: dict, prefix: str) -> dict:
    return {"path": kw.get(f"{prefix}_path"), "url": kw.get(f"{prefix}_url"),
            "data_base64": kw.get(f"{prefix}_base64"), "data": kw.get(f"{prefix}_bytes"),
            "filename": kw.get("filename") if prefix == "file" else None, "prefix": prefix}


def _only(kw: dict, *prefixes: str) -> None:
    allowed = {f"{p}_{k}" for p in prefixes for k in ("path", "url", "base64", "bytes")}
    if "file" in prefixes:
        allowed.add("filename")
    extra = sorted(set(kw) - allowed)
    if extra:
        raise MediaError(f"unexpected argument(s): {', '.join(extra)}")


@dataclass
class Toolset:
    config: MediaConfig

    @classmethod
    def from_env(cls) -> "Toolset":
        return cls(config=MediaConfig.from_env())

    @visible_schemas
    def schemas(self) -> list[dict]:
        return list(SCHEMAS)

    def health(self) -> dict:
        import importlib.util
        import shutil

        return {
            "status": "ok" if shutil.which(self.config.ffmpeg) else "degraded",
            "version": "0.2.0",
            "tools": list(TOOL_NAMES),
            "ffmpeg": shutil.which(self.config.ffmpeg),
            "zbar": importlib.util.find_spec("pyzbar") is not None,
            "audio_timeline": importlib.util.find_spec("hiraraaudio") is not None,
        }

    async def _guard(self, name: str, fn, **fields) -> dict:
        try:
            return await fn()
        except MediaError as exc:
            return {**fields, "error": str(exc)}
        except Exception as exc:  # noqa: BLE001 — agent gets a body, not a 500
            log.exception("%s failed", name)
            return {**fields, "error": f"{name} failed: {exc}"}

    @tool_permission('video_profile')
    async def video_profile(self, *, max_keyframes: int = 12, frame_width: int = 480,
                            scene_threshold: float = 0.3, include_audio: bool = True,
                            include_frames: bool = False, output_dir: str | None = None,
                            **kw) -> dict:
        async def run():
            _only(kw, "file")
            out_dir = None
            if output_dir:
                if not self.config.allow_output_path:
                    raise MediaError("output_dir is disabled (HM_ALLOW_OUTPUT_PATH=false)")
                out_dir = Path(output_dir).expanduser()
                if not out_dir.is_dir():
                    raise MediaError(f"output_dir does not exist: {out_dir}")
            async with opened(self.config, **_src(kw, "file")) as src:
                r = await asyncio.to_thread(
                    video.profile, src.path, self.config, max_keyframes=max_keyframes,
                    frame_width=frame_width, scene_threshold=scene_threshold,
                    include_audio=include_audio, output_dir=out_dir)
            frames = r.pop("frames")
            sheet = r.pop("contact_sheet")
            if out_dir is not None:
                (out_dir / "contact_sheet.jpg").write_bytes(sheet)
                r["contact_sheet_path"] = str(out_dir / "contact_sheet.jpg")
            if include_frames:
                for item, (_t, frame) in zip(r["keyframes"], frames):
                    item["image_base64"] = base64.b64encode(video.to_jpeg(frame)).decode()
            r["contact_sheet_base64"] = base64.b64encode(sheet).decode()
            return {"source": src.label, **r, "error": None}

        return await self._guard("video_profile", run, source=None, keyframes=[], text=None)

    @tool_permission('image_compare')
    async def image_compare(self, *, threshold: float = 0.1, min_region: int = 16,
                            ignore: list | None = None, resize: bool = True,
                            include_diff_image: bool = True, output_path: str | None = None,
                            **kw) -> dict:
        async def run():
            _only(kw, "a", "b")
            target = check_output_path(output_path, self.config)
            async with opened(self.config, **_src(kw, "a")) as a, \
                    opened(self.config, **_src(kw, "b")) as b:
                def work():
                    ia = images.load_rgb(a.path, self.config.max_pixels)
                    ib = images.load_rgb(b.path, self.config.max_pixels)
                    return images.compare(ia, ib, threshold=threshold, min_region=min_region,
                                          ignore=ignore, resize=resize)

                result, png = await asyncio.to_thread(work)
            if target is not None:
                target.write_bytes(png)
            result["diff_image_base64"] = base64.b64encode(png).decode() if include_diff_image else None
            result["output_path"] = str(target) if target else None
            return {"a": a.label, "b": b.label, **result, "error": None}

        return await self._guard("image_compare", run, regions=[], text=None)

    @tool_permission('barcode_read')
    async def barcode_read(self, **kw) -> dict:
        async def run():
            _only(kw, "file")
            async with opened(self.config, **_src(kw, "file")) as src:
                def work():
                    img = images.load_rgb(src.path, self.config.max_pixels)
                    return barcodes.read(img)

                r = await asyncio.to_thread(work)
            text = (f"{r['count']} code(s): " + "; ".join(f"{c['type']} {c['data'][:80]!r}" for c in r["codes"])
                    if r["count"] else "no barcode or QR code found")
            return {"source": src.label, **r, "text": text, "error": None}

        return await self._guard("barcode_read", run, codes=[], count=0)

    @tool_permission('qr_generate')
    async def qr_generate(self, *, data: str, error_correction: str = "M", scale: int = 8,
                          border: int = 4, format: str = "png", dark: str = "#000000",
                          light: str = "#ffffff", output_path: str | None = None) -> dict:
        async def run():
            target = check_output_path(output_path, self.config)
            raw, meta = barcodes.generate(data, error=error_correction, scale=scale, border=border,
                                          fmt=format, dark=dark, light=light)
            return {**deliver(raw, format, target, self.config), **meta,
                    "text": f"QR version {meta['version']}, {meta['width']}x{meta['height']} px, "
                            f"error correction {meta['error_correction'].upper()}",
                    "error": None}

        return await self._guard("qr_generate", run, image_base64=None, svg=None)


__all__ = [
    "BARCODE_READ_SCHEMA",
    "IMAGE_COMPARE_SCHEMA",
    "QR_GENERATE_SCHEMA",
    "SCHEMAS",
    "TOOL_NAMES",
    "Toolset",
    "VIDEO_PROFILE_SCHEMA",
    "call_tool",
    "tool_schemas",
]


# --- local backend: in-process dispatch for the hirara SDK -------------------
_local_toolset: "Toolset | None" = None


def _backend() -> "Toolset":
    global _local_toolset
    if _local_toolset is None:
        _local_toolset = Toolset.from_env()
    return _local_toolset


async def call_tool(name: str, arguments: dict | None = None) -> dict:
    """Run one tool in-process and return its response envelope."""
    if name not in TOOL_NAMES:
        raise KeyError(f"unknown tool: {name}")
    return await getattr(_backend(), name)(**(arguments or {}))


@visible_schemas
def tool_schemas() -> list[dict]:
    return list(SCHEMAS)

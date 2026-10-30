"""Administrator configuration and thin transport adapter for Rust document tools."""
from __future__ import annotations

from dataclasses import dataclass
import importlib.util
import json
import os
from pathlib import Path
import re

from hirara_core.native import native_call
from .paths import require_roots, PathError


@dataclass(frozen=True)
class DocumentConfig:
    collections: dict[str, str] | None = None
    models_dir: str = ""
    tier: str = "lite"
    allow_write: bool = True
    max_input_bytes: int = 2_000_000

    @classmethod
    def from_env(cls):
        collections = json.loads(os.getenv("CRAG_COLLECTIONS") or "{}")
        if not isinstance(collections, dict) or len(collections) > 32:
            raise ValueError("CRAG_COLLECTIONS must be a JSON object with at most 32 named paths")
        for name, path in collections.items():
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", name) or not isinstance(path, str) or not path.strip():
                raise ValueError("invalid collection name or path in CRAG_COLLECTIONS")
        tier = os.getenv("CRAG_TIER") or "lite"
        if tier not in {"lite", "full"}:
            raise ValueError("CRAG_TIER must be lite or full")
        cap = int(os.getenv("CRAG_MAX_INPUT_BYTES") or "2000000")
        if cap < 1:
            raise ValueError("CRAG_MAX_INPUT_BYTES must be positive")
        return cls(collections={name: str(Path(path).expanduser().resolve()) for name, path in collections.items()},
                   models_dir=os.getenv("CRAG_MODEL_DIR", ""), tier=tier,
                   allow_write=(os.getenv("CRAG_ALLOW_WRITE") or "true").lower() in {"true", "1", "yes", "on"},
                   max_input_bytes=cap)


def _pdfium() -> None:
    if os.getenv("GYR_PDFIUM"):
        return
    spec = importlib.util.find_spec("pypdfium2_raw")
    if spec and spec.submodule_search_locations:
        package = Path(next(iter(spec.submodule_search_locations)))
        for name in ("libpdfium.so", "libpdfium.dylib", "pdfium.dll"):
            if (package / name).is_file():
                os.environ.setdefault("GYR_PDFIUM", str(package / name))
                break


async def call(action: str, *, config: DocumentConfig, fs_config, collection: str = "default", **args) -> dict:
    envelope = {"collection": collection, "error": None}
    if not isinstance(collection, str) or collection not in (config.collections or {}):
        return {**envelope, "error": "unknown collection; configure CRAG_COLLECTIONS on the server"}
    if action != "document_search" and not config.allow_write:
        return {**envelope, "error": "document mutations disabled (CRAG_ALLOW_WRITE=false)"}
    if not config.models_dir:
        return {**envelope, "error": "set CRAG_MODEL_DIR to pre-provisioned Gyrfalcon model files; no automatic downloads"}
    roots = []
    if args.get("path") is not None:
        try:
            roots = [str(root) for root in require_roots(fs_config)]
        except PathError as exc:
            return {**envelope, "error": str(exc)}
        if not isinstance(args["path"], str):
            return {**envelope, "error": "path must be a string"}
        args["path"] = os.path.expanduser(args["path"])
        if args["path"].lower().endswith(".pdf"):
            _pdfium()
    return {**envelope, **await native_call(
        action, **args, collection_path=(config.collections or {})[collection],
        models_path=str(Path(config.models_dir).expanduser().resolve()), tier=config.tier,
        allow_write=config.allow_write, roots=roots, allow_any_path=fs_config.allow_any_path,
        max_file_bytes=fs_config.max_bytes, max_input_bytes=config.max_input_bytes)}


async def close(config: DocumentConfig):
    for path in (config.collections or {}).values():
        await native_call("document_close", collection_path=path)

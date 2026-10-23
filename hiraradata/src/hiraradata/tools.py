"""The tool layer: schemas and JSON-ready results.

Both front ends (HTTP service and MCP server) call into here, so the two can
never drift apart in behaviour — only in transport.

Tools: ``data_profile``, ``chart_render``, ``diagram_render``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import tempfile
from dataclasses import dataclass
from pathlib import Path

from . import charts, diagrams
from .config import DataConfig
from .errors import DataError
from .output import check_output_path, deliver
from .profile import profile_path, profile_records
from .sources import opened

log = logging.getLogger(__name__)

_FILE = {
    "file_path": {"type": "string", "description": "Local file (if the server allows local paths)."},
    "file_url": {"type": "string", "description": "http(s) URL (if the server allows URL fetch)."},
    "file_base64": {"type": "string", "description": "Base64-encoded file bytes."},
    "filename": {"type": "string", "description": "Original name; its extension hints the format."},
}

DATA_PROFILE_SCHEMA = {
    "name": "data_profile",
    "description": (
        "Profile a table you cannot read in full: CSV, TSV, JSON, JSON Lines, "
        "Excel (.xlsx) or Parquet. Streams every row once and returns per "
        "column the inferred type, nulls, distinct count, top values, numeric "
        "stats (min / max / mean / std / quantiles / histogram / outliers), "
        "string lengths and date ranges, plus table-level warnings (duplicate "
        "rows, constant / empty columns, mixed types, likely IDs, ragged rows) "
        "and a few sample rows. Give a file, or inline data (CSV text, JSON "
        "text, or a list of objects)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            **_FILE,
            "data": {"description": "Inline data: CSV / JSON text, or a list of objects."},
            "format": {"type": "string",
                       "enum": ["auto", "csv", "tsv", "json", "jsonl", "xlsx", "parquet"]},
            "sheet": {"type": "string", "description": "Excel sheet (default first)."},
            "delimiter": {"type": "string", "description": "CSV delimiter (default sniffed)."},
            "has_header": {"type": "boolean", "description": "CSV first row is a header (default sniffed)."},
            "max_rows": {"type": "integer", "minimum": 1},
            "sample_rows": {"type": "integer", "minimum": 0, "maximum": 50},
        },
        "additionalProperties": False,
    },
}

CHART_RENDER_SCHEMA = {
    "name": "chart_render",
    "description": (
        "Render a chart from numbers: line, bar, barh, scatter, area, pie, "
        "histogram or box, as PNG (image_base64) or SVG (svg text). Give x "
        "plus series [{name, values}], or records (a list of objects) with "
        "x_field and y_fields. Returns a text description of the plotted "
        "values (min / max and where) so you can check the chart without "
        "seeing it."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "type": {"type": "string", "enum": list(charts.KINDS)},
            "x": {"type": "array", "description": "x values or category labels."},
            "series": {"type": "array", "items": {"type": "object", "properties": {
                "name": {"type": "string"},
                "values": {"type": "array", "items": {"type": ["number", "null"]}}}}},
            "records": {"type": "array", "items": {"type": "object"},
                        "description": "Rows of data instead of x / series."},
            "x_field": {"type": "string"},
            "y_fields": {"type": "array", "items": {"type": "string"}},
            "title": {"type": "string"},
            "x_label": {"type": "string"},
            "y_label": {"type": "string"},
            "width": {"type": "integer", "minimum": 200, "maximum": 4000},
            "height": {"type": "integer", "minimum": 150, "maximum": 4000},
            "format": {"type": "string", "enum": ["png", "svg"]},
            "stacked": {"type": "boolean"},
            "log_y": {"type": "boolean"},
            "legend": {"type": "boolean"},
            "bins": {"type": "integer", "minimum": 1, "maximum": 200},
            "output_path": {"type": "string", "description": "Also write the image here."},
        },
        "required": ["type"],
        "additionalProperties": False,
    },
}

DIAGRAM_RENDER_SCHEMA = {
    "name": "diagram_render",
    "description": (
        "Render a diagram written as text to PNG or SVG: Graphviz DOT (any "
        "graph) or a Mermaid flowchart (graph / flowchart with node shapes, "
        "labelled edges, dotted / thick links and subgraphs). Layout by "
        "Graphviz; no browser needed. Attributes that read server files "
        "(image, shapefile, fontpath) are refused."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "source": {"type": "string", "description": "DOT or Mermaid flowchart text."},
            "language": {"type": "string", "enum": ["auto", "dot", "mermaid"]},
            "format": {"type": "string", "enum": ["png", "svg"]},
            "engine": {"type": "string", "enum": list(diagrams.ENGINES),
                       "description": "Graphviz layout engine (default dot)."},
            "output_path": {"type": "string", "description": "Also write the image here."},
        },
        "required": ["source"],
        "additionalProperties": False,
    },
}

SCHEMAS = [DATA_PROFILE_SCHEMA, CHART_RENDER_SCHEMA, DIAGRAM_RENDER_SCHEMA]
TOOL_NAMES = tuple(s["name"] for s in SCHEMAS)


def _inline_rows(data):
    """Inline data -> (records list) or (temp file path, format)."""
    if isinstance(data, list):
        return data, None
    if isinstance(data, dict):
        return [data], None
    if not isinstance(data, str) or not data.strip():
        raise DataError("data must be CSV / JSON text or a list of objects")
    text = data.strip()
    if text[0] in "[{":
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = None
        if parsed is not None:
            if isinstance(parsed, dict):
                lists = [v for v in parsed.values() if isinstance(v, list)]
                parsed = lists[0] if len(lists) == 1 else [parsed]
            return parsed, None
    return None, text


@dataclass
class Toolset:
    config: DataConfig

    @classmethod
    def from_env(cls) -> "Toolset":
        return cls(config=DataConfig.from_env())

    def schemas(self) -> list[dict]:
        return list(SCHEMAS)

    def health(self) -> dict:
        import shutil

        return {"status": "ok", "version": "0.1.0", "tools": list(TOOL_NAMES),
                "graphviz": shutil.which(self.config.dot),
                "allow_local_path": self.config.allow_local_path,
                "allow_url_fetch": self.config.allow_url_fetch}

    async def _guard(self, name: str, fn, **fields) -> dict:
        try:
            return await fn()
        except DataError as exc:
            return {**fields, "error": str(exc)}
        except Exception as exc:  # noqa: BLE001 — agent gets a body, not a 500
            log.exception("%s failed", name)
            return {**fields, "error": f"{name} failed: {exc}"}

    async def data_profile(self, *, file_path: str | None = None, file_url: str | None = None,
                           file_base64: str | None = None, file_bytes: bytes | None = None,
                           filename: str | None = None, data=None, format: str | None = None,
                           sheet: str | None = None, delimiter: str | None = None,
                           has_header: bool | None = None, max_rows: int | None = None,
                           sample_rows: int = 5) -> dict:
        async def run():
            rows_cap = min(max_rows or self.config.max_rows, self.config.max_rows)
            opts = dict(max_rows=rows_cap, max_columns=self.config.max_columns,
                        sample_rows=max(0, min(int(sample_rows), 50)))
            if data is not None:
                if any((file_path, file_url, file_base64, file_bytes)):
                    raise DataError("give data or a file, not both")
                records, text = _inline_rows(data)
                if records is not None:
                    result = await asyncio.to_thread(profile_records, records, **opts)
                    return {**result, "source": "inline", "error": None}
                with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False,
                                                 encoding="utf-8") as tmp:
                    tmp.write(text)
                try:
                    result = await asyncio.to_thread(
                        profile_path, Path(tmp.name), fmt=format, delimiter=delimiter,
                        has_header=has_header, **opts)
                finally:
                    Path(tmp.name).unlink(missing_ok=True)
                return {**result, "source": "inline", "error": None}
            async with opened(self.config, path=file_path, url=file_url, data_base64=file_base64,
                              data=file_bytes, filename=filename, prefix="file") as src:
                result = await asyncio.to_thread(
                    profile_path, src.path, fmt=format, sheet=sheet, delimiter=delimiter,
                    has_header=has_header, **opts)
                return {**result, "source": src.label, "error": None}

        return await self._guard("data_profile", run, column_profiles=[], warnings=[], text=None)

    async def chart_render(self, *, type: str, x: list | None = None, series: list | None = None,
                           records: list | None = None, x_field: str | None = None,
                           y_fields: list[str] | None = None, title: str | None = None,
                           x_label: str | None = None, y_label: str | None = None,
                           width: int = 900, height: int = 500, format: str = "png",
                           stacked: bool = False, log_y: bool = False, legend: bool | None = None,
                           bins: int = 20, output_path: str | None = None) -> dict:
        async def run():
            target = check_output_path(output_path, self.config)
            xs, ser = charts.normalise_series(x=x, series=series, records=records, x_field=x_field,
                                              y_fields=y_fields, max_points=self.config.max_points)
            data, text = await asyncio.to_thread(
                charts.render, type, xs, ser, title=title, x_label=x_label, y_label=y_label,
                width=width, height=height, fmt=format, stacked=stacked, log_y=log_y,
                legend=legend, bins=bins)
            return {**deliver(data, format, target, self.config), "type": type, "text": text,
                    "error": None}

        return await self._guard("chart_render", run, image_base64=None, svg=None, text=None)

    async def diagram_render(self, *, source: str, language: str = "auto", format: str = "png",
                             engine: str = "dot", output_path: str | None = None) -> dict:
        async def run():
            target = check_output_path(output_path, self.config)
            data, dot = await asyncio.to_thread(diagrams.render, source, language=language,
                                                fmt=format, engine=engine, config=self.config)
            translated = dot if dot != source else None
            return {**deliver(data, format, target, self.config), "engine": engine,
                    "dot": translated, "error": None}

        return await self._guard("diagram_render", run, image_base64=None, svg=None)


__all__ = [
    "CHART_RENDER_SCHEMA",
    "DATA_PROFILE_SCHEMA",
    "DIAGRAM_RENDER_SCHEMA",
    "SCHEMAS",
    "TOOL_NAMES",
    "Toolset",
    "call_tool",
    "tool_schemas",
]


# --- local backend: in-process dispatch for the hirara SDK -------------------
# Discovered by the hirara SDK through the ``hirara.backends`` entry point and
# called directly (no HTTP hop). Reuses the same Toolset the service and MCP
# server use, so behaviour cannot drift between local and networked calls.
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


def tool_schemas() -> list[dict]:
    return list(SCHEMAS)

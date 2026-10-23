"""MCP front end — data profiling, charts and diagrams for agents.

    python -m hiraradata.mcp_server                       # stdio
    python -m hiraradata.mcp_server --transport streamable-http
"""

from __future__ import annotations

import argparse
from typing import Any

from mcp.server.mcpserver import MCPServer

from . import tools as T
from .tools import Toolset

server = MCPServer(
    name="hiraradata",
    version="0.1.0",
    instructions=(
        "Data tools for an agent. data_profile summarises a table too big to read "
        "(types, nulls, stats, outliers, duplicates). chart_render turns numbers into "
        "a chart image; diagram_render turns DOT or a Mermaid flowchart into an image. "
        "No API keys."
    ),
)

_toolset = Toolset.from_env()


@server.tool(name="data_profile", description=T.DATA_PROFILE_SCHEMA["description"])
async def data_profile_tool(file_path: str | None = None, file_url: str | None = None,
                            file_base64: str | None = None, filename: str | None = None,
                            data: Any = None, format: str | None = None, sheet: str | None = None,
                            delimiter: str | None = None, has_header: bool | None = None,
                            max_rows: int | None = None, sample_rows: int = 5) -> dict:
    return await _toolset.data_profile(
        file_path=file_path, file_url=file_url, file_base64=file_base64, filename=filename,
        data=data, format=format, sheet=sheet, delimiter=delimiter, has_header=has_header,
        max_rows=max_rows, sample_rows=sample_rows)


@server.tool(name="chart_render", description=T.CHART_RENDER_SCHEMA["description"])
async def chart_render_tool(type: str, x: list | None = None, series: list[dict] | None = None,
                            records: list[dict] | None = None, x_field: str | None = None,
                            y_fields: list[str] | None = None, title: str | None = None,
                            x_label: str | None = None, y_label: str | None = None,
                            width: int = 900, height: int = 500, format: str = "png",
                            stacked: bool = False, log_y: bool = False,
                            legend: bool | None = None, bins: int = 20,
                            output_path: str | None = None) -> dict:
    return await _toolset.chart_render(
        type=type, x=x, series=series, records=records, x_field=x_field, y_fields=y_fields,
        title=title, x_label=x_label, y_label=y_label, width=width, height=height,
        format=format, stacked=stacked, log_y=log_y, legend=legend, bins=bins,
        output_path=output_path)


@server.tool(name="diagram_render", description=T.DIAGRAM_RENDER_SCHEMA["description"])
async def diagram_render_tool(source: str, language: str = "auto", format: str = "png",
                              engine: str = "dot", output_path: str | None = None) -> dict:
    return await _toolset.diagram_render(source=source, language=language, format=format,
                                         engine=engine, output_path=output_path)


def main() -> None:
    parser = argparse.ArgumentParser(description="HiraraData MCP server")
    parser.add_argument("--transport", default="stdio",
                        choices=["stdio", "sse", "streamable-http"])
    args = parser.parse_args()
    server.run(transport=args.transport)


if __name__ == "__main__":
    main()

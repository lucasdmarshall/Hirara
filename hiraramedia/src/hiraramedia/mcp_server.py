"""MCP front end — video, image and barcode tools for agents.

    python -m hiraramedia.mcp_server                       # stdio
    python -m hiraramedia.mcp_server --transport streamable-http
"""

from __future__ import annotations

import argparse

from mcp.server.mcpserver import MCPServer

from . import tools as T
from .tools import Toolset

server = MCPServer(
    name="hiraramedia",
    version="0.1.0",
    instructions=(
        "Media tools for an agent. video_profile 'watches' a video: shots, black and "
        "frozen stretches, keyframes on one contact sheet, and the audio timeline. "
        "image_compare finds and boxes what changed between two images. barcode_read "
        "decodes QR codes and barcodes exactly; qr_generate makes QR codes. No API keys."
    ),
)

_toolset = Toolset.from_env()


@server.tool(name="video_profile", description=T.VIDEO_PROFILE_SCHEMA["description"])
async def video_profile_tool(file_path: str | None = None, file_url: str | None = None,
                             file_base64: str | None = None, filename: str | None = None,
                             max_keyframes: int = 12, frame_width: int = 480,
                             scene_threshold: float = 0.3, include_audio: bool = True,
                             include_frames: bool = False, output_dir: str | None = None) -> dict:
    kw = {k: v for k, v in {"file_path": file_path, "file_url": file_url,
                            "file_base64": file_base64, "filename": filename}.items() if v}
    return await _toolset.video_profile(max_keyframes=max_keyframes, frame_width=frame_width,
                                        scene_threshold=scene_threshold,
                                        include_audio=include_audio,
                                        include_frames=include_frames, output_dir=output_dir, **kw)


@server.tool(name="image_compare", description=T.IMAGE_COMPARE_SCHEMA["description"])
async def image_compare_tool(a_path: str | None = None, a_url: str | None = None,
                             a_base64: str | None = None, b_path: str | None = None,
                             b_url: str | None = None, b_base64: str | None = None,
                             threshold: float = 0.1, min_region: int = 16,
                             ignore: list[list[int]] | None = None, resize: bool = True,
                             include_diff_image: bool = True,
                             output_path: str | None = None) -> dict:
    kw = {k: v for k, v in {"a_path": a_path, "a_url": a_url, "a_base64": a_base64,
                            "b_path": b_path, "b_url": b_url, "b_base64": b_base64}.items() if v}
    return await _toolset.image_compare(threshold=threshold, min_region=min_region, ignore=ignore,
                                        resize=resize, include_diff_image=include_diff_image,
                                        output_path=output_path, **kw)


@server.tool(name="barcode_read", description=T.BARCODE_READ_SCHEMA["description"])
async def barcode_read_tool(file_path: str | None = None, file_url: str | None = None,
                            file_base64: str | None = None, filename: str | None = None) -> dict:
    kw = {k: v for k, v in {"file_path": file_path, "file_url": file_url,
                            "file_base64": file_base64, "filename": filename}.items() if v}
    return await _toolset.barcode_read(**kw)


@server.tool(name="qr_generate", description=T.QR_GENERATE_SCHEMA["description"])
async def qr_generate_tool(data: str, error_correction: str = "M", scale: int = 8,
                           border: int = 4, format: str = "png", dark: str = "#000000",
                           light: str = "#ffffff", output_path: str | None = None) -> dict:
    return await _toolset.qr_generate(data=data, error_correction=error_correction, scale=scale,
                                      border=border, format=format, dark=dark, light=light,
                                      output_path=output_path)


def main() -> None:
    parser = argparse.ArgumentParser(description="HiraraMedia MCP server")
    parser.add_argument("--transport", default="stdio",
                        choices=["stdio", "sse", "streamable-http"])
    args = parser.parse_args()
    server.run(transport=args.transport)


if __name__ == "__main__":
    main()

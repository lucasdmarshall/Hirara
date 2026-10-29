"""MCP front end — agents and IDEs call Whisper as a tool.

Run over stdio for Claude Code / Claude Desktop / Cursor::

    python -m hirarastt.mcp_server

Or over HTTP for a remote client::

    python -m hirarastt.mcp_server --transport stdio
"""

from __future__ import annotations

from hirara_core.policy import mcp_errors

import argparse

from mcp.server.mcpserver import MCPServer

from .tools import Toolset

server = MCPServer(
    name="hirarastt",
    version="0.2.0",
    instructions=(
        "Free open-source speech-to-text powered by Whisper. Use the "
        "transcribe tool to turn audio or video into text. Prefer a local "
        "audio_path when the file is already on disk; use audio_base64 only "
        "for small clips. No API keys required."
    ),
)

_toolset = Toolset.from_env()


@server.tool(
    name="transcribe",
    description=(
        "Transcribe speech from an audio or video file into text using "
        "open-source Whisper (no API keys, runs locally).\n\n"
        "Use this when the user provides audio/video and you need the spoken "
        "content as text: meetings, voice notes, interviews, podcasts, "
        "lectures, or any clip you cannot listen to directly.\n\n"
        "Provide exactly one audio source: audio_path (local file), "
        "audio_url (http/https, if the server allows URL fetch), or "
        "audio_base64 (raw bytes). Prefer audio_path over base64 when the "
        "file is large.\n\n"
        "Set task=translate to get an English translation of non-English "
        "speech. Pass language (ISO-639-1) when you already know it."
    ),
)
@mcp_errors
async def transcribe_tool(
    audio_path: str | None = None,
    audio_url: str | None = None,
    audio_base64: str | None = None,
    filename: str | None = None,
    language: str | None = None,
    task: str = "transcribe",
    timestamps: bool = True,
    prompt: str | None = None,
) -> dict:
    """Speech-to-text via open-source Whisper.

    Args:
        audio_path: Local path to an audio/video file.
        audio_url: http(s) URL of an audio/video file (if URL fetch is enabled).
        audio_base64: Base64-encoded audio bytes (small clips only).
        filename: Original filename when using audio_base64.
        language: Optional ISO-639-1 language code; omit to auto-detect.
        task: "transcribe" (same language) or "translate" (to English).
        timestamps: Include segment-level timestamps.
        prompt: Optional initial prompt for spelling/names/style.
    """
    return await _toolset.transcribe(
        audio_path=audio_path,
        audio_url=audio_url,
        audio_base64=audio_base64,
        filename=filename,
        language=language,
        task=task,
        timestamps=timestamps,
        prompt=prompt,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="HiraraSTT MCP server")
    parser.add_argument(
        "--transport",
        default="stdio",
        choices=["stdio", "sse", "streamable-http"],
        help="MCP transport to serve on (default: stdio).",
    )
    args = parser.parse_args()
    if args.transport != "stdio":
        parser.error("network MCP is disabled; use stdio or the authenticated HTTP hub")
    server.run(transport=args.transport)


if __name__ == "__main__":
    main()

"""MCP front end — agents and IDEs call the audio tools directly.

Run over stdio for Claude Code / Claude Desktop / Cursor::

    python -m hiraraaudio.mcp_server

Or over HTTP for a remote client::

    python -m hiraraaudio.mcp_server --transport stdio
"""

from __future__ import annotations

from hirara_core.policy import mcp_errors

import argparse

from mcp.server.mcpserver import MCPServer

from . import tools as T
from .tools import Toolset

server = MCPServer(
    name="hiraraaudio",
    version="0.2.0",
    instructions=(
        "Lightweight audio tools for an agent that cannot listen. Start with "
        "audio_profile to learn what a recording contains. audio_check judges it "
        "against a delivery spec and audio_fix repairs it; audio_compare verifies an "
        "edit; audio_find / audio_fingerprint locate shared material; audio_split and "
        "audio_tighten edit at natural pauses; audio_spectrogram gives an image; "
        "audio_tones finds DTMF, beeps and hum; audio_speak and audio_sonify make "
        "sound; audio_watch monitors a live stream. Prefer audio_path over base64 for "
        "large files. Signal processing only, no ML models, no API keys."
    ),
)

_toolset = Toolset.from_env()


def _d(schema: dict) -> str:
    return schema["description"]


@server.tool(name="audio_info", description=_d(T.AUDIO_INFO_SCHEMA))
@mcp_errors
async def audio_info_tool(audio_path: str | None = None, audio_url: str | None = None,
                          audio_base64: str | None = None, filename: str | None = None) -> dict:
    return await _toolset.audio_info(audio_path=audio_path, audio_url=audio_url,
                                     audio_base64=audio_base64, filename=filename)


@server.tool(name="audio_profile", description=_d(T.AUDIO_PROFILE_SCHEMA))
@mcp_errors
async def audio_profile_tool(audio_path: str | None = None, audio_url: str | None = None,
                             audio_base64: str | None = None, filename: str | None = None,
                             start: float | None = None, duration: float | None = None,
                             max_segments: int = 40, silence_db: float | None = None,
                             long_silence_s: float = 3.0) -> dict:
    return await _toolset.audio_profile(
        audio_path=audio_path, audio_url=audio_url, audio_base64=audio_base64,
        filename=filename, start=start, duration=duration, max_segments=max_segments,
        silence_db=silence_db, long_silence_s=long_silence_s)


@server.tool(name="audio_check", description=_d(T.AUDIO_CHECK_SCHEMA))
@mcp_errors
async def audio_check_tool(audio_path: str | None = None, audio_url: str | None = None,
                           audio_base64: str | None = None, filename: str | None = None,
                           preset: str = "podcast", start: float | None = None,
                           duration: float | None = None) -> dict:
    return await _toolset.audio_check(
        audio_path=audio_path, audio_url=audio_url, audio_base64=audio_base64,
        filename=filename, preset=preset, start=start, duration=duration)


@server.tool(name="audio_fix", description=_d(T.AUDIO_FIX_SCHEMA))
@mcp_errors
async def audio_fix_tool(audio_path: str | None = None, audio_url: str | None = None,
                         audio_base64: str | None = None, filename: str | None = None,
                         preset: str | None = None, target_lufs: float | None = None,
                         max_true_peak: float | None = None, remove_dc: bool | None = None,
                         dehum: str = "auto", highpass_hz: float | None = None,
                         denoise: bool = False, sample_rate: int | None = None,
                         output_format: str | None = None, output_path: str | None = None,
                         return_audio: bool = False) -> dict:
    return await _toolset.audio_fix(
        audio_path=audio_path, audio_url=audio_url, audio_base64=audio_base64,
        filename=filename, preset=preset, target_lufs=target_lufs,
        max_true_peak=max_true_peak, remove_dc=remove_dc, dehum=dehum,
        highpass_hz=highpass_hz, denoise=denoise, sample_rate=sample_rate,
        output_format=output_format, output_path=output_path, return_audio=return_audio)


@server.tool(name="audio_compare", description=_d(T.AUDIO_COMPARE_SCHEMA))
@mcp_errors
async def audio_compare_tool(a_path: str | None = None, a_url: str | None = None,
                             a_base64: str | None = None, b_path: str | None = None,
                             b_url: str | None = None, b_base64: str | None = None) -> dict:
    return await _toolset.audio_compare(a_path=a_path, a_url=a_url, a_base64=a_base64,
                                        b_path=b_path, b_url=b_url, b_base64=b_base64)


@server.tool(name="audio_find", description=_d(T.AUDIO_FIND_SCHEMA))
@mcp_errors
async def audio_find_tool(audio_path: str | None = None, audio_url: str | None = None,
                          audio_base64: str | None = None, filename: str | None = None,
                          clip_path: str | None = None, clip_url: str | None = None,
                          clip_base64: str | None = None, clip_start: float | None = None,
                          clip_end: float | None = None, threshold: float = 0.8,
                          max_matches: int = 50) -> dict:
    return await _toolset.audio_find(
        audio_path=audio_path, audio_url=audio_url, audio_base64=audio_base64,
        filename=filename, clip_path=clip_path, clip_url=clip_url, clip_base64=clip_base64,
        clip_start=clip_start, clip_end=clip_end, threshold=threshold,
        max_matches=max_matches)


@server.tool(name="audio_fingerprint", description=_d(T.AUDIO_FINGERPRINT_SCHEMA))
@mcp_errors
async def audio_fingerprint_tool(audio_paths: list[str] | None = None,
                                 audio_urls: list[str] | None = None) -> dict:
    return await _toolset.audio_fingerprint(audio_paths=audio_paths, audio_urls=audio_urls)


@server.tool(name="audio_split", description=_d(T.AUDIO_SPLIT_SCHEMA))
@mcp_errors
async def audio_split_tool(audio_path: str | None = None, audio_url: str | None = None,
                           audio_base64: str | None = None, filename: str | None = None,
                           min_seconds: float = 10.0, max_seconds: float = 60.0,
                           silence_db: float | None = None, output_dir: str | None = None,
                           output_format: str | None = None, return_audio: bool = False) -> dict:
    return await _toolset.audio_split(
        audio_path=audio_path, audio_url=audio_url, audio_base64=audio_base64,
        filename=filename, min_seconds=min_seconds, max_seconds=max_seconds,
        silence_db=silence_db, output_dir=output_dir, output_format=output_format,
        return_audio=return_audio)


@server.tool(name="audio_tighten", description=_d(T.AUDIO_TIGHTEN_SCHEMA))
@mcp_errors
async def audio_tighten_tool(audio_path: str | None = None, audio_url: str | None = None,
                             audio_base64: str | None = None, filename: str | None = None,
                             min_pause: float = 1.0, keep_pause: float = 0.5,
                             edges: bool = True, silence_db: float | None = None,
                             dry_run: bool = False, output_format: str | None = None,
                             output_path: str | None = None, return_audio: bool = False) -> dict:
    return await _toolset.audio_tighten(
        audio_path=audio_path, audio_url=audio_url, audio_base64=audio_base64,
        filename=filename, min_pause=min_pause, keep_pause=keep_pause, edges=edges,
        silence_db=silence_db, dry_run=dry_run, output_format=output_format,
        output_path=output_path, return_audio=return_audio)


@server.tool(name="audio_spectrogram", description=_d(T.AUDIO_SPECTROGRAM_SCHEMA))
@mcp_errors
async def audio_spectrogram_tool(audio_path: str | None = None, audio_url: str | None = None,
                                 audio_base64: str | None = None, filename: str | None = None,
                                 start: float | None = None, duration: float | None = None,
                                 width: int = 1200, height: int = 400, min_freq: float = 50.0,
                                 max_freq: float = 8000.0, freq_scale: str = "log",
                                 dynamic_range: float = 80.0,
                                 output_path: str | None = None) -> dict:
    return await _toolset.audio_spectrogram(
        audio_path=audio_path, audio_url=audio_url, audio_base64=audio_base64,
        filename=filename, start=start, duration=duration, width=width, height=height,
        min_freq=min_freq, max_freq=max_freq, freq_scale=freq_scale,
        dynamic_range=dynamic_range, output_path=output_path)


@server.tool(name="audio_tones", description=_d(T.AUDIO_TONES_SCHEMA))
@mcp_errors
async def audio_tones_tool(audio_path: str | None = None, audio_url: str | None = None,
                           audio_base64: str | None = None, filename: str | None = None,
                           start: float | None = None, duration: float | None = None,
                           detect: list[str] | None = None) -> dict:
    return await _toolset.audio_tones(
        audio_path=audio_path, audio_url=audio_url, audio_base64=audio_base64,
        filename=filename, start=start, duration=duration, detect=detect)


@server.tool(name="audio_speak", description=_d(T.AUDIO_SPEAK_SCHEMA))
@mcp_errors
async def audio_speak_tool(text: str | None = None, voice: str | None = None,
                           speed: int | None = None, pitch: int | None = None,
                           ssml: bool = False, list_voices: bool = False,
                           language: str | None = None, output_format: str | None = None,
                           output_path: str | None = None, return_audio: bool = False) -> dict:
    return await _toolset.audio_speak(
        text=text, voice=voice, speed=speed, pitch=pitch, ssml=ssml,
        list_voices=list_voices, language=language, output_format=output_format,
        output_path=output_path, return_audio=return_audio)


@server.tool(name="audio_sonify", description=_d(T.AUDIO_SONIFY_SCHEMA))
@mcp_errors
async def audio_sonify_tool(values: list[float | None] | None = None,
                            series: list[dict] | None = None, duration: float | None = None,
                            min_freq: float = 220.0, max_freq: float = 880.0,
                            scale: str = "musical", waveform: str = "sine",
                            min_value: float | None = None, max_value: float | None = None,
                            output_format: str | None = None, output_path: str | None = None,
                            return_audio: bool = False) -> dict:
    return await _toolset.audio_sonify(
        values=values, series=series, duration=duration, min_freq=min_freq,
        max_freq=max_freq, scale=scale, waveform=waveform, min_value=min_value,
        max_value=max_value, output_format=output_format, output_path=output_path,
        return_audio=return_audio)


@server.tool(name="audio_watch", description=_d(T.AUDIO_WATCH_SCHEMA))
@mcp_errors
async def audio_watch_tool(action: str, stream_url: str | None = None,
                           audio_path: str | None = None, watch_id: str | None = None,
                           cursor: int = 0, max_events: int = 100, dead_air_s: float = 5.0,
                           silence_db: float = -50.0, spike_db: float = 15.0,
                           detect_tones: bool = True, max_seconds: float = 3600.0,
                           realtime: bool = False) -> dict:
    return await _toolset.audio_watch(
        action=action, stream_url=stream_url, audio_path=audio_path, watch_id=watch_id,
        cursor=cursor, max_events=max_events, dead_air_s=dead_air_s, silence_db=silence_db,
        spike_db=spike_db, detect_tones=detect_tones, max_seconds=max_seconds,
        realtime=realtime)


def main() -> None:
    parser = argparse.ArgumentParser(description="HiraraAudio MCP server")
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

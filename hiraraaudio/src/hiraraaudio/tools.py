"""The tool layer: schemas and JSON-ready results.

Both front ends (HTTP service and MCP server) call into here, so the two can
never drift apart in behaviour — only in transport.

Fourteen tools, all signal processing on FFmpeg + NumPy, no ML models:
audio_info, audio_profile, audio_check, audio_fix, audio_compare, audio_find,
audio_fingerprint, audio_split, audio_tighten, audio_spectrogram,
audio_tones, audio_speak, audio_sonify, audio_watch.
"""

from __future__ import annotations

from hirara_core.policy import tool_permission, visible_schemas

import asyncio
import base64
import logging
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from . import analysis, dsp, editing, matching, quality, sonify, speech, tones, visual
from .config import AudioConfig
from .errors import AudioError
from .media import OUTPUT_FORMATS, encode_array, format_from_path, probe
from .output import check_output_dir, check_output_path, deliver
from .sources import opened
from .watch import Settings, WatchManager

log = logging.getLogger(__name__)


# --- schemas --------------------------------------------------------------------

def _source_props(prefix: str = "audio", what: str = "audio/video file") -> dict:
    return {
        f"{prefix}_path": {
            "type": "string",
            "description": f"Local path to the {what} (if the server allows local paths).",
        },
        f"{prefix}_url": {
            "type": "string",
            "description": f"http(s) URL of the {what} (if the server allows URL fetch).",
        },
        f"{prefix}_base64": {
            "type": "string",
            "description": f"Base64-encoded {what} bytes. Prefer a path for large files.",
        },
    }


_SOURCE = {**_source_props(), "filename": {
    "type": "string", "description": "Original file name, helps decode audio_base64."}}
_SPAN = {
    "start": {"type": "number", "minimum": 0, "description": "Analyse from this second."},
    "duration": {"type": "number", "exclusiveMinimum": 0,
                 "description": "Analyse this many seconds."},
}
_OUTPUT = {
    "output_format": {"type": "string", "enum": ["wav", "flac", "mp3", "ogg", "opus", "m4a"],
                      "description": "Output format (default: from output_path, else wav)."},
    "output_path": {"type": "string",
                    "description": "Write the result here (server must allow output paths). "
                                   "Without it the result is returned as audio_base64."},
    "return_audio": {"type": "boolean",
                     "description": "Also return audio_base64 when output_path is set."},
}
_SOURCE_HINT = " Provide one source: audio_path, audio_url or audio_base64."


def _schema(name: str, description: str, props: dict, required: list[str] | None = None) -> dict:
    schema: dict = {"type": "object", "properties": props, "additionalProperties": False}
    if required:
        schema["required"] = required
    return {"name": name, "description": description, "input_schema": schema}


AUDIO_INFO_SCHEMA = _schema(
    "audio_info",
    "Container and stream facts for an audio or video file without decoding it: "
    "duration, codec, sample rate, channels, bit rate, tags and chapters." + _SOURCE_HINT,
    dict(_SOURCE),
)

AUDIO_PROFILE_SCHEMA = _schema(
    "audio_profile",
    "Describe a recording you cannot listen to. Returns a short timeline of "
    "speech / music / noise / silence with levels, integrated loudness and true "
    "peak, and events worth knowing about (long silences, clipping, sudden level "
    "jumps, mains hum), plus a ready-to-read text summary.\n\nUse it first on any "
    "unfamiliar audio, before deciding to transcribe, edit, split or fix it. Labels "
    "are signal-feature estimates, not a trained classifier." + _SOURCE_HINT,
    {**_SOURCE, **_SPAN,
     "max_segments": {"type": "integer", "minimum": 1, "maximum": 500,
                      "description": "Most timeline entries to return (default 40)."},
     "silence_db": {"type": "number", "description": "Silence threshold in dBFS (default adaptive)."},
     "long_silence_s": {"type": "number", "exclusiveMinimum": 0,
                        "description": "Report silences at least this long (default 3)."}},
)

AUDIO_CHECK_SCHEMA = _schema(
    "audio_check",
    "Judge audio against a delivery spec and say exactly what fails and how to fix "
    "it. Presets: podcast (-16 LUFS, -1 dBTP), broadcast (EBU R128, -23 LUFS), "
    "music_streaming (-14 LUFS), audiobook (ACX: RMS -23..-18 dBFS, peak -3 dBFS, "
    "noise floor -60 dBFS, room tone), stt_ready (fit for speech-to-text). Each "
    "failure carries audio_fix arguments; suggested_fix collects them." + _SOURCE_HINT,
    {**_SOURCE, **_SPAN,
     "preset": {"type": "string", "enum": list(quality.PRESETS),
                "description": "Spec to check against (default podcast)."}},
)

AUDIO_FIX_SCHEMA = _schema(
    "audio_fix",
    "Repair what audio_check reports, then re-check the result. Two-pass loudness "
    "normalisation to a target (linear gain where possible), true-peak limit, DC "
    "removal, mains hum notch (auto-detects 50/60 Hz), rumble high-pass and "
    "optional spectral noise reduction. Pass audio_check's suggested_fix as "
    "arguments, or a preset. Clipping cannot be undone here." + _SOURCE_HINT,
    {**_SOURCE,
     "preset": {"type": "string", "enum": list(quality.PRESETS),
                "description": "Take targets from this preset and re-check against it."},
     "target_lufs": {"type": "number", "description": "Integrated loudness target."},
     "max_true_peak": {"type": "number", "description": "True-peak ceiling in dBTP."},
     "remove_dc": {"type": "boolean", "description": "Remove DC offset (default: if present)."},
     "dehum": {"type": "string", "enum": ["auto", "50", "60", "off"],
               "description": "Notch mains hum (default auto: only if detected)."},
     "highpass_hz": {"type": "number", "minimum": 10, "maximum": 300,
                     "description": "High-pass cutoff to remove rumble."},
     "denoise": {"type": "boolean", "description": "Apply spectral noise reduction."},
     "sample_rate": {"type": "integer", "description": "Output sample rate (default: input's)."},
     **_OUTPUT},
)

AUDIO_COMPARE_SCHEMA = _schema(
    "audio_compare",
    "Compare two recordings and say what changed: whether b contains the same "
    "material as a, the time offset, which spans were removed, inserted, moved or "
    "changed, where silence was shortened, and level changes. Use it to verify an "
    "edit you made but cannot hear, or to diff two versions of a file. Provide one "
    "source for each of a and b.",
    {**_source_props("a", "original file"), **_source_props("b", "edited / second file")},
)

AUDIO_FIND_SCHEMA = _schema(
    "audio_find",
    "Find every place a short reference clip (a jingle, ad, intro, sound effect, "
    "or a span of the same file) occurs in a longer recording. Robust to level "
    "changes and re-encoding. Give the clip as clip_path/clip_url/clip_base64, or "
    "as clip_start/clip_end within the recording itself." + _SOURCE_HINT,
    {**_SOURCE, **_source_props("clip", "reference clip"),
     "clip_start": {"type": "number", "minimum": 0,
                    "description": "Clip start (seconds) within the recording itself."},
     "clip_end": {"type": "number", "exclusiveMinimum": 0,
                  "description": "Clip end (seconds) within the recording itself."},
     "threshold": {"type": "number", "minimum": 0.3, "maximum": 1.0,
                   "description": "Match score needed, 0.3..1 (default 0.8)."},
     "max_matches": {"type": "integer", "minimum": 1, "maximum": 500,
                     "description": "Most matches to return (default 50)."}},
)

AUDIO_FINGERPRINT_SCHEMA = _schema(
    "audio_fingerprint",
    "Find duplicates and shared material across many files with acoustic "
    "fingerprints: which files are the same recording (even re-encoded or at a "
    "different level), which contain another, and at what offset.",
    {"audio_paths": {"type": "array", "items": {"type": "string"},
                     "description": "Local file paths."},
     "audio_urls": {"type": "array", "items": {"type": "string"},
                    "description": "http(s) URLs (if the server allows URL fetch)."}},
)

AUDIO_SPLIT_SCHEMA = _schema(
    "audio_split",
    "Plan cut points at natural pauses so every piece is between min_seconds and "
    "max_seconds long, never cutting through a word when a pause exists (e.g. "
    "chunks for transcribe). Returns the plan; writes the pieces to output_dir, or "
    "returns them as base64 with return_audio." + _SOURCE_HINT,
    {**_SOURCE,
     "min_seconds": {"type": "number", "exclusiveMinimum": 0, "description": "Default 10."},
     "max_seconds": {"type": "number", "exclusiveMinimum": 0, "description": "Default 60."},
     "silence_db": {"type": "number", "description": "Silence threshold (default adaptive)."},
     "output_dir": {"type": "string", "description": "Write pieces here (server must allow)."},
     "output_format": _OUTPUT["output_format"],
     "return_audio": {"type": "boolean", "description": "Return pieces as base64."}},
)

AUDIO_TIGHTEN_SCHEMA = _schema(
    "audio_tighten",
    "Shorten long pauses (dead air) without touching speech: every pause longer "
    "than min_pause is cut down to keep_pause, with short fades so joins do not "
    "click. dry_run returns the plan only. The result is re-measured so you can "
    "see the new length and longest remaining pause." + _SOURCE_HINT,
    {**_SOURCE,
     "min_pause": {"type": "number", "exclusiveMinimum": 0,
                   "description": "Only pauses longer than this (default 1.0 s)."},
     "keep_pause": {"type": "number", "minimum": 0,
                    "description": "Pause length to leave (default 0.5 s)."},
     "edges": {"type": "boolean",
               "description": "Also trim leading/trailing silence (default true)."},
     "silence_db": {"type": "number", "description": "Silence threshold (default adaptive)."},
     "dry_run": {"type": "boolean", "description": "Plan only, write nothing."},
     **_OUTPUT},
)

AUDIO_SPECTROGRAM_SCHEMA = _schema(
    "audio_spectrogram",
    "Render a labelled spectrogram PNG (time and frequency axes) for a "
    "vision-capable model to inspect: hum lines, hiss, dropouts, clipping "
    "splatter, where speech or music sits. Returns png_base64, the plot geometry "
    "for mapping pixels to time/frequency, and any steady tones." + _SOURCE_HINT,
    {**_SOURCE, **_SPAN,
     "width": {"type": "integer", "minimum": 64, "maximum": 4000, "description": "Default 1200."},
     "height": {"type": "integer", "minimum": 64, "maximum": 2000, "description": "Default 400."},
     "min_freq": {"type": "number", "description": "Lowest frequency shown (default 50)."},
     "max_freq": {"type": "number", "description": "Highest frequency shown (default 8000)."},
     "freq_scale": {"type": "string", "enum": ["log", "linear"], "description": "Default log."},
     "dynamic_range": {"type": "number", "minimum": 20, "maximum": 140,
                       "description": "dB range shown (default 80)."},
     "output_path": {"type": "string", "description": "Also write the PNG here."}},
)

AUDIO_TONES_SCHEMA = _schema(
    "audio_tones",
    "Detect DTMF key presses (phone digits), beeps and steady test tones with "
    "their frequency and timing, and 50/60 Hz mains hum. Useful on call "
    "recordings, voicemail, broadcast and test signals." + _SOURCE_HINT,
    {**_SOURCE, **_SPAN,
     "detect": {"type": "array", "items": {"type": "string", "enum": ["dtmf", "beeps", "hum"]},
                "description": "What to look for (default all)."}},
)

AUDIO_SPEAK_SCHEMA = _schema(
    "audio_speak",
    "Lightweight text-to-speech with eSpeak NG: 100+ languages, instant on CPU, "
    "no model download. Sounds synthetic; good for notifications, accessibility "
    "read-outs, pronunciation checks and test audio. Set list_voices=true to see "
    "voices (optionally for one language).",
    {"text": {"type": "string", "description": "Text to speak (or SSML with ssml=true)."},
     "voice": {"type": "string", "description": "Voice / language code, e.g. en-us, de, fr+f3."},
     "speed": {"type": "integer", "minimum": 80, "maximum": 450,
               "description": "Words per minute (default 175)."},
     "pitch": {"type": "integer", "minimum": 0, "maximum": 99, "description": "Default 50."},
     "ssml": {"type": "boolean", "description": "Treat text as SSML."},
     "list_voices": {"type": "boolean", "description": "Return available voices instead."},
     "language": {"type": "string", "description": "Filter list_voices by language."},
     **_OUTPUT},
)

AUDIO_SONIFY_SCHEMA = _schema(
    "audio_sonify",
    "Turn numbers into sound so the shape of the data can be heard: each value "
    "becomes a short tone whose pitch follows the value, panned left to right; "
    "nulls are rests. Pass values for one series or series for several (played "
    "one after another).",
    {"values": {"type": "array", "items": {"type": ["number", "null"]},
                "description": "One data series."},
     "series": {"type": "array", "items": {"type": "object", "properties": {
         "name": {"type": "string"},
         "values": {"type": "array", "items": {"type": ["number", "null"]}}}},
         "description": "Several named series."},
     "duration": {"type": "number", "description": "Total seconds (default ~0.12 s per point)."},
     "min_freq": {"type": "number", "description": "Pitch of the lowest value (default 220)."},
     "max_freq": {"type": "number", "description": "Pitch of the highest value (default 880)."},
     "scale": {"type": "string", "enum": ["musical", "linear"], "description": "Default musical."},
     "waveform": {"type": "string", "enum": ["sine", "triangle", "square"],
                  "description": "Default sine."},
     "min_value": {"type": "number", "description": "Value mapped to min_freq (default data min)."},
     "max_value": {"type": "number", "description": "Value mapped to max_freq (default data max)."},
     **_OUTPUT},
)

AUDIO_WATCH_SCHEMA = _schema(
    "audio_watch",
    "Monitor a live audio stream (or a file) in the background and collect events: "
    "dead_air, audio_resumed, level_spike, clipping, beep/tone, dtmf, stalled, "
    "stream_ended, stream_error. action=start returns a watch_id; poll with the "
    "returned cursor to get only new events; stop when done; list shows watchers.",
    {"action": {"type": "string", "enum": ["start", "poll", "stop", "list"]},
     "stream_url": {"type": "string", "description": "http(s) stream to monitor (start)."},
     "audio_path": {"type": "string", "description": "Local file to monitor instead (start)."},
     "watch_id": {"type": "string", "description": "Watcher to poll or stop."},
     "cursor": {"type": "integer", "minimum": 0,
                "description": "Return events after this sequence number (poll)."},
     "max_events": {"type": "integer", "minimum": 1, "maximum": 1000,
                    "description": "Most events per poll (default 100)."},
     "dead_air_s": {"type": "number", "description": "Silence length that counts as dead air (default 5)."},
     "silence_db": {"type": "number", "description": "Level below which it is silence (default -50)."},
     "spike_db": {"type": "number", "description": "Jump above recent level that counts as a spike (default 15)."},
     "detect_tones": {"type": "boolean", "description": "Report beeps, tones and DTMF (default true)."},
     "max_seconds": {"type": "number", "description": "Stop after this many seconds (default 3600)."},
     "realtime": {"type": "boolean", "description": "Play a file at real speed (default false)."}},
    ["action"],
)

SCHEMAS = [
    AUDIO_INFO_SCHEMA, AUDIO_PROFILE_SCHEMA, AUDIO_CHECK_SCHEMA, AUDIO_FIX_SCHEMA,
    AUDIO_COMPARE_SCHEMA, AUDIO_FIND_SCHEMA, AUDIO_FINGERPRINT_SCHEMA, AUDIO_SPLIT_SCHEMA,
    AUDIO_TIGHTEN_SCHEMA, AUDIO_SPECTROGRAM_SCHEMA, AUDIO_TONES_SCHEMA, AUDIO_SPEAK_SCHEMA,
    AUDIO_SONIFY_SCHEMA, AUDIO_WATCH_SCHEMA,
]
TOOL_NAMES = tuple(s["name"] for s in SCHEMAS)


# --- helpers ----------------------------------------------------------------------

_SOURCE_KEYS = ("path", "url", "base64", "bytes")


def _only(kw: dict, *prefixes: str) -> None:
    """Reject arguments that are not a source for these prefixes.

    Source fields arrive through ``**kw``; without this a misspelt argument
    (``audo_path``) would be silently ignored instead of reported.
    """
    allowed = {f"{p}_{k}" for p in prefixes for k in _SOURCE_KEYS}
    if "audio" in prefixes:
        allowed.add("filename")
    extra = sorted(set(kw) - allowed)
    if extra:
        raise AudioError(f"unexpected argument(s): {', '.join(extra)}")


def _src(kw: dict, prefix: str = "audio") -> dict:
    return {
        "path": kw.get(f"{prefix}_path"),
        "url": kw.get(f"{prefix}_url"),
        "data_base64": kw.get(f"{prefix}_base64"),
        "filename": kw.get("filename") if prefix == "audio" else None,
        "data": kw.get(f"{prefix}_bytes"),
        "prefix": prefix,
    }


def _span(start, duration) -> tuple[float | None, float | None]:
    if start is not None and start < 0:
        raise AudioError("start must be >= 0")
    if duration is not None and duration <= 0:
        raise AudioError("duration must be > 0")
    return start, duration


def _temp(fmt: str) -> Path:
    return Path(tempfile.mkstemp(prefix="hiraraaudio-", suffix=f".{fmt}")[1])


@dataclass
class Toolset:
    """The audio tools sharing one config and one stream-watch manager."""

    config: AudioConfig
    watches: WatchManager = field(init=False)

    def __post_init__(self) -> None:
        self.watches = WatchManager(self.config)

    @classmethod
    def from_env(cls) -> "Toolset":
        return cls(config=AudioConfig.from_env())

    @visible_schemas
    def schemas(self) -> list[dict]:
        return list(SCHEMAS)

    def health(self) -> dict:
        import shutil

        return {
            "status": "ok" if shutil.which(self.config.ffmpeg) else "degraded",
            "version": "0.2.0",
            "tools": list(TOOL_NAMES),
            "ffmpeg": shutil.which(self.config.ffmpeg),
            "ffprobe": shutil.which(self.config.ffprobe),
            "espeak": shutil.which(self.config.espeak),
            "allow_local_path": self.config.allow_local_path,
            "allow_url_fetch": self.config.allow_url_fetch,
            "allow_output_path": self.config.allow_output_path,
            "max_bytes": self.config.max_bytes,
            "max_duration": self.config.max_duration,
        }

    async def _guard(self, name: str, fn, **fields) -> dict:
        """Run ``fn`` and turn any failure into the tool's error envelope."""
        try:
            return await fn()
        except AudioError as exc:
            return {**fields, "error": str(exc)}
        except Exception as exc:  # noqa: BLE001 — agent gets a body, not a 500
            log.exception("%s failed", name)
            return {**fields, "error": f"{name} failed: {exc}"}

    # --- audio_info -------------------------------------------------------------------

    @tool_permission('audio_info')
    async def audio_info(self, **kw) -> dict:
        async def run():
            _only(kw, "audio")
            async with opened(self.config, **_src(kw)) as src:
                info = await asyncio.to_thread(probe, src.path, self.config)
                return analysis.info_result(info, src.label)

        return await self._guard("audio_info", run, source=None, summary=None)

    # --- audio_profile ----------------------------------------------------------------

    @tool_permission('audio_profile')
    async def audio_profile(self, *, start: float | None = None, duration: float | None = None,
                            max_segments: int = 40, silence_db: float | None = None,
                            long_silence_s: float = 3.0, **kw) -> dict:
        async def run():
            _only(kw, "audio")
            _span(start, duration)
            async with opened(self.config, **_src(kw)) as src:
                m = await asyncio.to_thread(analysis.measure, src.path, self.config, start=start,
                                            duration=duration, silence_db=silence_db)
                return analysis.profile_result(m, src.label, max_segments=max(1, max_segments),
                                               long_silence=long_silence_s)

        return await self._guard("audio_profile", run, source=None, timeline=[], events=[],
                                 text=None)

    # --- audio_check / audio_fix --------------------------------------------------------

    @tool_permission('audio_check')
    async def audio_check(self, *, preset: str | None = "podcast", start: float | None = None,
                          duration: float | None = None, **kw) -> dict:
        async def run():
            _only(kw, "audio")
            _span(start, duration)
            spec = quality.get_preset(preset)
            async with opened(self.config, **_src(kw)) as src:
                m = await asyncio.to_thread(analysis.measure, src.path, self.config,
                                            start=start, duration=duration)
                return quality.check_result(m, spec, src.label)

        return await self._guard("audio_check", run, source=None, preset=preset, passed=None,
                                 checks=[], text=None)

    @tool_permission('audio_fix')
    async def audio_fix(self, *, preset: str | None = None, target_lufs: float | None = None,
                        max_true_peak: float | None = None, remove_dc: bool | None = None,
                        dehum: str | None = "auto", highpass_hz: float | None = None,
                        denoise: bool = False, sample_rate: int | None = None,
                        output_format: str | None = None, output_path: str | None = None,
                        return_audio: bool = False, **kw) -> dict:
        async def run():
            _only(kw, "audio")
            spec = quality.get_preset(preset) if preset else None
            target = check_output_path(output_path, self.config)
            fmt = format_from_path(output_path, output_format)
            async with opened(self.config, **_src(kw)) as src:
                before = await asyncio.to_thread(analysis.measure, src.path, self.config)
                chain, steps = await asyncio.to_thread(
                    quality.build_fix, src.path, self.config, preset=spec,
                    target_lufs=target_lufs, max_true_peak=max_true_peak, remove_dc=remove_dc,
                    dehum=dehum, highpass_hz=highpass_hz, denoise=denoise, before=before)
                if not chain:
                    return {"source": src.label, "steps": [], "changed": False,
                            "text": "nothing to fix with these settings", "before": None,
                            "after": None, "output_path": None, "audio_base64": None,
                            "error": None}
                out = await asyncio.to_thread(quality.run_fix, src.path, self.config, fmt=fmt,
                                              sample_rate=sample_rate, chain=chain)
                try:
                    after = await asyncio.to_thread(analysis.measure, out, self.config)
                    check_spec = spec or quality.get_preset("podcast")
                    b = quality.check_result(before, check_spec, src.label)
                    a = quality.check_result(after, check_spec, "output")
                    delivered = deliver(out, target, self.config, inline=return_audio)
                finally:
                    out.unlink(missing_ok=True)
                return {
                    "source": src.label,
                    "steps": steps,
                    "changed": True,
                    "checked_against": check_spec.name,
                    "before": {"passed": b["passed"], "text": b["text"],
                               **(before.loud.as_dict() if before.loud else {})},
                    "after": {"passed": a["passed"], "text": a["text"],
                              **(after.loud.as_dict() if after.loud else {})},
                    "remaining": [c for c in a["checks"] if c["status"] != "pass"],
                    "format": fmt,
                    **delivered,
                    "text": "\n".join(["applied: " + "; ".join(steps),
                                       "before: " + b["text"], "after:  " + a["text"]]),
                    "error": None,
                }

        return await self._guard("audio_fix", run, source=None, steps=[], output_path=None,
                                 audio_base64=None)

    # --- matching --------------------------------------------------------------------------

    @tool_permission('audio_compare')
    async def audio_compare(self, **kw) -> dict:
        async def run():
            _only(kw, "a", "b")
            async with opened(self.config, **_src(kw, "a")) as a, \
                    opened(self.config, **_src(kw, "b")) as b:
                def work():
                    ia, ib = probe(a.path, self.config), probe(b.path, self.config)
                    ma = matching.match_features(a.path, self.config)
                    mb = matching.match_features(b.path, self.config)
                    fa = matching.file_fingerprint(a.path, self.config)
                    fb = matching.file_fingerprint(b.path, self.config)
                    return ia, ib, matching.compare(ma, mb, fa, fb)

                ia, ib, result = await asyncio.to_thread(work)
                lines = [f"a {dsp.fmt_time(ia.duration or 0)}, b {dsp.fmt_time(ib.duration or 0)}"]
                if result["similarity"] is None:
                    lines.append("a has no non-silent content to compare")
                elif not result["aligned"]:
                    lines.append("no shared material found")
                else:
                    lines.append(f"{result['similarity'] * 100:.0f}% of a's content found in b"
                                 + (f", offset {result['offset_s']:+.2f}s"
                                    if result["offset_s"] else ""))
                for c in result["changes"]:
                    lines.append(f"{c['type']} a {dsp.fmt_time(c['a_start'])}–"
                                 f"{dsp.fmt_time(c['a_end'])}: {c['detail']}")
                if result["aligned"] and not result["changes"]:
                    lines.append("no differences found")
                return {
                    "a": {"source": a.label, **ia.as_dict()},
                    "b": {"source": b.label, **ib.as_dict()},
                    **result,
                    "same_content": bool(result["aligned"]) and not [
                        c for c in result["changes"] if c["type"] != "level_changed"],
                    "text": "\n".join(lines),
                    "error": None,
                }

        return await self._guard("audio_compare", run, aligned=[], changes=[], text=None)

    @tool_permission('audio_find')
    async def audio_find(self, *, clip_start: float | None = None, clip_end: float | None = None,
                         threshold: float = 0.8, max_matches: int = 50, **kw) -> dict:
        async def run():
            _only(kw, "audio", "clip")
            if not 0.3 <= threshold <= 1.0:
                raise AudioError("threshold must be between 0.3 and 1")
            own_span = clip_start is not None or clip_end is not None
            has_clip = any(kw.get(k) for k in ("clip_path", "clip_url", "clip_base64", "clip_bytes"))
            if own_span and has_clip:
                raise AudioError("give a clip file or clip_start/clip_end, not both")
            if not own_span and not has_clip:
                raise AudioError("provide clip_path, clip_url, clip_base64, or clip_start/clip_end")
            async with opened(self.config, **_src(kw)) as hay:
                hay_mf = await asyncio.to_thread(matching.match_features, hay.path, self.config)
                if own_span:
                    lo = clip_start or 0.0
                    hi = clip_end if clip_end is not None else lo + 5.0
                    if hi - lo < 0.3 or hi - lo > 120:
                        raise AudioError("clip must be 0.3..120 seconds long")
                    a, b = int(lo / dsp.MATCH_S), int(hi / dsp.MATCH_S)
                    clip_mf = matching.MatchFeatures(hay_mf.feats[a:b], hay_mf.level_db[a:b], hi - lo)
                    clip_label = f"{dsp.fmt_time(lo)}–{dsp.fmt_time(hi)} of the recording"
                else:
                    async with opened(self.config, **_src(kw, "clip")) as clip:
                        clip_mf = await asyncio.to_thread(matching.match_features, clip.path,
                                                          self.config, duration=120.0)
                        clip_label = clip.label
                if clip_mf.frames < 30:
                    raise AudioError("clip is too short (needs at least 0.3 s)")
                matches = await asyncio.to_thread(matching.find_clip, hay_mf, clip_mf,
                                                  threshold=threshold, max_matches=max_matches)
                text = (f"{len(matches)} match(es) for {clip_label}: " + ", ".join(
                    f"{dsp.fmt_time(m['start'])} ({m['score']:.2f})" for m in matches)
                        if matches else f"no match for {clip_label} above {threshold}")
                return {"source": hay.label, "clip": clip_label,
                        "clip_duration": round(clip_mf.frames * dsp.MATCH_S, 2),
                        "matches": matches, "threshold": threshold, "text": text, "error": None}

        return await self._guard("audio_find", run, source=None, matches=[], text=None)

    @tool_permission('audio_fingerprint')
    async def audio_fingerprint(self, *, audio_paths: list[str] | None = None,
                                audio_urls: list[str] | None = None) -> dict:
        async def run():
            items = [("path", p) for p in (audio_paths or [])] + [("url", u) for u in (audio_urls or [])]
            if len(items) < 2:
                raise AudioError("provide at least two files in audio_paths / audio_urls")
            if len(items) > self.config.max_fingerprint_sources:
                raise AudioError(
                    f"at most {self.config.max_fingerprint_sources} files (HA_MAX_FINGERPRINT_SOURCES)")
            files, prints = [], []
            for kind, value in items:
                async with opened(self.config, **{kind: value}) as src:
                    try:
                        fp = await asyncio.to_thread(matching.file_fingerprint, src.path, self.config)
                    except AudioError as exc:
                        files.append({"source": value, "error": str(exc)})
                        prints.append(None)
                        continue
                    files.append({"source": value, "duration": round(fp.duration, 2),
                                  "hashes": fp.count, "error": None})
                    prints.append(fp)
            matches = []
            for i in range(len(prints)):
                for j in range(i + 1, len(prints)):
                    if prints[i] is None or prints[j] is None:
                        continue
                    rel = matching.relation(prints[i], prints[j])
                    if rel:
                        matches.append({"a": files[i]["source"], "b": files[j]["source"], **rel})
            groups = _duplicate_groups(files, matches)
            lines = [f"{len(files)} files, {len(matches)} related pair(s)"]
            for m in matches:
                lines.append(f"{m['relation']}: {m['a']} ~ {m['b']} (offset {m['offset_s']:+.2f}s,"
                             f" score {m['score']})")
            return {"files": files, "matches": matches, "duplicate_groups": groups,
                    "text": "\n".join(lines), "error": None}

        return await self._guard("audio_fingerprint", run, files=[], matches=[], text=None)

    # --- editing --------------------------------------------------------------------------

    @tool_permission('audio_split')
    async def audio_split(self, *, min_seconds: float = 10.0, max_seconds: float = 60.0,
                          silence_db: float | None = None, output_dir: str | None = None,
                          output_format: str | None = None, return_audio: bool = False,
                          **kw) -> dict:
        async def run():
            _only(kw, "audio")
            out_dir = check_output_dir(output_dir, self.config)
            async with opened(self.config, **_src(kw)) as src:
                suffix = Path(src.label).suffix.lstrip(".").lower()
                fmt = format_from_path(None, output_format,
                                       default=suffix if suffix in OUTPUT_FORMATS else "wav")

                def work():
                    f = dsp.analyse(src.path, self.config, hum=False)
                    thr = dsp.silence_threshold(f, silence_db)
                    return f, editing.plan_split(f, thr, min_s=min_seconds, max_s=max_seconds)

                f, segments = await asyncio.to_thread(work)
                files: list[str] = []
                if out_dir is not None:
                    stem = Path(src.label).stem or "part"
                    files = await asyncio.to_thread(editing.write_segments, src.path, segments,
                                                    out_dir, stem, fmt, self.config)
                    for seg, path in zip(segments, files):
                        seg["output_path"] = path
                if return_audio:
                    with tempfile.TemporaryDirectory() as tmp:
                        written = await asyncio.to_thread(editing.write_segments, src.path,
                                                          segments, Path(tmp), "part", fmt,
                                                          self.config)
                        total = sum(Path(p).stat().st_size for p in written)
                        if total > self.config.max_output_bytes:
                            raise AudioError(
                                f"pieces total {total} bytes, over HA_MAX_OUTPUT_BYTES; "
                                "use output_dir instead")
                        for seg, path in zip(segments, written):
                            seg["audio_base64"] = base64.b64encode(Path(path).read_bytes()).decode()
                forced = sum(1 for s in segments if s["cut_after"] == "forced")
                lines = [f"{len(segments)} pieces from {dsp.fmt_time(f.duration)}"
                         + (f"; {forced} cut(s) had no pause in range" if forced else "")]
                for s in segments[:50]:
                    lines.append(f"#{s['index']} {dsp.fmt_time(s['start'])}–{dsp.fmt_time(s['end'])}"
                                 f" ({s['duration']:.1f}s)")
                return {"source": src.label, "duration": round(f.duration, 2),
                        "segments": segments, "format": fmt, "output_dir": str(out_dir) if out_dir else None,
                        "files": files, "text": "\n".join(lines), "truncated": f.truncated,
                        "error": None}

        return await self._guard("audio_split", run, source=None, segments=[], text=None)

    @tool_permission('audio_tighten')
    async def audio_tighten(self, *, min_pause: float = 1.0, keep_pause: float = 0.5,
                            edges: bool = True, silence_db: float | None = None,
                            dry_run: bool = False, output_format: str | None = None,
                            output_path: str | None = None, return_audio: bool = False,
                            **kw) -> dict:
        async def run():
            _only(kw, "audio")
            target = None if dry_run else check_output_path(output_path, self.config)
            fmt = format_from_path(output_path, output_format)
            async with opened(self.config, **_src(kw)) as src:
                def plan_it():
                    info = probe(src.path, self.config)
                    f = dsp.analyse(src.path, self.config, hum=False)
                    thr = dsp.silence_threshold(f, silence_db)
                    plan = editing.plan_tighten(f, thr, min_pause=min_pause,
                                                keep_pause=keep_pause, edges=edges)
                    return info, f, thr, plan

                info, f, thr, plan = await asyncio.to_thread(plan_it)
                removed = sum(p["remove"][1] - p["remove"][0] for p in plan)
                result = {
                    "source": src.label,
                    "duration": round(f.duration, 2),
                    "planned_duration": round(f.duration - removed, 2),
                    "removed_s": round(removed, 2),
                    "pauses": plan,
                    "silence_threshold_db": round(thr, 1),
                    "dry_run": dry_run,
                    "output_path": None,
                    "audio_base64": None,
                    "error": None,
                }
                summary = (f"{len(plan)} pause(s) shortened, {removed:.1f}s removed: "
                           f"{dsp.fmt_time(f.duration)} -> {dsp.fmt_time(f.duration - removed)}")
                if dry_run or not plan:
                    result["text"] = summary if plan else "no pauses longer than min_pause"
                    return result
                if f.truncated:
                    raise AudioError("file is longer than HA_MAX_DURATION; tighten it in parts")
                keep = editing.keep_intervals(plan, f.duration)
                out = await asyncio.to_thread(
                    editing.render_keep, src.path, self.config, keep,
                    sample_rate=info.sample_rate or 44100, channels=info.channels or 1, fmt=fmt)
                try:
                    def verify():
                        g = dsp.analyse(out, self.config, hum=False)
                        longest = max((b - a for a, b in dsp.silences(g, thr, 0.05)
                                       if a > 0 and b < g.duration), default=0.0)
                        return g.duration, longest

                    new_len, longest = await asyncio.to_thread(verify)
                    delivered = deliver(out, target, self.config, inline=return_audio)
                finally:
                    out.unlink(missing_ok=True)
                result.update(delivered)
                result["format"] = fmt
                result["verified"] = {"duration": round(new_len, 2),
                                      "longest_inner_pause_s": round(longest, 2)}
                result["text"] = (summary + f"; output {dsp.fmt_time(new_len)}, longest pause "
                                  f"now {longest:.2f}s")
                return result

        return await self._guard("audio_tighten", run, source=None, pauses=[], output_path=None,
                                 audio_base64=None)

    # --- visual and tones ------------------------------------------------------------------

    @tool_permission('audio_spectrogram')
    async def audio_spectrogram(self, *, start: float | None = None, duration: float | None = None,
                                width: int = 1200, height: int = 400, min_freq: float = 50.0,
                                max_freq: float = 8000.0, freq_scale: str = "log",
                                dynamic_range: float = 80.0, output_path: str | None = None,
                                **kw) -> dict:
        async def run():
            _only(kw, "audio")
            _span(start, duration)
            if freq_scale not in ("log", "linear"):
                raise AudioError("freq_scale must be log or linear")
            if not 0 < min_freq < max_freq:
                raise AudioError("need 0 < min_freq < max_freq")
            target = None
            if output_path:
                target = check_output_path(output_path, self.config)
            async with opened(self.config, **_src(kw)) as src:
                def work():
                    info = probe(src.path, self.config)
                    return visual.spectrogram(
                        src.path, self.config, start=start, duration=duration,
                        width=max(64, min(width, 4000)), height=max(64, min(height, 2000)),
                        min_freq=min_freq, max_freq=max_freq, log_freq=freq_scale == "log",
                        dynamic_range=dynamic_range, total=info.duration)

                r = await asyncio.to_thread(work)
                png = r.pop("png")
                if target is not None:
                    target.write_bytes(png)
                tones_text = ", ".join(f"{t['freq_hz']:g} Hz" for t in r["steady_tones"])
                return {
                    "source": src.label,
                    **r,
                    "png_base64": base64.b64encode(png).decode("ascii"),
                    "bytes": len(png),
                    "output_path": str(target) if target else None,
                    "text": (f"spectrogram {dsp.fmt_time(r['time_range'][0])}–"
                             f"{dsp.fmt_time(r['time_range'][1])}, {r['freq_range'][0]:g}–"
                             f"{r['freq_range'][1]:g} Hz ({r['freq_scale']})"
                             + (f"; steady tones: {tones_text}" if tones_text else "")),
                    "error": None,
                }

        return await self._guard("audio_spectrogram", run, source=None, png_base64=None)

    @tool_permission('audio_tones')
    async def audio_tones(self, *, start: float | None = None, duration: float | None = None,
                          detect: list[str] | None = None, **kw) -> dict:
        async def run():
            _only(kw, "audio")
            _span(start, duration)
            wanted = set(detect or ["dtmf", "beeps", "hum"])
            unknown = wanted - {"dtmf", "beeps", "hum"}
            if unknown:
                raise AudioError(f"unknown detect value(s): {', '.join(sorted(unknown))}")
            async with opened(self.config, **_src(kw)) as src:
                r = await asyncio.to_thread(
                    lambda: tones.detect(dsp.mono_chunks(src.path, self.config, start=start,
                                                         duration=duration),
                                         offset=start or 0.0, dtmf="dtmf" in wanted,
                                         beeps="beeps" in wanted, hum="hum" in wanted))
                return {"source": src.label, **r,
                        "dtmf_sequence": "".join(k["digit"] for k in r["dtmf"]),
                        "text": tones.text(r), "error": None}

        return await self._guard("audio_tones", run, source=None, dtmf=[], tones=[], hum=None)

    # --- synthesis --------------------------------------------------------------------------

    @tool_permission('audio_speak')
    async def audio_speak(self, *, text: str | None = None, voice: str | None = None,
                          speed: int | None = None, pitch: int | None = None, ssml: bool = False,
                          list_voices: bool = False, language: str | None = None,
                          output_format: str | None = None, output_path: str | None = None,
                          return_audio: bool = False) -> dict:
        async def run():
            if list_voices:
                voices = await asyncio.to_thread(speech.list_voices, self.config, language)
                return {"voices": voices, "count": len(voices), "error": None}
            target = check_output_path(output_path, self.config)
            fmt = format_from_path(output_path, output_format)
            out, words = await asyncio.to_thread(speech.synthesize, text or "", self.config,
                                                 voice=voice, speed=speed, pitch=pitch,
                                                 ssml=ssml, fmt=fmt)
            try:
                length = (await asyncio.to_thread(probe, out, self.config)).duration
                delivered = deliver(out, target, self.config, inline=return_audio)
            finally:
                out.unlink(missing_ok=True)
            return {"voice": voice or "default", "words": words,
                    "duration": None if length is None else round(length, 2),
                    "format": fmt, **delivered, "error": None}

        return await self._guard("audio_speak", run, output_path=None, audio_base64=None)

    @tool_permission('audio_sonify')
    async def audio_sonify(self, *, values: list | None = None, series: list[dict] | None = None,
                           duration: float | None = None, min_freq: float = 220.0,
                           max_freq: float = 880.0, scale: str = "musical",
                           waveform: str = "sine", min_value: float | None = None,
                           max_value: float | None = None, output_format: str | None = None,
                           output_path: str | None = None, return_audio: bool = False) -> dict:
        async def run():
            if (values is None) == (series is None):
                raise AudioError("provide values or series, not both")
            data = series if series is not None else [{"name": "values", "values": values}]
            if not isinstance(data, list) or not data or len(data) > 20:
                raise AudioError("series must be a list of 1..20 series")
            target = check_output_path(output_path, self.config)
            fmt = format_from_path(output_path, output_format)
            audio, mapping = sonify.render(data, duration=duration, min_freq=min_freq,
                                           max_freq=max_freq, scale=scale, waveform=waveform,
                                           min_value=min_value, max_value=max_value)
            out = _temp(fmt)
            try:
                await asyncio.to_thread(encode_array, audio, 22050, out, fmt, self.config)
                delivered = deliver(out, target, self.config, inline=return_audio)
            finally:
                out.unlink(missing_ok=True)
            return {"duration": round(len(audio) / 22050, 2), "mapping": mapping, "format": fmt,
                    **delivered, "error": None}

        return await self._guard("audio_sonify", run, output_path=None, audio_base64=None)

    # --- audio_watch ------------------------------------------------------------------------

    @tool_permission('audio_watch')
    async def audio_watch(self, *, action: str, stream_url: str | None = None,
                          audio_path: str | None = None, watch_id: str | None = None,
                          cursor: int = 0, max_events: int = 100, dead_air_s: float = 5.0,
                          silence_db: float = -50.0, spike_db: float = 15.0,
                          detect_tones: bool = True, max_seconds: float = 3600.0,
                          realtime: bool = False) -> dict:
        async def run():
            limit = max(1, min(int(max_events), 1000))
            if action == "list":
                return {"watches": self.watches.list(), "error": None}
            if action == "start":
                settings = Settings(dead_air_s=dead_air_s, silence_db=silence_db,
                                    spike_db=spike_db, detect_tones=detect_tones,
                                    max_seconds=max_seconds, realtime=realtime)
                watch = self.watches.start(stream_url=stream_url, audio_path=audio_path,
                                           settings=settings)
                await asyncio.sleep(0.3)  # surface an immediate failure (404, bad file)
                return watch.snapshot(0, limit)
            if action == "poll":
                return self.watches.get(watch_id).snapshot(max(0, int(cursor)), limit)
            if action == "stop":
                watch = self.watches.stop(watch_id)
                return watch.snapshot(max(0, int(cursor)), limit)
            raise AudioError("action must be start, poll, stop or list")

        return await self._guard("audio_watch", run, watch_id=watch_id, status=None, events=[])


def _duplicate_groups(files: list[dict], matches: list[dict]) -> list[list[str]]:
    parent = {f["source"]: f["source"] for f in files}

    def root(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for m in matches:
        if m["relation"] == "duplicate":
            parent[root(m["a"])] = root(m["b"])
    groups: dict[str, list[str]] = {}
    for f in files:
        groups.setdefault(root(f["source"]), []).append(f["source"])
    return [g for g in groups.values() if len(g) > 1]


__all__ = [
    *[s["name"].upper() + "_SCHEMA" for s in SCHEMAS],
    "SCHEMAS",
    "Toolset",
    "TOOL_NAMES",
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


@visible_schemas
def tool_schemas() -> list[dict]:
    return list(SCHEMAS)

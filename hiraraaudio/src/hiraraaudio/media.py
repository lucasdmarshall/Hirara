"""FFmpeg / FFprobe plumbing: probe, streamed decode, loudness, encode.

All decoding is streamed in fixed-size chunks so a multi-hour file never sits
in memory as one array. Every process gets a wall-clock timeout, and stderr
goes to a temp file rather than a pipe so a chatty ffmpeg cannot deadlock us.
"""

from __future__ import annotations

import json
import re
import subprocess
import tempfile
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .config import AudioConfig
from .errors import AudioError


@dataclass(slots=True)
class MediaInfo:
    duration: float | None
    sample_rate: int | None
    channels: int | None
    channel_layout: str | None
    codec: str | None
    format: str | None
    bit_rate: int | None
    sample_format: str | None
    tags: dict = field(default_factory=dict)
    chapters: list = field(default_factory=list)
    stream_count: int = 0
    has_video: bool = False

    def as_dict(self) -> dict:
        return {
            "duration": _round(self.duration, 3),
            "sample_rate": self.sample_rate,
            "channels": self.channels,
            "channel_layout": self.channel_layout,
            "codec": self.codec,
            "format": self.format,
            "bit_rate": self.bit_rate,
            "sample_format": self.sample_format,
            "tags": dict(self.tags),
            "chapters": list(self.chapters),
            "stream_count": self.stream_count,
            "has_video": self.has_video,
        }


def _round(value: float | None, digits: int = 2) -> float | None:
    return None if value is None else round(float(value), digits)


def _int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float(value) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if np.isfinite(out) else None


def _missing(binary: str) -> AudioError:
    return AudioError(
        f"{binary} is not installed or not on PATH. Install FFmpeg "
        "(e.g. apt-get install ffmpeg) or set HA_FFMPEG / HA_FFPROBE."
    )


def run(args: list[str], config: AudioConfig, *, input_bytes: bytes | None = None) -> tuple[bytes, str]:
    """Run a process to completion. Returns (stdout, stderr text)."""
    try:
        proc = subprocess.run(
            args,
            input=input_bytes,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=config.timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise _missing(args[0]) from exc
    except subprocess.TimeoutExpired as exc:
        raise AudioError(f"{Path(args[0]).name} timed out after {config.timeout:.0f}s") from exc
    stderr = proc.stderr.decode("utf-8", errors="replace")
    if proc.returncode != 0:
        raise AudioError(_ffmpeg_error(args[0], stderr))
    return proc.stdout, stderr


def _ffmpeg_error(binary: str, stderr: str) -> str:
    lines = [line.strip() for line in stderr.strip().splitlines() if line.strip()]
    tail = lines[-1] if lines else "unknown error"
    return f"{Path(binary).name} failed: {tail}"


def probe(path: str | Path, config: AudioConfig) -> MediaInfo:
    out, _ = run(
        [
            config.ffprobe,
            "-v", "error",
            "-print_format", "json",
            "-show_format",
            "-show_streams",
            "-show_chapters",
            str(path),
        ],
        config,
    )
    try:
        data = json.loads(out or b"{}")
    except json.JSONDecodeError as exc:
        raise AudioError("ffprobe returned unreadable output") from exc

    streams = data.get("streams") or []
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if audio is None:
        raise AudioError("no audio stream found in the input")
    fmt = data.get("format") or {}

    duration = _float(audio.get("duration")) or _float(fmt.get("duration"))
    chapters = [
        {
            "title": (c.get("tags") or {}).get("title"),
            "start": _round(_float(c.get("start_time")), 3),
            "end": _round(_float(c.get("end_time")), 3),
        }
        for c in data.get("chapters") or []
    ]
    tags = {**(fmt.get("tags") or {}), **(audio.get("tags") or {})}
    return MediaInfo(
        duration=duration,
        sample_rate=_int(audio.get("sample_rate")),
        channels=_int(audio.get("channels")),
        channel_layout=audio.get("channel_layout"),
        codec=audio.get("codec_name"),
        format=fmt.get("format_name"),
        bit_rate=_int(audio.get("bit_rate")) or _int(fmt.get("bit_rate")),
        sample_format=audio.get("sample_fmt"),
        tags={str(k).lower(): str(v) for k, v in tags.items()},
        chapters=chapters,
        stream_count=len(streams),
        has_video=any(
            s.get("codec_type") == "video"
            and not (s.get("disposition") or {}).get("attached_pic")
            for s in streams
        ),
    )


@dataclass
class DecodeStats:
    """Filled in by :func:`decode_chunks` as it runs."""

    samples: int = 0
    truncated: bool = False


def decode_chunks(
    path: str | Path,
    config: AudioConfig,
    *,
    sample_rate: int | None = 16000,
    channels: int | None = 1,
    start: float | None = None,
    duration: float | None = None,
    chunk_seconds: float = 30.0,
    stats: DecodeStats | None = None,
    native_rate: int | None = None,
) -> Iterator[np.ndarray]:
    """Yield float32 chunks shaped ``(frames, channels)``.

    ``sample_rate`` / ``channels`` of ``None`` keep the source's own. When the
    rate is kept, pass ``native_rate`` so the chunk size and the duration cap
    are computed in real samples.
    """
    rate = sample_rate or native_rate
    if not rate:
        raise AudioError("decode needs a sample rate")
    limit = config.max_duration if duration is None else min(duration, config.max_duration)

    args = [config.ffmpeg, "-nostdin", "-v", "error"]
    if start:
        args += ["-ss", f"{max(0.0, start):.3f}"]
    args += ["-i", str(path), "-vn", "-sn", "-dn", "-t", f"{limit:.3f}"]
    if channels:
        args += ["-ac", str(channels)]
    if sample_rate:
        args += ["-ar", str(sample_rate)]
    args += ["-f", "f32le", "-acodec", "pcm_f32le", "-"]

    n_channels = channels
    if not n_channels:
        n_channels = _int(probe(path, config).channels) or 1

    frames_per_chunk = max(1, int(rate * chunk_seconds))
    bytes_per_chunk = frames_per_chunk * n_channels * 4
    max_frames = int(limit * rate)

    errlog = tempfile.TemporaryFile()
    try:
        proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=errlog)
    except FileNotFoundError as exc:
        errlog.close()
        raise _missing(config.ffmpeg) from exc

    deadline = time.monotonic() + config.timeout
    produced = 0
    try:
        assert proc.stdout is not None
        while True:
            if time.monotonic() > deadline:
                raise AudioError(f"ffmpeg timed out after {config.timeout:.0f}s")
            buf = _read_exact(proc.stdout, bytes_per_chunk)
            if not buf:
                break
            usable = len(buf) - len(buf) % (n_channels * 4)
            chunk = np.frombuffer(buf[:usable], dtype="<f4").reshape(-1, n_channels)
            produced += len(chunk)
            if stats is not None:
                stats.samples = produced
            yield chunk
            if len(buf) < bytes_per_chunk:
                break
        proc.wait(timeout=max(1.0, deadline - time.monotonic()))
        if proc.returncode not in (0, None):
            errlog.seek(0)
            raise AudioError(
                _ffmpeg_error(config.ffmpeg, errlog.read().decode("utf-8", "replace"))
            )
        if stats is not None and produced >= max_frames - rate * 0.05:
            # Hit the HA_MAX_DURATION cap, unless the caller asked for exactly
            # this span. A short file that ends naturally is not "truncated".
            stats.truncated = duration is None or duration > config.max_duration
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        if proc.stdout is not None:
            proc.stdout.close()
        errlog.close()


def _read_exact(stream, size: int) -> bytes:
    parts: list[bytes] = []
    remaining = size
    while remaining > 0:
        data = stream.read(remaining)
        if not data:
            break
        parts.append(data)
        remaining -= len(data)
    return b"".join(parts)


def decode(
    path: str | Path,
    config: AudioConfig,
    *,
    sample_rate: int = 16000,
    start: float | None = None,
    duration: float | None = None,
    stats: DecodeStats | None = None,
) -> np.ndarray:
    """Whole (bounded) mono signal as one float32 array."""
    chunks = [
        c[:, 0]
        for c in decode_chunks(
            path,
            config,
            sample_rate=sample_rate,
            channels=1,
            start=start,
            duration=duration,
            stats=stats,
        )
    ]
    if not chunks:
        return np.zeros(0, dtype=np.float32)
    return np.concatenate(chunks)


@dataclass(slots=True)
class Loudness:
    integrated_lufs: float | None
    true_peak_dbtp: float | None
    lra: float | None
    threshold: float | None

    def as_dict(self) -> dict:
        return {
            "integrated_lufs": _round(self.integrated_lufs, 1),
            "true_peak_dbtp": _round(self.true_peak_dbtp, 1),
            "loudness_range_lu": _round(self.lra, 1),
        }


_JSON_BLOCK = re.compile(r"\{[^{}]*\"input_i\"[^{}]*\}", re.S)


def loudness(
    path: str | Path,
    config: AudioConfig,
    *,
    start: float | None = None,
    duration: float | None = None,
) -> Loudness:
    """ITU-R BS.1770 integrated loudness, true peak and LRA (ffmpeg loudnorm)."""
    args = [config.ffmpeg, "-nostdin", "-hide_banner"]
    if start:
        args += ["-ss", f"{start:.3f}"]
    limit = config.max_duration if duration is None else min(duration, config.max_duration)
    args += [
        "-i", str(path), "-vn", "-t", f"{limit:.3f}",
        "-af", "loudnorm=print_format=json", "-f", "null", "-",
    ]
    _, stderr = run(args, config)
    match = _JSON_BLOCK.search(stderr)
    if not match:
        raise AudioError("could not read loudness measurement from ffmpeg")
    data = json.loads(match.group(0))
    return Loudness(
        integrated_lufs=_float(data.get("input_i")),
        true_peak_dbtp=_float(data.get("input_tp")),
        lra=_float(data.get("input_lra")),
        threshold=_float(data.get("input_thresh")),
    )


def loudnorm_measure_raw(path: str | Path, config: AudioConfig, target: str) -> dict:
    """First loudnorm pass with the given target, raw measured values."""
    _, stderr = run(
        [
            config.ffmpeg, "-nostdin", "-hide_banner", "-i", str(path), "-vn",
            "-af", f"{target}:print_format=json", "-f", "null", "-",
        ],
        config,
    )
    match = _JSON_BLOCK.search(stderr)
    if not match:
        raise AudioError("could not read loudness measurement from ffmpeg")
    return json.loads(match.group(0))


OUTPUT_FORMATS = {
    "wav": ["-c:a", "pcm_s16le"],
    "flac": ["-c:a", "flac"],
    "mp3": ["-c:a", "libmp3lame", "-b:a", "192k"],
    "ogg": ["-c:a", "libvorbis", "-q:a", "5"],
    "opus": ["-c:a", "libopus", "-b:a", "96k"],
    "m4a": ["-c:a", "aac", "-b:a", "192k"],
}


def normalize_format(fmt: str | None, default: str = "wav") -> str:
    value = (fmt or default).strip().lower().lstrip(".")
    if value == "aac":
        value = "m4a"
    if value not in OUTPUT_FORMATS:
        raise AudioError(
            f"unsupported output format {fmt!r}; use one of {', '.join(sorted(OUTPUT_FORMATS))}"
        )
    return value


def format_from_path(path: str | None, fmt: str | None, default: str = "wav") -> str:
    if fmt:
        return normalize_format(fmt)
    if path:
        suffix = Path(path).suffix.lower().lstrip(".")
        if suffix in OUTPUT_FORMATS or suffix == "aac":
            return normalize_format(suffix)
    return normalize_format(default)


def encode_args(fmt: str) -> list[str]:
    return list(OUTPUT_FORMATS[normalize_format(fmt)])


def encode_array(
    samples: np.ndarray,
    sample_rate: int,
    out_path: str | Path,
    fmt: str,
    config: AudioConfig,
) -> None:
    """Encode float samples ``(frames,)`` or ``(frames, channels)`` to a file."""
    data = np.asarray(samples, dtype="<f4")
    if data.ndim == 1:
        data = data[:, None]
    channels = data.shape[1]
    run(
        [
            config.ffmpeg, "-nostdin", "-v", "error", "-y",
            "-f", "f32le", "-ar", str(sample_rate), "-ac", str(channels), "-i", "-",
            *encode_args(fmt), "-f", _muxer(fmt), str(out_path),
        ],
        config,
        input_bytes=np.ascontiguousarray(data).tobytes(),
    )


def _muxer(fmt: str) -> str:
    return {"m4a": "ipod", "opus": "ogg"}.get(fmt, fmt)


def transcode(src: str | Path, out_path: str | Path, fmt: str, config: AudioConfig,
              *, filters: str | None = None, sample_rate: int | None = None) -> str:
    """Re-encode ``src`` (optionally through an audio filter chain)."""
    args = [config.ffmpeg, "-nostdin", "-hide_banner", "-y", "-i", str(src), "-vn"]
    if filters:
        args += ["-af", filters]
    if sample_rate:
        args += ["-ar", str(sample_rate)]
    args += [*encode_args(fmt), "-f", _muxer(fmt), str(out_path)]
    _, stderr = run(args, config)
    return stderr


class StreamEncoder:
    """Feed float32 chunks into an ffmpeg encoder process."""

    def __init__(self, out_path: str | Path, fmt: str, sample_rate: int, channels: int,
                 config: AudioConfig) -> None:
        self._errlog = tempfile.TemporaryFile()
        self._config = config
        args = [
            config.ffmpeg, "-nostdin", "-v", "error", "-y",
            "-f", "f32le", "-ar", str(sample_rate), "-ac", str(channels), "-i", "-",
            *encode_args(fmt), "-f", _muxer(fmt), str(out_path),
        ]
        try:
            self._proc = subprocess.Popen(args, stdin=subprocess.PIPE, stderr=self._errlog)
        except FileNotFoundError as exc:
            self._errlog.close()
            raise _missing(config.ffmpeg) from exc

    def write(self, chunk: np.ndarray) -> None:
        assert self._proc.stdin is not None
        try:
            self._proc.stdin.write(np.ascontiguousarray(chunk, dtype="<f4").tobytes())
        except BrokenPipeError as exc:
            raise AudioError(self._failure()) from exc

    def close(self) -> None:
        try:
            if self._proc.stdin is not None:
                self._proc.stdin.close()
            self._proc.wait(timeout=self._config.timeout)
            if self._proc.returncode != 0:
                raise AudioError(self._failure())
        finally:
            if self._proc.poll() is None:
                self._proc.kill()
                self._proc.wait()
            self._errlog.close()

    def _failure(self) -> str:
        self._errlog.seek(0)
        return _ffmpeg_error(self._config.ffmpeg, self._errlog.read().decode("utf-8", "replace"))


def pcm_md5(path: str | Path, config: AudioConfig) -> str | None:
    """MD5 of the decoded PCM, for "same samples, different container" checks."""
    out, _ = run(
        [config.ffmpeg, "-nostdin", "-v", "error", "-i", str(path), "-vn",
         "-map", "0:a:0", "-f", "md5", "-"],
        config,
    )
    text = out.decode("ascii", "replace").strip()
    return text.split("=", 1)[1] if "=" in text else None


__all__ = [
    "DecodeStats",
    "Loudness",
    "MediaInfo",
    "OUTPUT_FORMATS",
    "StreamEncoder",
    "decode",
    "decode_chunks",
    "encode_array",
    "format_from_path",
    "loudness",
    "loudnorm_measure_raw",
    "normalize_format",
    "pcm_md5",
    "probe",
    "run",
    "transcode",
]

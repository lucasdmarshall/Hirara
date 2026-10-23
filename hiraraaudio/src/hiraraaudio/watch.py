"""audio_watch: monitor a live stream in the background and report events.

An agent's tool call is short-lived; a radio stream or a live feed is not.
This keeps a small monitor running between calls. The agent starts it, polls
for events with a cursor (dead air, audio back, level spikes, clipping, beeps,
DTMF, stalls, end of stream) and stops it. All analysis is cheap signal
processing on a 16 kHz mono decode, so a handful of watchers run on one CPU.

Stream URLs go through the same perimeter as every other fetch: each hop is
resolved, checked and pinned by hirara-core's SSRF guard before connecting.
"""

from __future__ import annotations

import collections
import subprocess
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import httpx
import numpy as np
from hirara_core import BlockedURL, resolve_target

from . import dsp, tones
from .config import AudioConfig
from .errors import AudioError
from .media import LOCAL_ONLY

BLOCK = 1600  # 100 ms at 16 kHz
MAX_EVENTS = 1000
STALL_S = 10.0
MAX_FINISHED = 16


@dataclass
class Settings:
    dead_air_s: float = 5.0
    silence_db: float = -50.0
    spike_db: float = 15.0
    detect_tones: bool = True
    detect_clipping: bool = True
    max_seconds: float = 3600.0
    realtime: bool = False


@dataclass
class Watch:
    id: str
    source: str
    settings: Settings
    started: float = field(default_factory=time.time)
    status: str = "starting"
    error: str | None = None
    audio_seconds: float = 0.0
    level_db: float | None = None
    last_audio_wall: float = field(default_factory=time.monotonic)
    events: collections.deque = field(default_factory=lambda: collections.deque(maxlen=MAX_EVENTS))
    seq: int = 0
    stop_flag: threading.Event = field(default_factory=threading.Event)
    lock: threading.Lock = field(default_factory=threading.Lock)
    proc: subprocess.Popen | None = None
    stalled: bool = False
    finished_at: float | None = None

    def emit(self, kind: str, at: float, detail: str, **extra) -> None:
        with self.lock:
            self.seq += 1
            self.events.append({
                "seq": self.seq,
                "type": kind,
                "time": round(at, 2),
                "wall_time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "detail": detail,
                **extra,
            })

    def finish(self, status: str, error: str | None = None) -> None:
        with self.lock:
            if self.status in ("starting", "running"):
                self.status = status
                self.error = error
                self.finished_at = time.time()

    def snapshot(self, cursor: int, limit: int) -> dict:
        with self.lock:
            events = [e for e in self.events if e["seq"] > cursor][:limit]
            dropped = bool(self.events) and self.events[0]["seq"] > cursor + 1
            return {
                "watch_id": self.id,
                "source": self.source,
                "status": self.status,
                "events": events,
                "cursor": events[-1]["seq"] if events else max(cursor, 0),
                "more": bool(events) and events[-1]["seq"] < self.seq,
                "events_dropped": dropped,
                "audio_seconds": round(self.audio_seconds, 1),
                "level_db": None if self.level_db is None else round(self.level_db, 1),
                "started_at": datetime.fromtimestamp(self.started, timezone.utc).isoformat(timespec="seconds"),
                "settings": {
                    "dead_air_s": self.settings.dead_air_s,
                    "silence_db": self.settings.silence_db,
                    "spike_db": self.settings.spike_db,
                    "max_seconds": self.settings.max_seconds,
                },
                "error": self.error,
            }


class Analyzer:
    """Turns 100 ms blocks into events. Pure state machine, easy to test."""

    def __init__(self, watch: Watch) -> None:
        self.w = watch
        self.s = watch.settings
        self.t = 0.0
        self.silent_since: float | None = None
        self.dead_air = False
        self.history: collections.deque = collections.deque(maxlen=100)
        self.spike_until = -1.0
        self.clip_until = -1.0
        self.tone_buf = np.zeros(0, dtype=np.float32)
        self.tone_t0 = 0.0
        self.run: dict | None = None
        self.digit: dict | None = None

    def feed(self, block: np.ndarray) -> None:
        level = float(dsp.db(np.sqrt(np.mean(block.astype(np.float64) ** 2))))
        self.w.level_db = level
        t = self.t
        if level < self.s.silence_db:
            if self.silent_since is None:
                self.silent_since = t
            if not self.dead_air and t + 0.1 - self.silent_since >= self.s.dead_air_s:
                self.dead_air = True
                self.w.emit("dead_air", self.silent_since,
                            f"silent for {self.s.dead_air_s:g}s")
        else:
            if self.dead_air:
                gap = t - (self.silent_since or t)
                self.w.emit("audio_resumed", t, f"audio back after {gap:.1f}s of silence",
                            silence_s=round(gap, 1))
            self.silent_since = None
            self.dead_air = False
            if len(self.history) >= 20 and t >= self.spike_until:
                median = float(np.median(self.history))
                if level > median + self.s.spike_db:
                    self.w.emit("level_spike", t,
                                f"{level - median:.0f} dB above the recent level",
                                level_db=round(level, 1))
                    self.spike_until = t + 2.0
            self.history.append(level)

        if self.s.detect_clipping and t >= self.clip_until:
            if int(np.sum(np.abs(block) >= 0.99)) >= 3:
                self.w.emit("clipping", t, "samples at or near full scale")
                self.clip_until = t + 5.0

        if self.s.detect_tones:
            self._tones(block)
        self.t += len(block) / dsp.ANALYSIS_RATE
        self.w.audio_seconds = self.t

    def _tones(self, block: np.ndarray) -> None:
        self.tone_buf = np.concatenate([self.tone_buf, block])
        if len(self.tone_buf) < tones.TONE_FRAME + tones.TONE_HOP * 10:
            return
        count = (len(self.tone_buf) - tones.TONE_FRAME) // tones.TONE_HOP + 1
        frames = np.lib.stride_tricks.sliding_window_view(
            self.tone_buf, tones.TONE_FRAME)[:: tones.TONE_HOP][:count]
        res = tones.analyse_frames(frames)
        for i in range(count):
            at = self.tone_t0 + i * tones.HOP_S
            self._digit_step(res["digit"][i], at)
            self._tone_step(bool(res["tonal"][i]), float(res["freq"][i]), float(res["level"][i]), at)
        self.tone_buf = self.tone_buf[count * tones.TONE_HOP:]
        self.tone_t0 += count * tones.HOP_S

    def _digit_step(self, digit: str, at: float) -> None:
        if self.digit and digit != self.digit["d"]:
            if self.digit["n"] >= 2:
                self.w.emit("dtmf", self.digit["at"], f"DTMF {self.digit['d']}",
                            digit=self.digit["d"])
            self.digit = None
        if digit:
            if self.digit is None:
                self.digit = {"d": digit, "at": at, "n": 0}
            self.digit["n"] += 1

    def _tone_step(self, tonal: bool, freq: float, level: float, at: float) -> None:
        run = self.run
        if run and (not tonal or abs(freq - run["f"]) > 0.03 * run["f"]):
            dur = at - run["at"] + (tones.TONE_FRAME / dsp.ANALYSIS_RATE - tones.HOP_S)
            if dur >= 0.08:
                kind = "beep" if dur < 1.5 else "tone"
                self.w.emit(kind, run["at"], f"{run['f']:.0f} Hz for {dur:.2f}s",
                            freq_hz=round(run["f"], 1), duration_s=round(dur, 2))
            self.run = run = None
        if tonal and run is None:
            self.run = {"at": at, "f": freq}

    def flush(self) -> None:
        self._digit_step("", self.t)
        self._tone_step(False, 0.0, 0.0, self.t)


class WatchManager:
    def __init__(self, config: AudioConfig) -> None:
        self.config = config
        self._watches: dict[str, Watch] = {}
        self._lock = threading.Lock()

    # --- public API ----------------------------------------------------------

    def start(self, *, stream_url: str | None, audio_path: str | None, settings: Settings) -> Watch:
        if bool(stream_url) == bool(audio_path):
            raise AudioError("provide exactly one of stream_url or audio_path")
        if settings.dead_air_s <= 0 or settings.spike_db <= 0:
            raise AudioError("dead_air_s and spike_db must be positive")
        settings.max_seconds = min(max(1.0, settings.max_seconds), self.config.max_watch_seconds)
        with self._lock:
            self._prune()
            active = [w for w in self._watches.values() if w.status in ("starting", "running")]
            if len(active) >= self.config.max_watchers:
                raise AudioError(
                    f"{len(active)} watchers already running (HA_MAX_WATCHERS); stop one first"
                )
            if audio_path:
                if not self.config.allow_local_path:
                    raise AudioError("audio_path is disabled on this server (HA_ALLOW_LOCAL_PATH=false)")
                if not Path(audio_path).expanduser().is_file():
                    raise AudioError(f"file not found: {audio_path}")
                source = str(Path(audio_path).expanduser())
            else:
                assert stream_url is not None
                try:
                    # Validate now so a blocked URL fails the start call itself.
                    resolve_target(stream_url, allow_private_ips=self.config.watch_allow_private)
                except BlockedURL as exc:
                    raise AudioError(f"stream_url blocked: {exc}") from exc
                source = stream_url
            watch = Watch(id=uuid.uuid4().hex[:12], source=source, settings=settings)
            self._watches[watch.id] = watch
        threading.Thread(target=self._run, args=(watch, bool(stream_url)), daemon=True,
                         name=f"audio-watch-{watch.id}").start()
        return watch

    def get(self, watch_id: str | None) -> Watch:
        if not watch_id:
            raise AudioError("watch_id is required")
        with self._lock:
            watch = self._watches.get(watch_id)
        if watch is None:
            raise AudioError(f"unknown watch_id: {watch_id}")
        self._check_stall(watch)
        return watch

    def stop(self, watch_id: str | None) -> Watch:
        watch = self.get(watch_id)
        watch.stop_flag.set()
        proc = watch.proc
        if proc is not None and proc.poll() is None:
            proc.kill()
        watch.finish("stopped")
        return watch

    def list(self) -> list[dict]:
        with self._lock:
            watches = list(self._watches.values())
        return [
            {"watch_id": w.id, "source": w.source, "status": w.status,
             "audio_seconds": round(w.audio_seconds, 1), "events": w.seq}
            for w in watches
        ]

    # --- internals -----------------------------------------------------------------

    def _prune(self) -> None:
        done = sorted((w for w in self._watches.values() if w.finished_at),
                      key=lambda w: w.finished_at or 0)
        for w in done[:-MAX_FINISHED] if len(done) > MAX_FINISHED else []:
            self._watches.pop(w.id, None)

    def _check_stall(self, watch: Watch) -> None:
        if watch.status != "running":
            return
        idle = time.monotonic() - watch.last_audio_wall
        if idle >= STALL_S and not watch.stalled:
            watch.stalled = True
            watch.emit("stalled", watch.audio_seconds, f"no audio received for {idle:.0f}s")

    def _run(self, watch: Watch, is_url: bool) -> None:
        cfg = self.config
        args = [cfg.ffmpeg, "-v", "error", "-nostdin"] if not is_url else [cfg.ffmpeg, "-v", "error"]
        if watch.settings.realtime and not is_url:
            args.append("-re")
        args += [*LOCAL_ONLY, "-i", "pipe:0" if is_url else watch.source,
                 "-vn", "-ac", "1", "-ar", str(dsp.ANALYSIS_RATE), "-f", "f32le", "-"]
        errlog = tempfile.TemporaryFile()
        try:
            proc = subprocess.Popen(args, stdin=subprocess.PIPE if is_url else subprocess.DEVNULL,
                                    stdout=subprocess.PIPE, stderr=errlog)
        except FileNotFoundError:
            errlog.close()
            watch.finish("error", f"{cfg.ffmpeg} is not installed")
            return
        watch.proc = proc
        with watch.lock:
            if watch.status == "starting":
                watch.status = "running"
        feeder = None
        if is_url:
            feeder = threading.Thread(target=self._feed_url, args=(watch, proc), daemon=True)
            feeder.start()

        analyzer = Analyzer(watch)
        deadline = time.monotonic() + watch.settings.max_seconds
        try:
            assert proc.stdout is not None
            while not watch.stop_flag.is_set():
                buf = proc.stdout.read(BLOCK * 4)
                if not buf:
                    break
                watch.last_audio_wall = time.monotonic()
                if watch.stalled:
                    watch.stalled = False
                    watch.emit("resumed", analyzer.t, "audio data flowing again")
                usable = len(buf) - len(buf) % 4
                analyzer.feed(np.frombuffer(buf[:usable], dtype="<f4"))
                if time.monotonic() >= deadline or analyzer.t >= watch.settings.max_seconds:
                    watch.emit("limit_reached", analyzer.t,
                               f"stopped after max_seconds={watch.settings.max_seconds:g}")
                    watch.stop_flag.set()
                    watch.finish("ended")
                    break
            analyzer.flush()
            if watch.stop_flag.is_set():
                return
            proc.wait(timeout=5)
            if watch.error:
                # The URL feeder failed; its message beats ffmpeg's "invalid data".
                watch.emit("stream_error", analyzer.t, watch.error)
                watch.finish("error", watch.error)
                return
            if proc.returncode not in (0, None):
                errlog.seek(0)
                tail = [ln for ln in errlog.read().decode("utf-8", "replace").splitlines()
                        if ln.strip()]
                message = tail[-1] if tail else f"ffmpeg exited with {proc.returncode}"
                watch.emit("stream_error", analyzer.t, message)
                watch.finish("error", message)
                return
            watch.emit("stream_ended", analyzer.t, "the source ended")
            watch.finish("ended")
        except Exception as exc:  # noqa: BLE001 — a monitor must report, not die silently
            watch.emit("stream_error", analyzer.t, f"monitor failed: {exc}")
            watch.finish("error", str(exc))
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
            if proc.stdout is not None:
                proc.stdout.close()
            errlog.close()

    def _feed_url(self, watch: Watch, proc: subprocess.Popen) -> None:
        """Pull the stream through the SSRF guard and pipe it into ffmpeg."""
        current = watch.source
        try:
            with httpx.Client(timeout=httpx.Timeout(15.0, read=STALL_S * 3),
                              follow_redirects=False) as client:
                for _ in range(6):
                    target = resolve_target(current,
                                            allow_private_ips=self.config.watch_allow_private)
                    request = client.build_request(
                        "GET",
                        httpx.URL(target.url).copy_with(host=target.ip),
                        headers={"Host": target.host_header, "User-Agent": "hiraraaudio/0.1",
                                 "Icy-MetaData": "0"},
                        extensions={"sni_hostname": target.host},
                    )
                    response = client.send(request, stream=True)
                    try:
                        if response.is_redirect:
                            location = response.headers.get("location")
                            if not location:
                                raise AudioError("redirect with no Location header")
                            current = str(httpx.URL(current).join(location))
                            continue
                        if response.status_code >= 400:
                            raise AudioError(f"HTTP {response.status_code} from stream")
                        for data in response.iter_bytes():
                            if watch.stop_flag.is_set():
                                return
                            assert proc.stdin is not None
                            proc.stdin.write(data)
                        return
                    finally:
                        response.close()
                raise AudioError("too many redirects")
        except BlockedURL as exc:
            watch.error = f"stream_url blocked: {exc}"
        except (AudioError, httpx.HTTPError) as exc:
            watch.error = str(exc) or type(exc).__name__
        except (BrokenPipeError, OSError):
            pass
        finally:
            try:
                if proc.stdin is not None:
                    proc.stdin.close()
            except OSError:
                pass


__all__ = ["Analyzer", "Settings", "Watch", "WatchManager"]

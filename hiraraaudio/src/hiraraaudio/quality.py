"""audio_check and audio_fix: judge audio against a delivery spec, then repair it.

A library hands back numbers (-19.3 LUFS, -0.4 dBTP). An agent needs the
judgement: does this pass for a podcast, and if not, what exactly to change.
audio_check returns that, and each failure carries the audio_fix arguments
that address it, so check -> fix -> check is a closed loop.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path

from . import dsp
from .analysis import Measurement
from .config import AudioConfig
from .errors import AudioError
from .media import loudnorm_measure_raw, probe, transcode


@dataclass(frozen=True)
class Preset:
    name: str
    description: str
    target_lufs: float | None = None
    lufs_tolerance: float = 1.0
    max_true_peak: float | None = None
    max_lra: float | None = None
    rms_range: tuple[float, float] | None = None  # ACX-style overall RMS window
    max_sample_peak: float | None = None
    max_noise_floor: float | None = None
    min_sample_rate: int | None = None
    exact_sample_rate: int | None = None
    max_silence: float | None = None
    head_silence: tuple[float, float] | None = None
    tail_silence: tuple[float, float] | None = None
    max_duration: float | None = None
    min_speech_pct: float | None = None
    min_snr: float | None = None
    max_music_pct: float | None = None


PRESETS: dict[str, Preset] = {
    "podcast": Preset(
        "podcast",
        "Spoken-word podcast: -16 LUFS integrated, true peak at or below -1 dBTP",
        target_lufs=-16.0, lufs_tolerance=1.0, max_true_peak=-1.0,
        min_sample_rate=44100, max_silence=5.0,
    ),
    "broadcast": Preset(
        "broadcast",
        "EBU R128 broadcast: -23 LUFS ±0.5, true peak at or below -1 dBTP",
        target_lufs=-23.0, lufs_tolerance=0.5, max_true_peak=-1.0, max_lra=20.0,
        max_silence=10.0,
    ),
    "music_streaming": Preset(
        "music_streaming",
        "Music streaming: about -14 LUFS, true peak at or below -1 dBTP",
        target_lufs=-14.0, lufs_tolerance=1.0, max_true_peak=-1.0,
        min_sample_rate=44100,
    ),
    "audiobook": Preset(
        "audiobook",
        "ACX audiobook: RMS -23 to -18 dBFS, peaks at or below -3 dBFS, "
        "noise floor at or below -60 dBFS, 44.1 kHz, room tone at head and tail",
        rms_range=(-23.0, -18.0), max_sample_peak=-3.0, max_noise_floor=-60.0,
        exact_sample_rate=44100, head_silence=(0.5, 1.0), tail_silence=(1.0, 5.0),
        max_duration=120 * 60.0,
    ),
    "stt_ready": Preset(
        "stt_ready",
        "Ready for speech-to-text: enough speech, clean enough, not clipped",
        min_sample_rate=16000, min_speech_pct=20.0, min_snr=15.0, max_music_pct=50.0,
    ),
}


def _check(name, status, measured, expected, message, fix=None) -> dict:
    return {
        "name": name,
        "status": status,
        "measured": measured,
        "expected": expected,
        "message": message,
        "fix": fix,
    }


def evaluate(m: Measurement, preset: Preset) -> list[dict]:
    checks: list[dict] = []
    loud = m.loud
    native = m.native
    rate = m.info.sample_rate

    if preset.target_lufs is not None:
        lufs = loud.integrated_lufs if loud else None
        lo, hi = preset.target_lufs - preset.lufs_tolerance, preset.target_lufs + preset.lufs_tolerance
        if lufs is None:
            checks.append(_check("integrated_loudness", "fail", None, f"{lo}..{hi} LUFS",
                                 "no measurable programme loudness (silent or too short)"))
        elif lo <= lufs <= hi:
            checks.append(_check("integrated_loudness", "pass", round(lufs, 1), f"{lo}..{hi} LUFS",
                                 f"{lufs:.1f} LUFS is on target"))
        else:
            delta = preset.target_lufs - lufs
            checks.append(_check(
                "integrated_loudness", "fail", round(lufs, 1), f"{lo}..{hi} LUFS",
                f"{lufs:.1f} LUFS is {abs(delta):.1f} LU too {'quiet' if delta > 0 else 'loud'}",
                {"target_lufs": preset.target_lufs},
            ))

    if preset.max_true_peak is not None and loud and loud.true_peak_dbtp is not None:
        tp = loud.true_peak_dbtp
        ok = tp <= preset.max_true_peak + 0.05
        checks.append(_check(
            "true_peak", "pass" if ok else "fail", round(tp, 1), f"<= {preset.max_true_peak} dBTP",
            f"true peak {tp:.1f} dBTP" + ("" if ok else " is too hot"),
            None if ok else {"max_true_peak": preset.max_true_peak},
        ))

    if preset.max_lra is not None and loud and loud.lra is not None:
        ok = loud.lra <= preset.max_lra
        checks.append(_check("loudness_range", "pass" if ok else "warn", round(loud.lra, 1),
                             f"<= {preset.max_lra} LU",
                             f"loudness range {loud.lra:.1f} LU"
                             + ("" if ok else "; consider gentle compression")))

    if preset.rms_range is not None and native and native.rms_dbfs is not None:
        lo, hi = preset.rms_range
        rms = native.rms_dbfs
        ok = lo <= rms <= hi
        checks.append(_check(
            "rms_level", "pass" if ok else "fail", round(rms, 1), f"{lo}..{hi} dBFS",
            f"overall RMS {rms:.1f} dBFS" + ("" if ok else " is out of range"),
            None if ok else {"target_lufs": round((lo + hi) / 2, 1)},
        ))

    if preset.max_sample_peak is not None and native and native.peak_dbfs is not None:
        ok = native.peak_dbfs <= preset.max_sample_peak + 0.05
        checks.append(_check(
            "sample_peak", "pass" if ok else "fail", round(native.peak_dbfs, 1),
            f"<= {preset.max_sample_peak} dBFS",
            f"sample peak {native.peak_dbfs:.1f} dBFS" + ("" if ok else " is too hot"),
            None if ok else {"max_true_peak": preset.max_sample_peak - 0.5},
        ))

    if native is not None:
        ok = native.clipped_runs == 0
        checks.append(_check(
            "clipping", "pass" if ok else "fail", native.clipped_samples, 0,
            "no clipped samples" if ok else
            f"{native.clipped_runs} clipped run(s), first at {dsp.fmt_time(native.clip_times[0])}"
            "; the damage is already in the samples, re-record or re-export from the source "
            "if you can",
        ))
        dc = max((abs(v) for v in native.dc_offset), default=0.0)
        ok = dc < 0.005
        checks.append(_check("dc_offset", "pass" if ok else "warn", round(dc, 4), "< 0.005",
                             "no DC offset" if ok else f"DC offset {dc:.4f}",
                             None if ok else {"remove_dc": True}))
        if native.channel_correlation is not None:
            corr = native.channel_correlation
            ok = corr > -0.2
            checks.append(_check(
                "phase", "pass" if ok else "fail", corr, "> -0.2",
                f"channel correlation {corr}" + ("" if ok else
                                                 "; channels cancel when summed to mono"),
            ))

    if preset.max_noise_floor is not None:
        floor = m.quietest_window_db()
        if floor is None:
            checks.append(_check("noise_floor", "warn", None, f"<= {preset.max_noise_floor} dBFS",
                                 "only digital silence between phrases; ACX expects natural "
                                 "room tone"))
        else:
            ok = floor <= preset.max_noise_floor
            checks.append(_check(
                "noise_floor", "pass" if ok else "fail", round(floor, 1),
                f"<= {preset.max_noise_floor} dBFS",
                f"noise floor {floor:.1f} dBFS" + ("" if ok else " is too high"),
                None if ok else {"denoise": True},
            ))

    if rate:
        if preset.exact_sample_rate is not None:
            ok = rate == preset.exact_sample_rate
            checks.append(_check("sample_rate", "pass" if ok else "fail", rate,
                                 preset.exact_sample_rate, f"{rate} Hz",
                                 None if ok else {"sample_rate": preset.exact_sample_rate}))
        elif preset.min_sample_rate is not None:
            ok = rate >= preset.min_sample_rate
            checks.append(_check(
                "sample_rate", "pass" if ok else "warn", rate, f">= {preset.min_sample_rate}",
                f"{rate} Hz" + ("" if ok else "; upsampling will not restore lost detail"),
            ))

    if preset.max_silence is not None:
        longest = max((b - a for a, b in m.silences(0.2)), default=0.0)
        ok = longest <= preset.max_silence
        checks.append(_check(
            "dead_air", "pass" if ok else "warn", round(longest, 1), f"<= {preset.max_silence}s",
            f"longest silence {longest:.1f}s" + ("" if ok else "; audio_tighten shortens it"),
        ))

    if preset.head_silence or preset.tail_silence:
        head, tail = m.leading_trailing_silence()
        for name, value, bounds in (("head_room_tone", head, preset.head_silence),
                                    ("tail_room_tone", tail, preset.tail_silence)):
            if bounds is None:
                continue
            lo, hi = bounds
            ok = lo <= value <= hi
            checks.append(_check(name, "pass" if ok else "fail", round(value, 2), f"{lo}..{hi}s",
                                 f"{value:.2f}s of room tone"))

    if preset.max_duration is not None:
        ok = m.duration <= preset.max_duration
        checks.append(_check("duration", "pass" if ok else "fail", round(m.duration, 1),
                             f"<= {preset.max_duration:.0f}s", f"{dsp.fmt_time(m.duration)} long"))

    share = m.kind_share()
    if preset.min_speech_pct is not None:
        ok = share["speech"] >= preset.min_speech_pct
        checks.append(_check("speech_present", "pass" if ok else "fail", share["speech"],
                             f">= {preset.min_speech_pct}%", f"speech in ~{share['speech']:.0f}% "
                             "of the file (estimate)"))
    if preset.min_snr is not None:
        snr = m.snr_db()
        if snr is not None:
            status = "pass" if snr >= preset.min_snr else ("warn" if snr >= preset.min_snr - 5 else "fail")
            checks.append(_check("signal_to_noise", status, round(snr, 1), f">= {preset.min_snr} dB",
                                 f"about {snr:.0f} dB above the noise floor",
                                 None if status == "pass" else {"denoise": True}))
    if preset.max_music_pct is not None:
        ok = share["music"] <= preset.max_music_pct
        checks.append(_check("music_share", "pass" if ok else "warn", share["music"],
                             f"<= {preset.max_music_pct}%", f"music in ~{share['music']:.0f}% "
                             "(estimate); background music lowers transcription accuracy"))

    hum = dsp.detect_hum(m.features.hum_spectrum)
    checks.append(_check(
        "hum", "pass" if hum is None else "warn",
        None if hum is None else hum["mains_hz"], "none",
        "no mains hum" if hum is None else f"{hum['mains_hz']} Hz mains hum",
        None if hum is None else {"dehum": str(hum["mains_hz"])},
    ))
    return checks


def check_result(m: Measurement, preset: Preset, source: str) -> dict:
    checks = evaluate(m, preset)
    failures = [c for c in checks if c["status"] == "fail"]
    warnings = [c for c in checks if c["status"] == "warn"]
    fix_args: dict = {}
    for c in checks:
        if isinstance(c["fix"], dict) and c["status"] != "pass":
            fix_args.update(c["fix"])
    if fix_args:
        fix_args = {"preset": preset.name, **fix_args}
    lines = [
        f"{preset.name}: {'PASS' if not failures else 'FAIL'} "
        f"({len(failures)} failed, {len(warnings)} warnings, {len(checks)} checks)"
    ]
    for c in checks:
        if c["status"] != "pass":
            lines.append(f"{c['status'].upper()} {c['name']}: {c['message']} (expected {c['expected']})")
    return {
        "source": source,
        "preset": preset.name,
        "description": preset.description,
        "passed": not failures,
        "checks": checks,
        "failures": len(failures),
        "warnings": len(warnings),
        "suggested_fix": fix_args or None,
        "text": "\n".join(lines),
        "duration": round(m.duration, 2),
        "truncated": m.features.truncated,
        "error": None,
    }


def get_preset(name: str | None) -> Preset:
    key = (name or "podcast").strip().lower()
    if key not in PRESETS:
        raise AudioError(f"unknown preset {name!r}; use one of {', '.join(PRESETS)}")
    return PRESETS[key]


# --- audio_fix ----------------------------------------------------------------

def build_fix(
    path: Path,
    config: AudioConfig,
    *,
    preset: Preset | None,
    target_lufs: float | None,
    max_true_peak: float | None,
    remove_dc: bool | None,
    dehum: str | None,
    highpass_hz: float | None,
    denoise: bool,
    before: Measurement,
) -> tuple[str, list[str]]:
    """The ffmpeg filter chain for the requested repairs, and what it does."""
    steps: list[str] = []
    filters: list[str] = []

    if preset is not None and target_lufs is None and preset.target_lufs is not None:
        target_lufs = preset.target_lufs
    if preset is not None and target_lufs is None and preset.rms_range is not None:
        target_lufs = round(sum(preset.rms_range) / 2, 1)
    if preset is not None and max_true_peak is None:
        max_true_peak = preset.max_true_peak
        if max_true_peak is None and preset.max_sample_peak is not None:
            max_true_peak = preset.max_sample_peak - 0.5

    dc = max((abs(v) for v in (before.native.dc_offset if before.native else [])), default=0.0)
    if remove_dc is None:
        remove_dc = dc >= 0.005
    cutoff = highpass_hz if highpass_hz else (20.0 if remove_dc else None)
    if cutoff:
        filters.append(f"highpass=f={cutoff:g}:poles=2")
        steps.append(f"high-pass at {cutoff:g} Hz" + (" (removes DC offset)" if remove_dc else ""))

    mains = None
    if dehum and dehum != "off":
        if dehum == "auto":
            hum = dsp.detect_hum(before.features.hum_spectrum)
            mains = hum["mains_hz"] if hum else None
        elif dehum in ("50", "60"):
            mains = int(dehum)
        else:
            raise AudioError("dehum must be auto, 50, 60 or off")
    if mains:
        for k in range(1, 5):
            filters.append(f"bandreject=f={mains * k}:width_type=q:w=30")
        steps.append(f"notch out {mains} Hz hum and 3 harmonics")

    if denoise:
        floor = dsp.noise_floor_db(before.features)
        nf = float(min(-20.0, max(-80.0, floor if floor is not None else -50.0)))
        filters.append(f"afftdn=nf={nf:.0f}:nr=12")
        steps.append(f"spectral noise reduction (floor {nf:.0f} dB)")

    if target_lufs is not None or max_true_peak is not None:
        tl = target_lufs if target_lufs is not None else (
            before.loud.integrated_lufs if before.loud and before.loud.integrated_lufs else -16.0
        )
        tp = max_true_peak if max_true_peak is not None else -1.0
        # Two-pass loudnorm: measure with the exact chain so far, then apply
        # linear gain where possible (no pumping) and limit only if needed.
        pre = ",".join(filters)
        first = loudnorm_measure_raw(
            path, config, (pre + "," if pre else "") + f"loudnorm=I={tl}:TP={tp}:LRA=11"
        )
        filters.append(
            f"loudnorm=I={tl}:TP={tp}:LRA=11"
            f":measured_I={first['input_i']}:measured_TP={first['input_tp']}"
            f":measured_LRA={first['input_lra']}:measured_thresh={first['input_thresh']}"
            f":offset={first['target_offset']}:linear=true"
        )
        steps.append(f"normalise to {tl} LUFS, true peak <= {tp} dBTP")

    return ",".join(filters), steps


def run_fix(path: Path, config: AudioConfig, *, fmt: str, sample_rate: int | None,
            chain: str) -> Path:
    out = Path(tempfile.mkstemp(prefix="hiraraaudio-fix-", suffix=f".{fmt}")[1])
    info = probe(path, config)
    rate = sample_rate or info.sample_rate
    # loudnorm resamples internally (to 192 kHz); pin the output rate back.
    transcode(path, out, fmt, config, filters=chain or None, sample_rate=rate)
    return out


__all__ = ["PRESETS", "Preset", "build_fix", "check_result", "evaluate", "get_preset", "run_fix"]

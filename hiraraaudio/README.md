<div align="center">

# HiraraAudio

**Lightweight audio tools for AI agents that cannot listen.**

Part of [Hirara](https://github.com/lucasdmarshall/Hirara). FFmpeg + NumPy
signal processing only: no ML models, no model downloads, CPU only, no API keys.

</div>

---

## Why these tools

An agent can already run `ffmpeg` through `execute_code`. What it cannot do is
hear. So these tools do not wrap FFmpeg commands; each one gives an agent
something a library call does not:

- **Describe**: audio reduced to a short timeline an agent can read, or a
  labelled image a vision model can inspect.
- **Judge**: audio checked against a delivery spec, with the fix for every
  failure.
- **Verify**: an edit checked against the original, since the agent cannot
  listen to its own result.
- **Plan, act, re-check**: edits that need analysis to land in the right place.
- **Hold state**: a live stream watched between tool calls.

## Tools

| Tool | What it gives an agent |
|---|---|
| **`audio_info`** | Container, codec, duration, channels, tags, chapters (FFprobe, no decode) |
| **`audio_profile`** | A short timeline of speech / music / noise / tones / silence with levels, loudness, true peak, and events (long silences, clipping, level jumps, hum), plus a text summary |
| **`audio_check`** | Pass/fail against `podcast`, `broadcast` (EBU R128), `music_streaming`, `audiobook` (ACX) or `stt_ready`, with `audio_fix` arguments for each failure |
| **`audio_fix`** | Two-pass loudness normalisation, true-peak limit, DC removal, hum notch, rumble high-pass, optional denoise, then a re-check (before/after) |
| **`audio_compare`** | Whether b has a's material, the offset, and which spans were removed, inserted, moved or changed, where silence was shortened, and level changes |
| **`audio_find`** | Every place a reference clip occurs in a long recording (jingles, ads, intros) |
| **`audio_fingerprint`** | Duplicates and containment across many files, re-encoded or not |
| **`audio_split`** | Cut points at natural pauses within length bounds, never mid-word when a pause exists |
| **`audio_tighten`** | Shortens long pauses with click-free cuts; dry-run plan, then re-measures the output |
| **`audio_spectrogram`** | A labelled spectrogram PNG with plot geometry, plus steady tones |
| **`audio_tones`** | DTMF digits, beeps and test tones (frequency, timing), 50/60 Hz mains hum |
| **`audio_speak`** | Text-to-speech in 100+ languages with eSpeak NG (synthetic voice, instant, tiny) |
| **`audio_sonify`** | A data series as sound: pitch follows value, panned left to right |
| **`audio_watch`** | Background monitor for a live stream: dead air, audio back, level spikes, clipping, beeps, DTMF, stalls, end of stream |

Every input takes one of `audio_path`, `audio_url` (opt-in) or
`audio_base64`. Every error comes back in the JSON `"error"` field.

### Typical loops

- **Unknown recording**: `audio_profile` → decide → `transcribe` / `audio_split`.
- **Deliver a podcast**: `audio_check` → `audio_fix` with its `suggested_fix` → `after.passed`.
- **Edit you cannot hear**: `audio_tighten` → `audio_compare` (original vs output)
  should show only `silence_shortened`.
- **Ad / jingle audit**: `audio_find` with the jingle as the clip.
- **Long transcription**: `audio_split` (e.g. 30–120 s pieces) → `transcribe` each piece.

---

## Quick start

```bash
apt-get install ffmpeg espeak-ng          # espeak-ng only for audio_speak
pip install -e ../hirara-core -e ".[service,mcp]"
uvicorn hiraraaudio.service:app --host 127.0.0.1 --port 9300
```

```bash
curl -X POST localhost:9300/audio_profile -H 'content-type: application/json' \
  -d '{"audio_path":"/data/episode.mp3"}'

curl -X POST localhost:9300/audio_check -H 'content-type: application/json' \
  -d '{"audio_path":"/data/episode.mp3","preset":"podcast"}'

curl -X POST localhost:9300/audio_watch -H 'content-type: application/json' \
  -d '{"action":"start","stream_url":"https://radio.example/live.mp3","dead_air_s":5}'
```

Large files can be uploaded instead of named by path:

```bash
curl -X POST localhost:9300/upload/audio_profile \
  -F file=@episode.mp3 -F 'arguments={"max_segments":20}'
```

MCP: `python -m hiraraaudio.mcp_server` (stdio) or `--transport stdio`.

Python SDK (in-process, no service): `pip install "hirara[audio]"`, then
`hirara.audio_profile(path="episode.mp3")`.

Docker:

```bash
docker compose up -d --build     # put files in the `data` volume, name them /data/...
```

---

## What "estimate" means here

The speech / music / noise / tones labels come from classic signal features
(energy dips, zero-crossing variation, spectral flatness, tonality), not a
trained classifier. They are right on clean material and should be read as
"mostly" on mixed material, such as speech over a music bed. Loudness and true
peak are ITU-R BS.1770 measurements from FFmpeg and are exact.

`audio_watch` stream URLs go through the shared SSRF guard, so streams must be
on ports 80, 443, 8080 or 8443 and on public addresses (set
`HA_WATCH_ALLOW_PRIVATE=true` to watch a private network stream).

---

## Configuration

| Variable | Default | Notes |
|---|---|---|
| `HA_ALLOW_LOCAL_PATH` | `true` | Read files named by path. Set `false` on a network-exposed service |
| `HA_ALLOW_OUTPUT_PATH` | `true` | Write `output_path` / `output_dir`. Set `false` on a network-exposed service |
| `HA_ALLOW_URL_FETCH` | `false` | Allow `*_url` inputs (through the SSRF guard) |
| `HA_URL_TIMEOUT` | `60` | Seconds per URL fetch |
| `HA_MAX_BYTES` | `209715200` | Largest input file |
| `HA_MAX_DURATION` | `14400` | Seconds analysed per input (longer input is marked `truncated`) |
| `HA_MAX_OUTPUT_BYTES` | `26214400` | Largest result returned inline as base64 |
| `HA_TIMEOUT` | `900` | Seconds per FFmpeg / eSpeak process |
| `HA_FFMPEG` / `HA_FFPROBE` / `HA_ESPEAK` | `ffmpeg` / `ffprobe` / `espeak-ng` | Binaries |
| `HA_MAX_SPEAK_CHARS` | `5000` | Longest `audio_speak` text |
| `HA_MAX_FINGERPRINT_SOURCES` | `50` | Most files per `audio_fingerprint` |
| `HA_MAX_WATCHERS` | `4` | Concurrent `audio_watch` monitors |
| `HA_MAX_WATCH_SECONDS` | `43200` | Longest a monitor may run |
| `HA_WATCH_ALLOW_PRIVATE` | `false` | Let `audio_watch` reach private / loopback hosts |
| `HA_PORT` | `9300` | Compose host port |

---

## License

Apache-2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE).

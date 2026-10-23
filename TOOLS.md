# Hirara tool roadmap

Target tool surface for the Hirara agent toolkit. Status tracks shipping
progress in this repo (hub + SDK + packages).

| # | Tool | Status | Package / notes |
|---|---|---|---|
| 1 | `web_search` | ✅ shipped | `hirara-web` / hub |
| 2 | `web_fetch` | ✅ shipped | `hirara-web` / hub |
| 3 | `dns_lookup` | ✅ shipped | `hiraranet` |
| 4 | `port_scan` | ✅ shipped | `hiraranet` |
| 5 | `service_enum` | ✅ shipped | `hiraranet` |
| 6 | `browser_open` | ✅ shipped | `hirarabrowser` |
| 7 | `browser_click` | ✅ shipped | `hirarabrowser` |
| 8 | `browser_type` | ✅ shipped | `hirarabrowser` |
| 9 | `browser_screenshot` | ✅ shipped | `hirarabrowser` |
| 10 | `http_request` | ✅ shipped | `hirarahttp` |
| 11 | `http_history` | ✅ shipped | `hirarahttp` |
| 12 | `inspect_headers` | ✅ shipped | `hirarahttp` |
| 13 | `inspect_cookies` | ✅ shipped | `hirarahttp` |
| 14 | `inspect_response` | ✅ shipped | `hirarahttp` |
| 15 | `directory_enum` | ✅ shipped | `hirarahttp` |
| 16 | `python_exec` | ✅ shipped (as `execute_code`) | `hiraracode` — alias / rename TBD |
| 17 | `file_read` | ✅ shipped | `hirarafs` |
| 18 | `file_write` | ✅ shipped | `hirarafs` |
| 19 | `decode` | ✅ shipped | `hirarautil` |
| 20 | `hash` | ✅ shipped | `hirarautil` |
| 21 | `database_query` | ✅ shipped | `hiraradb` (SQLite) |
| 22 | `database_schema` | ✅ shipped | `hiraradb` |
| 23 | `application_logs` | ✅ shipped | `hiraraops` |
| 24 | `process_list` | ✅ shipped | `hiraraops` |
| 25 | `environment_read` | ✅ shipped | `hiraraops` |
| 26 | `jwt_inspect` | ✅ shipped | `hirarautil` |
| 27 | `jwt_decode` | ✅ shipped | `hirarautil` |
| 28 | `request_replay` | ✅ shipped | `hirarahttp` |
| 29 | `parameter_test` | ✅ shipped | `hirarahttp` |
| 30 | `response_compare` | ✅ shipped | `hirarahttp` |
| 31 | `html_to_pdf` | ✅ shipped | `hirarapdf` — HTML + CSS + images |

## Package clusters

| Package | Tools |
|---|---|
| **`hiraranet`** | `dns_lookup`, `port_scan`, `service_enum` |
| **`hirarabrowser`** | `browser_open`, `browser_click`, `browser_type`, `browser_screenshot` |
| **`hirarahttp`** | `http_request`, `http_history`, `inspect_*`, `directory_enum`, `request_replay`, `parameter_test`, `response_compare` |
| **`hirarautil`** | `decode`, `hash`, `jwt_inspect`, `jwt_decode` |
| **`hirarafs`** | `file_read`, `file_write` |
| **`hiraradb`** | `database_query`, `database_schema` |
| **`hiraraops`** | `application_logs`, `process_list`, `environment_read` |
| **`hiraraaudio`** (planned) | `audio_info`, `audio_profile`, `audio_check`, `audio_fix`, `audio_compare`, `audio_find`, `audio_fingerprint`, `audio_split`, `audio_tighten`, `audio_spectrogram`, `audio_tones`, `audio_speak`, `audio_sonify`, `audio_watch` |
| Existing | `web_*`, `execute_code` / `python_exec`, PDF (`pdf_*`, `html_to_pdf`), OCR, Office, STT (`transcribe`) |

## Upcoming

Next cluster: **`hiraraaudio`**. Speech-to-text stays on the existing
`transcribe` tool (`hirarastt`).

An agent cannot hear, and it can already run `ffmpeg` through `execute_code`.
So these are not FFmpeg wrappers. Each tool does something a bare library call
does not give an agent:

- **Describe** audio in a form an agent can reason about: a short timeline or
  a labelled image, not thousands of samples.
- **Judge** audio against a delivery spec and say what to fix.
- **Verify** an edit, since the agent cannot listen to its own result.
- **Plan, act, then re-check** edits that need analysis to get right.
- **Hold state** across calls, such as watching a live stream.

Lightweight by design: FFmpeg, NumPy and signal processing only. No ML
models, no model downloads, CPU only. eSpeak NG is the one optional system
binary (for `audio_speak`). Trimming, converting, concatenating and
resampling stay internal building blocks rather than separate tools.

| # | Tool | Status | What it gives an agent |
|---|---|---|---|
| 32 | `audio_info` | 📋 upcoming | Container, codec, duration, channels, tags and chapters (FFprobe) |
| 33 | `audio_profile` | 📋 upcoming | A short timeline of speech, music, noise and silence, plus loudness, clipping and hum events |
| 34 | `audio_check` | 📋 upcoming | Pass/fail against a preset (`podcast`, `broadcast` EBU R128, `audiobook` ACX, `music_streaming`, `stt_ready`), with the fix for each failure |
| 35 | `audio_fix` | 📋 upcoming | Applies `audio_check`'s fixes (loudness, true peak, DC, hum, rumble), then re-checks the result |
| 36 | `audio_compare` | 📋 upcoming | Two files: same content or not, time offset, and which spans were removed, added or changed |
| 37 | `audio_find` | 📋 upcoming | Every place a reference clip (jingle, ad, intro) occurs in a long recording |
| 38 | `audio_fingerprint` | 📋 upcoming | Duplicate and containment matches across many files |
| 39 | `audio_split` | 📋 upcoming | Cut points at natural pauses within length bounds, never mid-word (e.g. chunks for `transcribe`) |
| 40 | `audio_tighten` | 📋 upcoming | Shortens long silences with click-free cuts, with a dry-run plan and a re-check |
| 41 | `audio_spectrogram` | 📋 upcoming | A labelled spectrogram PNG for vision models, plus a text note of steady tones |
| 42 | `audio_tones` | 📋 upcoming | DTMF digits, beeps, test tones and 50/60 Hz mains hum |
| 43 | `audio_speak` | 📋 upcoming | Lightweight text-to-speech in many languages (eSpeak NG) |
| 44 | `audio_sonify` | 📋 upcoming | Turns a data series into sound, for accessibility |
| 45 | `audio_watch` | 📋 upcoming | Monitors a live stream in the background and reports dead air, level spikes, clipping, tones and dropouts |

## Current focus

**`dns_lookup`**, **`port_scan`**, **`service_enum`** (`hiraranet/`),
**`browser_*`** (`hirarabrowser/`), the `hirarahttp` cluster,
**`file_read` / `file_write`** (`hirarafs/`), **`decode` / `hash` /
`jwt_inspect` / `jwt_decode`** (`hirarautil/`), **`database_query` /
`database_schema`** (`hiraradb/`), **`application_logs` / `process_list` /
`environment_read`** (`hiraraops/`), and the full **`hirarahttp`** cluster
(including **`request_replay` / `parameter_test` / `response_compare`**) are
shipped, plus **`html_to_pdf`** (`hirarapdf/`).
Next up: the `hiraraaudio` cluster above.

## Engineering conventions (all tools)

Same patterns as the rest of Hirara:

- Self-hosted, no third-party API keys.
- URL fetches go through [`hirara-core`](hirara-core/) (resolve-then-pin, redirect re-validation).
- Errors return in the JSON envelope (`"error": …`), not as HTTP 5xx.
- Hub registration: `hirara-hub` `DEFAULT_PORTS` + `TOOLS`, plus compose `HUB_*_URL`.
- Local SDK: `hirara.backends` entry point with `TOOL_NAMES` / `call_tool` / `tool_schemas`.

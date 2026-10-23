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
| **`hiraradata`** | `data_profile`, `chart_render`, `diagram_render` |
| **`hiraramedia`** | `video_profile`, `image_compare`, `barcode_read`, `qr_generate` |
| **`hiraraagent`** | `memory`, `ask_human`, `schedule`, `wait_until` |
| **`hiraraaudio`** | `audio_info`, `audio_profile`, `audio_check`, `audio_fix`, `audio_compare`, `audio_find`, `audio_fingerprint`, `audio_split`, `audio_tighten`, `audio_spectrogram`, `audio_tones`, `audio_speak`, `audio_sonify`, `audio_watch` |
| Existing | `web_*`, `execute_code` / `python_exec`, PDF (`pdf_*`, `html_to_pdf`), OCR, Office, STT (`transcribe`) |

## Audio (`hiraraaudio`)

Shipped in [`hiraraaudio/`](hiraraaudio/). Speech-to-text stays on the existing
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
| 32 | `audio_info` | ✅ shipped | Container, codec, duration, channels, tags and chapters (FFprobe) |
| 33 | `audio_profile` | ✅ shipped | A short timeline of speech, music, noise and silence, plus loudness, clipping and hum events |
| 34 | `audio_check` | ✅ shipped | Pass/fail against a preset (`podcast`, `broadcast` EBU R128, `audiobook` ACX, `music_streaming`, `stt_ready`), with the fix for each failure |
| 35 | `audio_fix` | ✅ shipped | Applies `audio_check`'s fixes (loudness, true peak, DC, hum, rumble), then re-checks the result |
| 36 | `audio_compare` | ✅ shipped | Two files: same content or not, time offset, and which spans were removed, added or changed |
| 37 | `audio_find` | ✅ shipped | Every place a reference clip (jingle, ad, intro) occurs in a long recording |
| 38 | `audio_fingerprint` | ✅ shipped | Duplicate and containment matches across many files |
| 39 | `audio_split` | ✅ shipped | Cut points at natural pauses within length bounds, never mid-word (e.g. chunks for `transcribe`) |
| 40 | `audio_tighten` | ✅ shipped | Shortens long silences with click-free cuts, with a dry-run plan and a re-check |
| 41 | `audio_spectrogram` | ✅ shipped | A labelled spectrogram PNG for vision models, plus a text note of steady tones |
| 42 | `audio_tones` | ✅ shipped | DTMF digits, beeps, test tones and 50/60 Hz mains hum |
| 43 | `audio_speak` | ✅ shipped | Lightweight text-to-speech in many languages (eSpeak NG) |
| 44 | `audio_sonify` | ✅ shipped | Turns a data series into sound, for accessibility |
| 45 | `audio_watch` | ✅ shipped | Monitors a live stream in the background and reports dead air, level spikes, clipping, tones and dropouts |

## Agent essentials

Same rule as the audio cluster: a tool earns its place by doing what an agent
cannot get from a library call or one `execute_code` run. Lightweight first,
no ML models.

| # | Tool | Status | Package | What it gives an agent |
|---|---|---|---|---|
| 46 | `file_edit` | ✅ shipped | `hirarafs` | Exact-string replace / insert in a file, so an edit cannot clobber the rest of it |
| 47 | `file_search` | ✅ shipped | `hirarafs` | Regex search across files under the allowed roots, with line numbers |
| 48 | `file_list` | ✅ shipped | `hirarafs` | Glob / tree listing with sizes and times |
| 49 | `archive_list` | ✅ shipped | `hirarafs` | What is inside a zip / tar without extracting it |
| 50 | `archive_extract` | ✅ shipped | `hirarafs` | Safe extraction: no path escape (zip-slip), no links out, size and count caps against bombs |
| 51 | `time_now` | ✅ shipped | `hirarautil` | The current date and time in any timezone; a model does not know today's date |
| 52 | `date_calc` | ✅ shipped | `hirarautil` | Date arithmetic, differences, business days, timezone conversion |
| 53 | `schema_validate` | ✅ shipped | `hirarautil` | Check JSON against a JSON Schema, with every error and its path |
| 54 | `link_check` | ✅ shipped | `hirarahttp` | Broken links on a page or site, through the SSRF guard |
| 55 | `site_map` | ✅ shipped | `hirarahttp` | Same-site crawl: pages, titles, status, depth |
| 56 | `web_watch` | ✅ shipped | `hirarahttp` | Watch a URL across calls and report what changed, as a diff |
| 57 | `secret_list` | ✅ shipped | `hirarahttp` | Named, host-scoped credentials `http_request` can use without the agent ever seeing them |
| 58 | `job_start` | ✅ shipped | `hiraracode` | Long-running sandbox job (server, build, test suite) in the background |
| 59 | `job_status` | ✅ shipped | `hiraracode` | Poll a job: state, exit code, new log lines |
| 60 | `job_stop` | ✅ shipped | `hiraracode` | Stop a job and remove its container |
| 61 | `email_read` | ✅ shipped | `hirarareader` | Parse .eml / .msg / mbox: headers, body, attachments |
| 62 | `data_profile` | ✅ shipped | `hiraradata` | Profile CSV / TSV / JSON / Excel / Parquet: types, nulls, ranges, top values, outliers |
| 63 | `chart_render` | ✅ shipped | `hiraradata` | Data to a chart PNG / SVG |
| 64 | `diagram_render` | ✅ shipped | `hiraradata` | Graphviz DOT and Mermaid flowcharts to PNG / SVG |
| 65 | `video_profile` | ✅ shipped | `hiraramedia` | Scene cuts, keyframe images and an audio timeline, so an agent can "watch" a video |
| 66 | `image_compare` | ✅ shipped | `hiraramedia` | Pixel diff of two images with changed regions boxed (verify a UI change) |
| 67 | `barcode_read` | ✅ shipped | `hiraramedia` | QR codes and barcodes in an image |
| 68 | `qr_generate` | ✅ shipped | `hiraramedia` | QR code PNG / SVG from text or a URL |
| 69 | `memory` | ✅ shipped | `hiraraagent` | Notes that persist across sessions: set, get, search, list, delete |
| 70 | `ask_human` | ✅ shipped | `hiraraagent` | Ask a person a question or for approval, then check for the answer |
| 71 | `schedule` | ✅ shipped | `hiraraagent` | Reminders and follow-ups that come due later |
| 72 | `wait_until` | ✅ shipped | `hiraraagent` | Block until a time, a human answer or a due reminder (capped) |

## Current focus

**`dns_lookup`**, **`port_scan`**, **`service_enum`** (`hiraranet/`),
**`browser_*`** (`hirarabrowser/`), the `hirarahttp` cluster,
**`file_read` / `file_write`** (`hirarafs/`), **`decode` / `hash` /
`jwt_inspect` / `jwt_decode`** (`hirarautil/`), **`database_query` /
`database_schema`** (`hiraradb/`), **`application_logs` / `process_list` /
`environment_read`** (`hiraraops/`), and the full **`hirarahttp`** cluster
(including **`request_replay` / `parameter_test` / `response_compare`**) are
shipped, plus **`html_to_pdf`** (`hirarapdf/`), the fourteen
**`audio_*`** tools (`hiraraaudio/`) and the twenty-seven agent essentials
(#46–72: files and archives, time and schemas, link and page watching,
secrets, background jobs, email, data / charts / diagrams, video / image /
barcodes, and memory / human approval / reminders).

## Engineering conventions (all tools)

Same patterns as the rest of Hirara:

- Self-hosted, no third-party API keys.
- URL fetches go through [`hirara-core`](hirara-core/) (resolve-then-pin, redirect re-validation).
- Errors return in the JSON envelope (`"error": …`), not as HTTP 5xx.
- Hub registration: `hirara-hub` `DEFAULT_PORTS` + `TOOLS`, plus compose `HUB_*_URL`.
- Local SDK: `hirara.backends` entry point with `TOOL_NAMES` / `call_tool` / `tool_schemas`.

<div align="center">

# hirara

**The Python client for the [Hirara](https://github.com/lucasdmarshall/Hirara) self-hosted agent tool hub.**

Call web search, PDF, OCR, code execution, and Office-document tools like
functions — against a hub you run. Built-in tools require no third-party API
keys. External MCP connectors use provider authentication when required.
See [connector setup and examples](../docs/connectors.md).

[![PyPI](https://img.shields.io/pypi/v/hirara.svg)](https://pypi.org/project/hirara/)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)

</div>

---

```bash
pip install hirara
```

```python
import hirara
hirara.configure("http://localhost:8080")          # or set HIRARA_HUB_URL

hirara.web_search("rust borrow checker", max_results=5)
hirara.pdf_read(path="report.pdf")                  # client reads + base64s the file for you
hirara.office_read(path="deck.pptx")["markdown"]
hirara.execute_code("python", "print(sum(range(10)))")
hirara.ocr_read(path="scan.png", languages=["en"])
```

Or an explicit client (multiple hubs, threads, custom timeout):

```python
from hirara import Client
hub = Client("http://localhost:8080", token="…")    # or HIRARA_HUB_TOKEN
hub.form_extract(path="invoice.pdf")["fields"]
```

---

## It talks to a running hub

`hirara` is a **thin client** — it does not bundle the tools (some need Docker,
SearXNG, or heavy models). It forwards calls to a running **[Hirara hub](https://github.com/lucasdmarshall/Hirara)**,
which you self-host:

```bash
docker compose -f docker-compose.hub.yml up -d --build
```

`pip install hirara` + a hub running = tools that work. No hub, no results.

---

## Nice touches

- **Local files just work.** Pass `path=` and the client reads the file and
  sends it as base64 — so it works even when the hub has no access to your disk
  (the default for a networked hub). Or pass `url=` / `base64=`.
- **Errors are exceptions.** A tool that reports a problem (blocked URL, bad
  input) raises `HiraraToolError`; an unreachable hub or bad token raises
  `HiraraError`. Pass `raise_on_error=False` to `call()` to get the raw dict.
- **Discovery.** `hirara.tools()` returns the hub's aggregated tool schemas;
  `hirara.health()` reports which backends are up.
- **Auth.** Set a token (arg or `HIRARA_HUB_TOKEN`) and it's sent as a bearer
  header — needed only when the hub is exposed on a network.

---

## Tools

| Method | Tool |
|---|---|
| `web_search(query, …)` · `web_fetch(url, …)` | web |
| `pdf_read(...)` · `pdf_info(...)` · `pdf_create(content, …)` · `html_to_pdf(html, …)` | PDF |
| `ocr_read(...)` · `form_extract(...)` | OCR / forms |
| `office_read(...)` | Word / PowerPoint / Excel |
| `transcribe(...)` | speech to text |
| `execute_code(language, code, …)` | sandboxed code |
| `dns_lookup` · `port_scan` · `service_enum` | network |
| `http_request` · `http_history` · `inspect_*` · `directory_enum` | HTTP |
| `request_replay` · `parameter_test` · `response_compare` | replay / compare |
| `file_read(path, …)` · `file_write(path, content, …)` | filesystem (hub/local path) |
| `decode(input, format=…)` · `hash(input, algorithms=…)` | encodings / digests |
| `jwt_inspect(…)` · `jwt_decode(…)` | JWT header / payload |
| `database_query(sql, …)` · `database_schema(…)` | SQLite query / schema |
| `application_logs(…)` · `process_list(…)` · `environment_read(…)` | logs / processes / env |
| `audio_info` · `audio_profile` · `audio_check` · `audio_fix` | describe / judge / repair audio |
| `audio_compare` · `audio_find` · `audio_fingerprint` | verify edits, find clips, duplicates |
| `audio_split` · `audio_tighten` · `audio_spectrogram` · `audio_tones` | edit at pauses, image, DTMF / hum |
| `audio_speak(text, …)` · `audio_sonify(values, …)` · `audio_watch(action, …)` | TTS, data to sound, stream monitor |
| `file_edit(path, old, new, …)` · `file_search(pattern, …)` · `file_list(path, …)` | edit / grep / list (backend path) |
| `archive_list(path)` · `archive_extract(path, dest)` | zip / tar, safely |
| `time_now(timezones)` · `date_calc(operation, …)` · `schema_validate(instance, schema)` | time, dates, JSON Schema |
| `link_check(url)` · `site_map(url)` · `web_watch(url, action=…)` · `secret_list()` | site checks, page diffs, secrets |
| `job_start(language, code, …)` · `job_status(job_id)` · `job_stop(job_id)` | background sandbox jobs |
| `email_read(...)` | .eml / .msg / mbox |
| `data_profile(...)` · `chart_render(type, …)` · `diagram_render(source, …)` | data, charts, diagrams |
| `video_profile(...)` · `image_compare(...)` · `barcode_read(...)` · `qr_generate(data)` | video, image diff, barcodes |
| `memory(action, …)` · `ask_human(action, …)` · `schedule(action, …)` · `wait_until(…)` | agent state and human approval |
| `call(name, arguments)` | any tool, raw |

File tools like PDF/OCR accept `path=` (local, auto-base64), `url=`, or `base64=`.
`file_read` passes `path=` through to the backend (reads the hub or local process filesystem),
and so do the `file_*` / `archive_*` tools, `audio_fingerprint`'s paths and any
`output_path` / `output_dir`.

---

## Environment

| Variable | Purpose |
|---|---|
| `HIRARA_HUB_URL` | Hub base URL (default `http://localhost:8080`) |
| `HIRARA_HUB_TOKEN` | Bearer token, if the hub requires auth |

---

## Testing

```bash
pip install -e ".[dev]"
pytest -q
```

The suite drives the client against a mock hub (httpx `MockTransport`):
argument forwarding, `path=` → base64, one-source validation, error-to-exception
mapping, auth headers, and discovery.

---

## License

Apache License 2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE).

Copyright 2026 Lucas D Marshall (Kaung Myat San).

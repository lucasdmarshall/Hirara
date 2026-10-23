<div align="center">

# HiraraReader

**Self-hosted Office-document and email reader for AI agents — docx, pptx, xlsx, eml, msg, mbox → text. No API keys.**

Part of the [Hirara](https://github.com/lucasdmarshall/Hirara) tool hub.
Pure-Python — [python-docx](https://github.com/python-openxml/python-docx),
[python-pptx](https://github.com/scanny/python-pptx), and
[openpyxl](https://foss.heptapod.net/openpyxl/openpyxl). URL fetches route
through the hub's shared SSRF guard, [`hirara-core`](../hirara-core/).

[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![MCP](https://img.shields.io/badge/MCP-compatible-8A2BE2.svg)](https://modelcontextprotocol.io/)

</div>

---

## Email: `email_read`

`email_read` takes an `.eml`, an Outlook `.msg` (needs the `msg` extra:
`pip install "hirarareader[msg]"`, included in the Docker image) or an mbox
mailbox and returns, per message: from / to / cc / reply-to, subject, date,
message ids, the readable body (HTML turned into text, scripts dropped), every
link, `Authentication-Results` and the number of `Received` hops, and the
attachments with size and SHA-256. Word / PowerPoint / Excel and text
attachments are read in place. Nothing in a message is fetched or executed.

```bash
curl -X POST localhost:8500/email_read -H 'content-type: application/json' \
  -d '{"file_path":"/data/invoice.eml"}'
```

## One tool, three formats

`office_read` takes a Word, PowerPoint, or Excel file and returns clean
**markdown** (plus the plain text). The format is **auto-detected from the file
contents** — they are all ZIP containers, told apart by what's inside — so the
agent never has to pick; it just says "read this file."

| Format | What comes out |
|---|---|
| **`.docx`** | Headings (`#`), bullet lists (`-`), and tables preserved as markdown |
| **`.pptx`** | Per-slide text under `## Slide N`, plus speaker notes |
| **`.xlsx`** | One markdown table per sheet, under `## Sheet: <name>` |

It pairs with the hub's other readers: [`hirarapdf`](../hirarapdf/) for PDFs
and [`hiraraocr`](../hiraraocr/) for images and scans. This one owns the Office
formats.

> Legacy binary formats (`.doc` / `.xls` / `.ppt`) are recognized and rejected
> with a clear message — save as the modern OOXML format instead.

---

## Quick start

```bash
pip install -e ../hirara-core        # shared SSRF guard (repo-local)
pip install -e ".[service,mcp]"
```

As an HTTP service:

```bash
uvicorn hirarareader.service:app --host 127.0.0.1 --port 8500
```

**Read** a document (base64, path, or URL) → markdown + text:

```bash
curl -X POST localhost:8500/office_read -H 'content-type: application/json' \
  -d '{"file_path":"/path/to/report.docx"}'
```

Or upload it directly:

```bash
curl -X POST localhost:8500/office_read/upload -F file=@deck.pptx
```

As an MCP server over stdio (Claude Desktop / Cursor / agent runtimes):

```bash
python -m hirarareader.mcp_server
```

With Docker (loopback-bound, nothing to download at boot):

```bash
docker compose up -d --build
```

---

## API

| Endpoint | Purpose |
|---|---|
| `POST /office_read` | Read one document. `file_path` / `file_url` / `file_base64`, `filename` |
| `POST /office_read/upload` | Same, multipart file upload |
| `GET /schemas` | Tool definition, ready for an LLM `tools` array |
| `GET /health` | Liveness + supported formats |

Response carries `kind` (`docx`/`pptx`/`xlsx`), `markdown`, `text`, `meta`
(paragraph/slide/sheet counts), `truncated`, `source`, and `error`. Errors come
back in the body, not as HTTP status codes: the caller is an agent loop, and
"unrecognized document" is a result to reason about.

---

## Security

- **`file_url` is off by default.** When enabled (`CRDR_ALLOW_URL_FETCH=true`),
  the fetch goes through `hirara-core`'s `safe_download` — resolve-then-pin,
  every redirect hop re-validated, streamed under a byte cap — never a bare
  `httpx.get`.
- **Local file access is gated.** `file_path` lets a caller name any file on the
  host; fine for a local/MCP server, **off in the Docker image**. Set
  `CRDR_ALLOW_LOCAL_PATH=true` only for a trusted, local deployment.
- **Everything is size-capped** — input by `CRDR_MAX_BYTES`, output by
  `CRDR_MAX_CHARS` (flags `truncated`), spreadsheet rows by `CRDR_MAX_ROWS`.

---

## Configuration

All via environment variable.

| Variable | Default | Notes |
|---|---|---|
| `CRDR_MAX_BYTES` | `26214400` | Cap on an input file (25 MB) |
| `CRDR_MAX_CHARS` | `500000` | Cap on output text/markdown; flags `truncated` |
| `CRDR_MAX_ROWS` | `2000` | Per-sheet row cap for spreadsheets |
| `CRDR_ALLOW_URL_FETCH` | `false` | Enable `file_url` (through the SSRF guard) |
| `CRDR_ALLOW_LOCAL_PATH` | `true` (lib) / `false` (image) | `file_path` reads |

---

## Testing

```bash
pip install -e ".[dev]"
pytest -q
```

The suite builds tiny real `.docx`/`.pptx`/`.xlsx` files in memory and reads
them back — so it exercises the actual libraries end-to-end, no fixtures checked
in. Verified on a live server: all three formats read to the expected markdown.

---

## License

Apache License 2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE).

Copyright 2026 Lucas D Marshall (Kaung Myat San).

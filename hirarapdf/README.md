<div align="center">

# Hirarapdf

**Self-hosted PDF tools for AI agents — read, parse, and create. No API keys.**

Part of the [Hirara](https://github.com/lucasdmarshall/Hirara) tool hub.
Pure-Python: [pypdf](https://github.com/py-pdf/pypdf) reads,
[reportlab](https://www.reportlab.com/) writes. URL fetches route through the
hub's shared SSRF guard, [`hirara-core`](../hirara-core/).

[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![MCP](https://img.shields.io/badge/MCP-compatible-8A2BE2.svg)](https://modelcontextprotocol.io/)

</div>

---

## Four tools

| Tool | Role | What it does |
|---|---|---|
| **`pdf_read`** | reader | Full text + per-page text + metadata out of a PDF |
| **`pdf_info`** | parser | Structure only — page count, metadata, outline, form fields, page sizes |
| **`pdf_create`** | maker | A real, paginating PDF from Markdown, plain text, or HTML |
| **`html_to_pdf`** | designer | HTML + CSS to PDF, with images you embed (resumes, CVs) |

`pdf_info` is the cheap "what is this file" call — use it to decide *whether* or
*how* to read a large or unfamiliar PDF before paying to extract every page.

---

## Quick start

```bash
pip install -e ../hirara-core        # shared SSRF guard (repo-local)
pip install -e ".[service,mcp]"
```

As an HTTP service:

```bash
uvicorn hirarapdf.service:app --host 127.0.0.1 --port 8200
```

**Read** a PDF's text (base64, path, or URL):

```bash
curl -X POST localhost:8200/pdf_read -H 'content-type: application/json' \
  -d '{"pdf_path":"/path/to/report.pdf"}'
```

Or upload it directly:

```bash
curl -X POST localhost:8200/pdf_read/upload -F file=@report.pdf
```

**Inspect** structure without extracting all the text:

```bash
curl -X POST localhost:8200/pdf_info -H 'content-type: application/json' \
  -d '{"pdf_path":"/path/to/report.pdf"}'
```

**Create** a PDF from Markdown — returns `pdf_base64`, or writes to `output_path`:

```bash
curl -X POST localhost:8200/pdf_create -H 'content-type: application/json' \
  -d '{"content":"# Hello\n\n- one\n- two","title":"Demo","output_path":"out.pdf"}'
```

As an MCP server over stdio (Claude Desktop / Cursor / agent runtimes):

```bash
python -m hirarapdf.mcp_server
```

With Docker (loopback-bound, nothing to download at boot):

```bash
docker compose up -d --build
```

---

## The maker's input formats

`pdf_create` accepts three `format`s, all rendered **pure-Python** on top of
reportlab — no browser engine, no cairo/pango system libraries, the usual way
"HTML to PDF" balloons a container.

**`markdown`** — a lightweight subset, deliberately *not* full CommonMark:
`#`/`##`/`###` headings, `-`/`*` bullet lists, `1.` numbered lists,
```` ``` ```` fenced code blocks, and inline `**bold**`, `*italic*`, `` `code` ``.
Not supported: tables, images, nested blockquotes. User content is XML-escaped
*before* the inline markup is applied, so a document that literally contains
`<script>` or `&` renders as text, not broken markup.

**`text`** — plain text; blank lines separate paragraphs. No markup at all.

**`html`** — a practical subset of HTML + CSS, rendered by
[xhtml2pdf](https://github.com/xhtml2pdf/xhtml2pdf): headings, paragraphs,
lists, **tables**, images, and simple inline/`@page` CSS. It is not a modern
layout engine — JavaScript, flexbox and grid do not apply, so feed it
document-style HTML. A bare fragment is wrapped in a minimal document (so
`title`/`author`/`subject` reach the PDF metadata); a full `<html>` document is
passed through and controls its own `<head>`.

```bash
curl -X POST localhost:8200/pdf_create -H 'content-type: application/json' \
  -d '{"format":"html","content":"<h1>Invoice</h1><table><tr><td>A</td><td>1</td></tr></table>","title":"Invoice"}'
```

## HTML to PDF

`html_to_pdf` is the document designer: an agent writes HTML and CSS and gets
a PDF back. Use it for resumes, CVs, and one-page layouts. Images are PNG,
JPEG, or GIF, passed as base64 in `images` (referenced by filename) or as a
`data:image` URI. Remote `http(s)` and `file` URLs in the HTML are rejected.

CSS that works is document styling: fonts, color, margins, borders, tables.
JavaScript, flexbox, and grid do not apply.

```bash
curl -X POST localhost:8200/html_to_pdf -H 'content-type: application/json' \
  -d '{"html":"<h1>Ada Lovelace</h1><p class=\"role\">Mathematician</p><img src=\"photo.png\" width=\"80\" height=\"80\"/>","css":"h1{color:#1a365d} .role{color:#444}","images":{"photo.png":"<base64>"},"title":"CV"}'
```

---

## Security

This tool turns attacker-influenceable bytes into and out of PDFs, so three
levers matter:

**`pdf_url` is off by default.** When you enable it
(`CPDF_ALLOW_URL_FETCH=true`), the fetch goes through `hirara-core`'s
`safe_download` — resolve-then-pin, every redirect hop re-validated, streamed
under a hard byte cap — so a public URL that `302`s to `169.254.169.254` is
rejected at the hop. It is never a bare `httpx.get`.

**Local filesystem access is gated.** `pdf_path` (read) and `output_path`
(write) let a caller name any path on the host. Fine for a local MCP server or a
loopback service you trust; **off in the Docker image** because a
network-exposed service should not read or write arbitrary files. Set
`CPDF_ALLOW_LOCAL_PATH=true` only for a trusted, local deployment.

**Everything is size-capped.** Input PDFs are bounded by `CPDF_MAX_BYTES`,
extracted text by `CPDF_MAX_CHARS` (the result flags `truncated=true`), and
`pdf_create` input by `CPDF_MAX_CREATE_CHARS`.

Errors come back in the response body, not as HTTP status codes — the caller is
an agent loop, and "PDF too large" is a result to reason about, not a transport
failure. Every response carries the same keys whether it succeeded or failed.

> **Note — no OCR.** `pdf_read` extracts a PDF's embedded text layer. A scanned
> PDF that is just images with no text layer comes back with little or no text.
> OCR is a separate concern (and a candidate for a future hub tool).

---

## API

| Endpoint | Purpose |
|---|---|
| `POST /pdf_read` | Extract text. `pdf_path` / `pdf_url` / `pdf_base64`, `password`, `include_pages` |
| `POST /pdf_read/upload` | Same, multipart file upload |
| `POST /pdf_info` | Structure only. Same sources |
| `POST /pdf_info/upload` | Same, multipart file upload |
| `POST /pdf_create` | Build a PDF. `content`, `format`, `title`, `author`, `subject`, `page_size`, `output_path` |
| `POST /html_to_pdf` | HTML + CSS to PDF. `html`, `css`, `images`, `title`, `author`, `subject`, `page_size`, `output_path` |
| `GET /schemas` | Tool definitions, ready for an LLM `tools` array |
| `GET /health` | Liveness + effective config |

---

## Configuration

All via environment variable.

| Variable | Default | Notes |
|---|---|---|
| `CPDF_MAX_BYTES` | `26214400` | Cap on an input PDF (25 MB) |
| `CPDF_MAX_CHARS` | `200000` | Cap on extracted text; result flags `truncated` |
| `CPDF_ALLOW_URL_FETCH` | `false` | Enable `pdf_url` (through the SSRF guard) |
| `CPDF_URL_TIMEOUT` | `30` | Seconds for a URL fetch |
| `CPDF_ALLOW_LOCAL_PATH` | `true` (lib) / `false` (image) | `pdf_path` read + `output_path` write |
| `CPDF_PAGE_SIZE` | `A4` | Default page size for `pdf_create` |
| `CPDF_MAX_CREATE_CHARS` | `500000` | Cap on `pdf_create` / `html_to_pdf` input length |
| `CPDF_MAX_HTML_IMAGES` | `24` | Cap on images in one `html_to_pdf` call |
| `CPDF_MAX_HTML_IMAGE_BYTES` | `8000000` | Cap on decoded image bytes per call |

---

## Testing

```bash
pip install -e ".[dev]"
pytest -q
```

The suite roundtrips through both engines — the maker builds a PDF, the reader
reads it back — so no binary fixtures are checked in. It also proves `pdf_url`
routes through the shared SSRF guard and surfaces a block as an error envelope
rather than an exception.

---

## License

Apache License 2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE).

Copyright 2026 Lucas D Marshall (Kaung Myat San).

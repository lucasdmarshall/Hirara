# Documents, public search, weather and symbolic math

These tools use Rust implementations in `hirara-native` 0.2. Python remains the
existing SDK/HTTP/MCP transport and permission layer. No LangChain, LlamaIndex,
Python CAS, model-selected endpoint or executable expression language is added.

Install from this checkout with a stable Rust toolchain and C linker:

```sh
python -m pip install './hirara-native[pdf]'
python scripts/install_dev.py --sdk
```

Source builds fetch a pinned Gyrfalcon Git dependency. Compiled wheels do not
fetch source or models at runtime. The `pdf` extra installs PDFium's shared
library through `pypdfium2`; Rust performs the extraction. Configure `GYR_PDFIUM`
instead if you already provision that library. Install it before starting the
service; restart after changing native libraries.

## Document collections

`document_index`, `document_search` and `document_remove` live in **hirarafs**.
Gyrfalcon is pinned at
[`c4851100aa8f21e20395be3f59120dd8459ed622`](https://github.com/lucasdmarshall/Gyrfalcon/tree/c4851100aa8f21e20395be3f59120dd8459ed622).
Upstream updates do not change Hirara until this revision is deliberately updated
and its compatibility tests pass. Never follow a moving branch at deployment time.

Configure collection names and model files on the server:

```sh
export CRAG_COLLECTIONS='{"default":"/indexes/personal","work":"/indexes/work"}'
export CRAG_MODEL_DIR=/models/potion-retrieval-32M
export CRAG_TIER=lite
export CFS_ROOTS=/data
export CFS_ALLOW_ANY_PATH=false
```

`CRAG_MODEL_DIR` is the actual model directory, not its parent. Lite expects
`model.safetensors`, `tokenizer.json` and optionally `config.json` for the
Model2Vec potion model. Full expects the BGE model/tokenizer and a separately
provisioned ONNX Runtime library (`ORT_DYLIB_PATH`). See Gyrfalcon's
[model provisioning instructions](https://github.com/lucasdmarshall/Gyrfalcon/blob/c4851100aa8f21e20395be3f59120dd8459ed622/docs/getting-started/installation.md#models).
Provision models through an operator-controlled process; Hirara never downloads
them on behalf of a tool request. Treat model files as trusted, immutable data,
and rebuild a collection when changing its model or tier.

```python
import hirara

hirara.document_index(path="/data/handbook.pdf", doc_id="handbook")
hits = hirara.document_search("how do I request leave?", max_results=5)

# Reusing a document id atomically replaces its chunks and metadata.
hirara.document_index(
    text="Extracted Office, OCR, notes or other text.", doc_id="note-1",
    source="team notes", collection="work", metadata={"team": "infra"},
)
hirara.document_search("infrastructure", collection="work", filter={"team": "infra"})
hirara.document_remove("note-1", collection="work")
```

Path ingestion accepts PDF, HTML, UTF-8 text and Markdown-like formats. It uses
the existing CFS root permissions, refuses symlink leaves and reads at most
`CFS_MAX_BYTES`. PDFs are limited to 200 pages; extracted/provided text is capped
by `CRAG_MAX_INPUT_BYTES` (default 2 MB). Scanned PDFs need existing `ocr_read`
first; Office files need `office_read`. Pass their extracted text with a stable
`doc_id`. No automatic directory walk, OCR or background ingestion is introduced.

Search returns at most 20 chunks with `doc_id`, stable `chunk_id`, `text`, `score`,
`source`, `page`/`page_end` for PDFs, UTF-8 byte offsets `start`/`end`, and metadata.
PDF page numbers refer to the extracted text; a chunk may span pages. Offsets
refer to indexed text, not bytes of the original PDF/HTML. Plain text has no page
number. Scores are comparable within one query only. Results are untrusted data;
the calling LLM can build an answer with citations. Hirara does not generate an
answer or claim that an uploaded source label certifies document authenticity.

Metadata filters AND different keys and OR the values within a key's list.
An empty list matches nothing. Metadata accepts strings, numbers, booleans and
lists of those values; Gyrfalcon stores them as text. Keys beginning
`__hirara_` are reserved for source/page information and cannot be supplied by a
request. Metadata filters are not access control.

Only named, administrator-configured collection paths are accepted. A configured
collection grants access to its indexed copies, even if an original file is later
moved or its source root is changed. Remove/reindex copies when revoking data.
`CRAG_ALLOW_WRITE=false` disables index/remove while retaining search. This is
separate from source-file mutation permission; search still needs the engine's
collection lock and may maintain index internals. Keep index storage writable.

One process owns a collection at a time. Use one hirarafs worker for these tools;
other processes should call its HTTP/MCP interface instead of opening the same
directory. Handles are reused, writes are durable through Gyrfalcon's WAL, and
shutdown flushes and closes handles. At most 32 collections may be configured/open.
Do not run the upstream CLI against a collection held by the service. Index and
model directories must be trusted; keep them outside `CFS_ROOTS` so source-file
write tools cannot corrupt them. New collection directories use mode 0700 on
Unix; existing directory permissions are retained.

The default models target English. Unicode text is accepted, but Burmese and
other-language semantic quality needs a separately evaluated multilingual model
and adapter support. The offline tests use a tiny known embedding table to test
semantic ranking without lexical overlap, filters, persistence and replacements;
they are not a benchmark of production-model retrieval quality.

### Compose

Full hub/image stacks and standalone hirarafs pass `CRAG_*` configuration through.
They mount writable `rag-indexes:/indexes` separately from source files and
read-only `rag-models:/models`. Set `CRAG_COLLECTIONS` and `CRAG_MODEL_DIR` only
after provisioning models. To use a host model directory, merge an override:

```yaml
services:
  hirarafs:
    environment:
      CRAG_COLLECTIONS: '{"default":"/indexes/personal"}'
      CRAG_MODEL_DIR: /models/potion-retrieval-32M
    volumes:
      - /opt/gyrfalcon-models:/models:ro
```

The filesystem Docker image installs PDFium. Models are never baked into images.
Existing stacks without collection configuration retain their normal file tools.

## Stack Exchange and books

Both tools live in the existing **web service** and work independently of SearXNG.

```python
hirara.stackexchange_search("Rust lifetime error", max_results=5)
hirara.stackexchange_search("SSH permissions", site="serverfault", include_answers=False)
hirara.books_search("intitle:Rust inauthor:Klabnik", max_results=5, start=0)
```

Stack Exchange returns question text, score, tags, author/source links and accepted
answer text when available. Code blocks preserve indentation separately; text/code
truncation is flagged. `page` is 1–100 and `max_results` is 1–20.
`answers_complete=false` reports an unavailable accepted answer or a backoff that
prevented its retrieval. An answer-request failure returns an error rather than
silently claiming a complete result. Provider backoff is enforced per process and
event loop before another Stack Exchange search. Quota/backoff values are returned.
Preserve author/source attribution when using Stack Exchange content.

Books returns title, authors, publisher, publication date, ISBN/other identifiers,
description, language, page count and a canonical Google Books URL. `start` is
0–1000 and `max_results` is 1–20. It does not download or return full books.

Public endpoints can throttle or reject anonymous traffic; such failures are
explicit errors, not empty successful searches. These adapters do not accept API
keys, credentials or endpoint overrides from the model.

## Weather

```python
hirara.weather("Yangon", forecast_days=3)
hirara.weather(latitude=16.8, longitude=96.1, units="imperial", forecast_days=5)
```

Provide a location **or** both coordinates. Location lookup selects the first
Open-Meteo/GeoNames match and reports the resolved location and alternatives;
use coordinates for precision. The result includes current conditions, 1–7 days
of forecast, units, local timezone, UTC offset and attribution. Metric means
Celsius, km/h and mm; imperial means Fahrenheit, mph and inches. Forecasts are
provider estimates and include their timestamps. Weather cache entries expire
within five minutes. Open-Meteo's public endpoint has usage limits and terms,
including commercial-use conditions; evaluate those before production use.

All three public tools use fixed HTTPS endpoints through the existing DNS-pinned
SSRF guard. Redirects/private targets are refused, responses capped at 2 MB and a
whole operation bounded to 50 seconds. Requests share search session budgets;
cache misses reserve budget before awaiting HTTP, including failed attempts.
Cache hits are free. Successful question/book links join the same session's URL
provenance registry. Multiple workers must coordinate aggregate provider usage.

## Symbolic math

`symbolic_math` lives in **hirarautil**, using pinned `tpt-math-symbolic` 0.2.0
(MIT/Apache-2.0). It has no network, file, process or code-evaluation capability.

```python
hirara.symbolic_math("simplify", "2*x + 3*x")
hirara.symbolic_math("differentiate", "x^3 + sin(x)", variable="x", order=1)
hirara.symbolic_math("evaluate", "sin(pi/2) + x^2", variables={"x": 3})
hirara.symbolic_math("solve", "x^2 - 5*x + 6 = 0", variable="x")
```

Supported operations are simplification, derivatives of order 1–3, finite numeric
evaluation, and real roots of one-variable linear/quadratic polynomials. Inputs
use explicit multiplication, ASCII variable names, ordinary decimal literals,
`pi`/`e`, powers with integer exponents 0–32, and unary functions `sin`, `cos`,
`tan`, `exp`, `ln`, `sqrt`, inverse trig and hyperbolic functions. General symbolic
exponents, integration, complex roots and arbitrary scientific natural-language
queries are not implemented; unsupported operations return errors.

Trigonometric functions use radians.

Results include expression text, LaTeX and `precision: "f64"`; decimal/transcendental
results are approximate. Original domain restrictions remain relevant after
algebraic simplification, such as `x/x` requiring nonzero `x`. Evaluation uses the
original expression and rejects unbound variables, division by zero and non-finite
results. Expression length, AST depth/node count, derivative order, nested powers
and output size are bounded. This tool is not an exact proof system.

## Verification

Existing `scripts/test_all.py`, Rust unit tests and native stdio MCP checks include
these tools. API tests use fixtures; live external provider availability and
production model quality are separate from deterministic regression tests.

CI builds the release wheel once and reuses it across package and Python-version
tests. With a compatible wheel already installed, `scripts/install_dev.py --sdk
--skip-native` installs matching Python adapters without recompiling Rust.

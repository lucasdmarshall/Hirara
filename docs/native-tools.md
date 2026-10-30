# Rust tools

The optional `hirara-native` package implements file mutations, JSON queries,
research query construction/parsing, and PostgreSQL/MySQL access in Rust. The
existing Python SDK, HTTP services and MCP servers provide their usual interfaces
and apply `HIRARA_ALLOWED_TOOLS`. SQLite and all existing tools keep working
without this package. Missing native support returns an installation error; there
is no runtime build, download, or silent fallback to another implementation.

## Install from this checkout

Install a stable Rust toolchain and a C linker, activate your Python environment,
then run:

```sh
python -m pip install ./hirara-native
python scripts/install_dev.py --sdk
```

`scripts/install_dev.py` also builds the local native package. Its first build
takes longer than the Python-only packages. The extension releases the GIL while
working. ABI3 wheels support CPython 3.11 and later; source installations need
Rust. Linux is the tested filesystem platform. The web, fs, util and db Dockerfiles
build and install the native wheel in a separate build stage, leaving the compiler
out of the runtime image. `Cargo.lock` records the tested Rust dependencies.

Published Python packages expose a `native` extra, for example
`pip install 'hirara[native]'`; use the source commands until that wheel is released.

## File copy, move, rename and delete

```python
import hirara

hirara.file_copy("/data/report.txt", "/data/report-copy.txt")
hirara.file_move("/data/report-copy.txt", "/data/archive/report.txt")
hirara.file_rename("/data/archive/report.txt", "report-old.txt")
hirara.file_delete("/data/archive/report-old.txt")
```

All four require `CFS_ALLOW_WRITE=true` and the existing `CFS_ROOTS` /
`CFS_ALLOW_ANY_PATH` permissions. Give an agent only the mutation tool names it
needs. Delete is permanent. Only regular files are accepted; no recursive folder
operations, symlink leaves, parent `..` traversal, or automatic parent creation.
Paths are capability-relative to allowed roots; symlinked parents cannot escape
the capability. Existing destinations are preserved unless `overwrite=True`.

Copies stage data before committing, enforce `CFS_MAX_WRITE_BYTES` while copying,
and leave the destination intact on failure. Copy does not preserve ownership,
timestamps or other metadata. Linux moves/renames use atomic no-clobber rename
unless overwrite is requested. Cross-filesystem moves return an error with the
source intact; use explicit copy followed by delete after checking the result.
On other Unix platforms a no-overwrite move uses link/unlink and can report a
partial move if source deletion fails. Concurrent hostile filesystem writers are
outside Hirara's single trusted operator threat model; separate workspaces remain
necessary for mutually untrusted tenants.

HTTP routes: `/file_copy`, `/file_move`, `/file_rename`, `/file_delete` on hirarafs.
Standalone stdio MCP and the hub expose the same tool names and arguments.

## JSON query

```python
hirara.json_query(
    {"items": [{"name": "a", "price": 2}, {"name": "b", "price": 9}]},
    "items[?price > `3`].name",
)  # result: ["b"]
hirara.json_query('{"a/b": [10, 20]}', "/a~1b/1", syntax="pointer")
# result: 20
```

`syntax="jmespath"` is the default; `syntax="pointer"` implements RFC 6901.
`input` accepts a JSON value or a string containing JSON. To query a scalar string,
pass its JSON representation, e.g. `'"hello"'`. Missing JMESPath properties produce
`null`; missing pointers produce an error, distinct from a property containing
`null`. Expressions are capped at 4096 bytes, input by `CUTIL_MAX_INPUT_CHARS`, and
serialized output by `CUTIL_MAX_OUTPUT_BYTES`. A result that is too large returns
an error instead of corrupting/truncating JSON. There is no Python/Rust evaluation,
filesystem access, network access, or custom executable query functions.

HTTP route: `/json_query` on hirarautil.

## Research search

```python
hirara.arxiv_search("ti:transformer AND cat:cs.CL", max_results=5, start=0)
hirara.pubmed_search("asthma[Title] AND 2025[Date - Publication]", max_results=5)
```

These use fixed public arXiv and NCBI endpoints and need neither a key nor SearXNG.
Both accept `query`, `max_results` (1–20) and `start` (0–10000; provider pagination
limits still apply). arXiv returns abstracts and canonical article/PDF URLs.
PubMed returns citation metadata and DOI, **not abstracts or full text**. Results
are untrusted third-party data. Use existing PDF/web tools to read a paper.

The Python transport reuses the shared DNS-pinned SSRF guard, caps each response
at 2 MB, refuses redirects and private targets, and applies a 50-second overall
deadline. Provider calls are spaced at least 3.1 seconds apart for arXiv and 0.4
seconds for NCBI in each process/event loop; multiple worker processes must
coordinate their combined usage externally. Searches share the existing search
cache TTL and session search budget. Successful result URLs are registered for
the same session's `web_fetch` provenance checks, including on cache hits. No
partial PubMed result is silently substituted when its summary request fails.

HTTP routes: `/arxiv_search`, `/pubmed_search` on the web service. HTTP clients can
pass the existing `session_id`; stdio MCP and the local SDK manage theirs.

## PostgreSQL and MySQL

Use administrator-configured named connections; requests never accept a network
DSN through `path=`. Existing SQLite paths, URLs and named databases still work.

```sh
export CDB_DATABASES='analytics=postgresql://reader:password@db.example/app?sslmode=verify-full,catalog=mysql://reader:password@mysql.example/app?ssl-mode=verify-identity'
export CDB_READONLY=true
```

Percent-encode reserved characters in credentials, including commas and `@`.
Keep DSNs in secret configuration; they are not returned in results or health.
Configured database endpoints are an explicit administrator network grant; they
are not fetched through the public-HTTP SSRF guard. Use network controls to restrict
the database service to the configured servers. `HIRARA_ALLOW_PRIVATE_IPS` governs
public HTTP tools, not these explicitly configured SQL connections.

```python
hirara.database_query(
    "SELECT id, name FROM customers WHERE id = $1", database="analytics", params=[42]
)
hirara.database_query(
    "SELECT id, name FROM products WHERE id = ?", database="catalog", params=[42]
)
hirara.database_schema(database="analytics", table="customers", include_indexes=True)
```

Network params are positional lists of JSON scalars: PostgreSQL uses `$1`, `$2`,
and MySQL uses `?`. SQLite still accepts both lists and named objects. Use explicit
SQL casts for strings representing date/time, UUID or other specialized types.
Results serialize dates as strings, decimals as strings, JSON as JSON, and binary
values as `{"__type__":"bytes","base64":"..."}`. Unsupported result types return
an error asking for a text cast. Row/table requests cannot exceed `CDB_MAX_ROWS`;
network query results also stop at 2 MB of serialized field data. A database may
still send a large individual value before that output cap is evaluated.

Read-only calls accept query statements and use a server read-only transaction;
requests cannot relax `CDB_READONLY=true`. Transaction/session control, COPY and
administrative statements are rejected even in write mode. SQL parsing is a
compatibility constraint, not a substitute for database authorization. Use a
dedicated least-privilege database role: no superuser, FILE, dangerous functions,
external network extensions or security-definer escape paths. Read-only
transactions do not sandbox the side effects of privileged server functions.

`CDB_TIMEOUT` bounds the complete native operation (up to 300 seconds); PostgreSQL
also gets a transaction-local statement timeout. A dropped client does not prove
that server work stopped, particularly MySQL writes. Timeout/connection loss can
leave a write outcome unknown: inspect state before retrying. MySQL DDL can commit
implicitly. No automatic write retry is performed.

Schema inspection returns current-schema tables/views, columns, primary keys and
optional indexes/foreign keys. Network `include_sql=true` currently returns
`sql: null`; SQLite keeps returning CREATE SQL. Index details are provider-specific.

## Verification

```sh
cargo fmt --manifest-path hirara-native/Cargo.toml --check
cargo clippy --manifest-path hirara-native/Cargo.toml --locked --all-targets -- -D warnings
cargo test --manifest-path hirara-native/Cargo.toml --locked
python scripts/test_all.py
```

`integration/test_native_databases.py` uses disposable PostgreSQL 17 at
`127.0.0.1:15432` and MySQL 8.4 at `127.0.0.1:13306`, database `hirara`, with
test-only administrator password `hirara-test`. With those services running:

```sh
HIRARA_DATABASE_INTEGRATION=1 python -m pytest -q integration/test_native_databases.py -o asyncio_mode=auto
```

CI starts these services and exercises both drivers. Unit research tests use
recorded-shaped fixtures and mocked HTTP, keeping network failures out of the
normal test suite.

# External MCP connectors

Hirara can discover external MCP servers, request human approval, retain
credentials across chats and restarts, list permitted tools, and call those
tools. The connection runtime, catalog adapters, OAuth and encrypted persistence
are Rust in `hirara-connectors/`; the existing Python SDK and hub are thin
transports.

## Run locally

Use the current stable Rust toolchain and the repository's normal Python development setup.
From the repository root:

```sh
cargo build --locked --manifest-path hirara-connectors/Cargo.toml
hirara-connectors/target/debug/hirara-connectors init .connector-secrets
export HCONNECT_CLIENTS_FILE="$PWD/.connector-secrets/clients.json"
export HCONNECT_ADMIN_TOKEN_FILE="$PWD/.connector-secrets/admin-token"
export HCONNECT_KEY_FILE="$PWD/.connector-secrets/vault-key"
export HCONNECT_STORE_DIR="$PWD/.hirara-connectors"
export HCONNECT_PUBLIC_URL=http://127.0.0.1:9700
hirara-connectors/target/debug/hirara-connectors
```

`init` generates independent random client/admin credentials and a 256-bit vault
key. It refuses to overwrite an existing directory. Unix directories are 0700
and files 0600. It does not print tokens. Keep both secret and vault directories
outside every Hirara filesystem root, reader input root, code sandbox mount,
backup shared with agents, and source repository. `.gitignore` and
`.dockerignore` exclude the default paths.

In a second terminal, configure the existing hub:

```sh
export HIRARA_CONNECTOR_TOKEN_FILE="$PWD/.connector-secrets/hub-token"
export HUB_HIRARACONNECTORS_URL=http://127.0.0.1:9700
# Set HUB_TOKEN through your deployment secret configuration when exposing HTTP.
uvicorn hirara_hub.service:app --host 127.0.0.1 --port 8080
```

Alternatively set `HIRARA_CONNECTOR_TOKEN` from a secret manager. It never falls
back to `HIRARA_BACKEND_TOKEN`. Connector probing is disabled when no connector
credential is configured, preserving existing hub health behavior. Other tools
and local SDK backends continue to work without this service.

For MCP clients, run `python -m hirara_hub.mcp_server` with the same environment.
The hub advertises native connector argument schemas and attribution in its MCP
initialization instructions. The Rust service also exposes `/schemas` and seven
`POST /connector_*` endpoints to clients using its own bearer credential.

## Discover and connect

```python
from hirara import Client
h = Client("http://127.0.0.1:8080", local=False)

h.connector_search("github", source="official")
h.connector_search("github", source="cursor")
h.connector_search("notion", source="cursor_marketplace")
h.connector_search("notion", source="claude_directory")
h.connector_details("cursor", "github")

proposal = h.connector_connect(source="cursor", server_id="github")
# Or supply the provider's documented public HTTPS endpoint:
# proposal = h.connector_connect(endpoint="https://provider.example/mcp")
print(proposal["approval_url"])
```

Open the approval URL yourself. Check the owner, endpoint and intended service;
the catalog has not granted permission. Enter the operator approval token from
`admin-token` in the browser, choose authentication, and enter allowed tool names
from the provider documentation. A literal `*` explicitly permits all current
and future upstream tools. Named grants are preferable. Approval links are
single-use and expire after ten minutes. The token form does not echo secrets
and is excluded from caching and framing. Do not give the operator credential to
the agent or mount it in an agent-readable filesystem.

Authentication choices:

- **None:** for public servers.
- **Bearer token:** enter a provider token in the browser.
- **API key header:** enter the key and its provider-documented header name, such
  as `x-api-key`. Reserved routing/protocol headers are rejected.
- **OAuth:** authorize in the provider's browser flow. A pre-registered public
  client ID can be supplied; otherwise the SDK attempts supported dynamic client
  registration. Providers requiring a confidential client secret, platform-only
  credentials or a provider-approved app may need additional integration.

After browser approval:

```python
connection_id = proposal["connection_id"]
result = h.connector_connect(connection_id)
# For OAuth, open result["authorization_url"] and complete provider consent.
# Then call connector_connect again to verify the connection.

tools = h.connector_tools(connection_id)
# Pick an advertised tool name and arguments matching its inputSchema:
# h.connector_call(connection_id, "provider_tool_name", {"query": "example"})
h.connector_status(connection_id)
h.connector_status()  # only this owner's saved connections
```

`connector_connect(connection_id, reauthorize=True)` starts OAuth consent again
when needed. `connector_disconnect(connection_id)` removes local credentials;
it does not claim provider-side revocation. Revoke the app/token in the provider
account settings as needed. To change endpoint or tool grants in this release,
disconnect and approve a new connection.

## Persistence and ownership

`HCONNECT_STORE_DIR/vault.bin` encrypts connection records, bearer/API keys and
OAuth credentials with ChaCha20-Poly1305. The independent key comes from
`HCONNECT_KEY_FILE` (32 raw bytes or base64). Every write uses a fresh nonce,
authenticates the vault version, and atomically replaces and fsyncs the file.
An exclusive process lock prevents competing writers. Wrong keys, tampering,
corruption and storage failures fail closed; they do not reset the vault.
Back up the vault and protect the key separately. Losing either can require
reconnecting accounts. This release uses the encrypted file backend on local
machines too; OS Keychain/Secret Service integration is not implemented yet.

MCP sessions open on demand and close after the operation; account connections
remain saved. OAuth tokens refresh when expired if the provider allows it, and
refreshed credentials are persisted. Incomplete approval/OAuth handshakes are
in memory for ten minutes and must restart after service restart. A saved
connection survives changing chat sessions and restarting the service when the
same vault and key remain available. Status reports configuration, not a live
health guarantee.

`HCONNECT_CLIENTS_FILE` is a JSON object mapping strong bearer tokens (at least
32 characters) to stable owner names. Caller identity comes only from the
validated credential, never a tool argument. Owners cannot inspect or delete
one another's records. Different tokens can intentionally map to the same owner.
The operator credential is distinct and can approve connections for any owner.

**The current Hirara hub has one shared configured identity.** Everyone who can
use that hub's connector routes shares its configured connector account. Use one
hub per owner/trust boundary, or access the Rust service with separate owner
credentials. A shared hub token is not multi-user identity propagation. Protect
the hub and connector API with authentication, TLS and deployment access control.

## Catalog sources and metadata

| Source | Data | Limits |
| --- | --- | --- |
| `official` | Documented MCP Registry v0.1 JSON API | Name substring queries require at least three characters; optional publisher categories |
| `cursor` | Cursor's public `cursor/plugins` marketplace and per-plugin manifests | Repository subset, not the entire website; only plugins declaring MCPs are returned |
| `cursor_marketplace` | Cursor Marketplace's public HTML | May include skills-only plugins; dynamic/private entries may be absent |
| `claude_directory` | Claude's public connectors directory and detail HTML | Dynamic/private entries may be absent; page changes can break the adapter |

Results preserve source IDs, source URLs, available descriptions, categories,
logos/images, publisher/repository/version fields and raw JSON metadata.
HTML adapters preserve extracted metadata, links, structured JSON and detail
page text. They do not invent missing fields or promise undocumented private
APIs. Available fields differ by source. `connector_details` provides richer
metadata than a website listing card. Logos are URLs; Hirara does not download
or execute images/SVGs. Consumers must safely render untrusted metadata.

Use `limit` (1–50), `cursor` and the returned `next_cursor`. Category filtering
is over a provider page; follow the cursor even when a filtered page is empty.
There is no universal category taxonomy. Website search covers the publicly
rendered inventory, not an authenticated site's complete database. Cursor
repository pages fetch metadata with concurrency four and report unavailable
details explicitly. No source is silently replaced with another. Errors mean
unavailable/changed, not an empty successful catalog.

Only an explicitly published Streamable HTTP endpoint is proposed automatically.
Cursor website detail pages can resolve explicitly linked GitHub JSON MCP
configuration files (at most eight files, preserving their source URLs and raw
metadata). Commands/scripts are never fetched or executed. Website-only listings
without such configuration may require supplying the provider's documented endpoint.
Cursor/Claude install links and their existing tokens are not reusable Hirara
connections. An upstream marketplace review badge is not a Hirara endorsement.

Source references:

- [Official Registry API](https://github.com/modelcontextprotocol/registry/blob/main/docs/reference/api/official-registry-api.md)
- [Cursor public plugin manifests](https://github.com/cursor/plugins)
- [Cursor Marketplace](https://cursor.com/marketplace)
- [Claude connectors directory](https://claude.com/marketplace/connectors-plugins)
- [Official Rust MCP SDK](https://github.com/modelcontextprotocol/rust-sdk)

## Security and bounded behavior

The service supports public HTTPS Streamable HTTP servers. Private destinations,
HTTP URLs, embedded URL credentials, link-local/metadata addresses and redirects
are denied. DNS answers are checked at validation and connection time on direct
connections. The same egress policy handles catalog, OAuth discovery/token
requests and MCP traffic. TLS verification remains enabled.

Environment HTTP proxies remain supported. A CONNECT proxy resolves destination
DNS itself, outside the client's DNS resolver. With a proxy configured startup
therefore requires `HCONNECT_TRUST_PROXY=true`: set this only when the proxy
also enforces denial of private/metadata destinations and DNS rebinding. This
acknowledges an actual deployment requirement. URL validation remains active;
destination DNS checks are delegated to the proxy. In this mode every external
HTTPS request is forced through the configured HTTPS/ALL proxy, without a
`NO_PROXY` or direct-connection fallback. Configure CA trust normally for a TLS-inspecting proxy. The
managed development environment's destination allowlist must allow the registry,
marketplace, provider and OAuth hosts before live integration can work.

`HIRARA_ALLOWED_TOOLS` is enforced on both the service and hub. Per-connection
allowed upstream tool names are checked again before execution. Tool arguments
are validated against the advertised input schema with no external schema
fetching. Upstream sampling, roots, elicitation and arbitrary callbacks are not
advertised. Credentials never appear in connector results or approval HTML.
Upstream descriptions/results remain untrusted and may contain prompt injection.

There are 256 saved connections, 128 pending approvals/authorizations, 16
concurrent agent operations, 1 MiB input bodies, 4 MiB upstream responses/streams
and tool catalogs, 64 KiB executable tool schemas, at most 1,000 tools/20 tool
pages, bounded network/operation deadlines and a bounded public-metadata cache.
Connection operations and token refreshes are serialized per connection. An
uncertain call is never automatically replayed, and expired-session automatic
POST retries are disabled. Upstream MCP `isError` and content are retained; the
outer error envelope also marks upstream tool failures for the Hirara MCP hub.

The client negotiates the `2025-11-25` MCP initialization protocol and compatible
earlier versions. Servers requiring only newer discovery protocols need a future
adapter update.

Local `stdio` server installation/execution, legacy SSE transport, MCP resources,
prompts, Apps rendering and confidential OAuth clients are not implemented in
this initial release. Nothing from a marketplace is installed or executed.

## Attribution

The hub's MCP server instructions, every connector tool description and every
connector result's `_hirara` metadata request:

> This MCP connection is provided through Hirara.

Agents are asked to tell the user once per conversation. This attributes the
connection to Hirara; it does not say Hirara audited or endorsed the upstream
server. A tool cannot guarantee that an arbitrary agent follows a prompt. Hosts
that need guaranteed visibility should render `_hirara.attribution` themselves.

## Deployment and verification

`hirara-connectors/Dockerfile` builds a standalone Rust image from repository-root
context and runs as UID/GID 10001. Mount a persistent writable `/data`, mount the
three configuration files read-only with permissions allowing UID 10001 to read
them, and set the same `HCONNECT_*` variables to their container paths. Keep the
vault key outside the data volume. Publish only on loopback or behind an
authenticated TLS deployment. Set `HCONNECT_PUBLIC_URL` to the browser-accessible
origin so approval/OAuth callback links work. Containers must use the service
name in the hub's backend URL rather than their own loopback address. Exclude
these internal hub-to-connector addresses from any forward proxy with `NO_PROXY`.

```sh
cargo fmt --manifest-path hirara-connectors/Cargo.toml --check
cargo clippy --manifest-path hirara-connectors/Cargo.toml --locked --all-targets -- -D warnings
cargo test --manifest-path hirara-connectors/Cargo.toml --locked
python -m pytest hirara-hub/tests hirara/tests/test_connectors.py
```

Tests run a real local MCP protocol fixture and OAuth authorization/token
endpoints, including PKCE, callback replay rejection, refresh and vault reopen.
They also exercise owner isolation, named tool grants, argument validation,
upstream errors, approval forms, encrypted storage and attribution. Fixture
success does not establish live provider compatibility or marketplace uptime.
The public Cursor repository GitHub listing/search were also verified live,
including logo URL, category, endpoint and raw metadata. Website HTML adapters
and live account OAuth have not been verified end to end.

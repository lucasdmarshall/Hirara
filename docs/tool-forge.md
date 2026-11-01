# Rust Tool Forge prototype

Turn a supported OpenAPI JSON document into a reusable Hirara tool package,
then run it from a CLI or any MCP stdio client. The importer, validation,
request planning, HTTP execution and MCP server are Rust. No LLM, generated
source code, compiler invocation, shell execution or plugin installation is
involved in importing a document.

This is a deliberately narrow prototype, not a natural-language tool builder.
Existing MCP discovery remains available through the connector catalog; Forge
currently imports an OpenAPI document you supply rather than automatically
choosing between a connector and an API.

## Try it without credentials or network requests

From the repository root:

```sh
cargo build --manifest-path hirara-connectors/Cargo.toml --locked
hirara-connectors/target/debug/hirara-connectors forge build \
  --spec examples/forge/inventory.openapi.json --name inventory \
  --credential-env INVENTORY_TOKEN --out /tmp/inventory.hirara.json
hirara-connectors/target/debug/hirara-connectors forge inspect \
  --package /tmp/inventory.hirara.json
hirara-connectors/target/debug/hirara-connectors forge test \
  --package /tmp/inventory.hirara.json --fixtures examples/forge/cases.json
```

Build does not overwrite existing output. The report lists generated tool names,
skipped operations with reasons, and the SHA-256 of the exact output bytes.
The example generates `inventory__getstock`, omits `POST /orders`, and exercises
four offline request-planning cases. `api.example.com` is a placeholder, not a
working inventory service. Fixture tests validate input and expected URLs;
they do not prove provider compatibility or validate response schemas.

For a real API, substitute its local JSON document and use `--operation ID`
to select one operation if desired. `--base-url https://...` overrides the root
server explicitly. Neither import nor fixture tests fetch URLs or read the
credential environment variable.

## Review and execution

Review the endpoint, description, auth header, environment binding, argument
schema, and skipped report. Only then copy the build/inspect SHA-256 into the
client configuration. A digest verifies artifact integrity, not publisher
identity or safety. Rebuilding requires another review and digest update.
Do not let an untrusted agent both edit a package and change its pinned digest.

Inject the provider credential through your process manager or secret manager
into the reviewed environment variable. Never put credentials in chat,
OpenAPI examples, fixture files or tool arguments. Forge reads credentials
from the process environment on each call; this prototype does **not** import
them into the connector OAuth vault. Environment access remains a trusted
operator/process boundary.

```sh
hirara-connectors forge call --package /path/inventory.hirara.json \
  --sha256 REVIEWED_SHA256 --tool inventory__getstock \
  --arguments /path/args.json

hirara-connectors forge mcp --package /path/inventory.hirara.json \
  --sha256 REVIEWED_SHA256
```

Example MCP client configuration (use absolute paths and supply credentials
through the client's secure environment mechanism):

```json
{
  "mcpServers": {
    "inventory": {
      "command": "/absolute/path/hirara-connectors",
      "args": ["forge", "mcp", "--package", "/path/inventory.hirara.json",
               "--sha256", "REVIEWED_SHA256"]
    }
  }
}
```

The MCP server uses stdin/stdout, creates no listening socket, and advertises
only tools. Requests use grouped arguments, for example
`{"path":{"sku":"ABC"},"query":{"warehouse":"east"}}`.
`HIRARA_ALLOWED_TOOLS=inventory__getstock` restricts both tool listing and
execution; an explicitly empty value denies all generated tools. The same
check applies to CLI calls. This is a process-local policy, not inheritance of
a separate hub's client identity or per-user grants: run separate restricted
processes for separate principals. CLI failures exit nonzero; MCP execution
failures use `isError: true`. MCP schema failures may use the SDK's protocol
validation error. Non-success upstream HTTP responses expose status only,
never their body; no automatic retry occurs.

## Supported subset and security boundaries

- OpenAPI 3.0/3.1 JSON; GET operations only. GET is **not proof of no side
  effects**: review the actual provider semantics before granting access.
- One root HTTPS server, scalar path/query/header parameters, basic scalar
  constraints, strict unknown-field rejection, local component references
  with bounded depth. No request body, external references, server templates,
  per-operation server overrides, arrays, formatted/nullable/composite
  parameters, YAML, streaming responses or arbitrary prose import.
- Public operations, HTTP bearer, or a single API key header. Alternative or
  combined auth, OAuth and query credentials need an explicit adapter.
  Credentials cannot be selected or overridden by tool arguments. Reserved
  auth, routing, cookie and transport headers are denied.
- Existing connector egress policy: public HTTPS destinations, public DNS,
  no redirects, bounded response size (4 MiB), connection/request timeouts.
  A configured proxy requires `HCONNECT_TRUST_PROXY=true` and must itself
  enforce destination restrictions; do not acknowledge an untrusted proxy.
- JSON responses only. Credential literals echoed by the API are redacted;
  encoded or transformed secrets are not guaranteed to be detected. Provider
  responses may still contain sensitive business data, so grant access with
  that in mind. Descriptions and responses are untrusted data, not instructions.
- Inputs/packages/specs capped at 1 MiB, generated tools at 100, and concurrent
  MCP executions at four. Unknown arguments and unsafe path substitutions fail
  before network access. Packages are declarative; no generated code executes.

MCP instructions request the attribution “provided through Hirara”; this is
advisory and cannot force an AI client to display text. It does not mean Hirara
endorses the upstream provider.

## Verification

Rust tests cover deterministic import, write-operation exclusion, auth/reference
rejection, strict arguments, unsafe paths, artifact pinning and real local HTTP
requests including credential redaction, HTTP errors and redirect refusal.
`integration/test_forge_mcp.py` exercises the compiled binary with a real MCP
stdio client, offline fixtures, allowlist enforcement and changed-package
rejection. These tests do not contact a live provider.

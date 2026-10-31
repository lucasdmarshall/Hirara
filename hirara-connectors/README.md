# hirara-connectors

Rust MCP discovery and connection service for Hirara. Exposes seven connector
tools through authenticated HTTP, the Hirara Python SDK and the hub's MCP stdio
transport. Uses the official `rmcp` Rust SDK.

See [setup, security model and examples](../docs/connectors.md).

```sh
cargo install --path hirara-connectors --locked
hirara-connectors local
```

The local runtime opens a browser companion, generates its own private
configuration, and is discovered automatically by the Hirara hub/SDK. Agents
return connection links; users approve access and sign in in their browser.
Use `hirara-connectors open` to authorize another browser session.


Connection credentials persist in an authenticated encrypted vault. Operator-managed deployments retain explicit secret configuration; local mode
creates it automatically. Never put
secrets in chat or pass them as connector tool arguments.

# hirara-connectors

Rust MCP discovery and connection service for Hirara. Exposes seven connector
tools through authenticated HTTP, the Hirara Python SDK and the hub's MCP stdio
transport. Uses the official `rmcp` Rust SDK.

See [setup, security model and examples](../docs/connectors.md).

```sh
cargo build --locked --manifest-path hirara-connectors/Cargo.toml
hirara-connectors/target/debug/hirara-connectors init .connector-secrets
```

Connection credentials persist in an authenticated encrypted vault. Secret
configuration is mandatory; an unconfigured service fails closed. Never put
secrets in chat or pass them as connector tool arguments.

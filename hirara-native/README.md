# Hirara Native

Rust implementations of Hirara's new filesystem mutations, JSON query, research
parsing and network SQL tools. Existing Python tools call this extension through
`hirara_core.native`; use the public tool interfaces so permissions are enforced.

See [installation, examples and limitations](../docs/native-tools.md).

The extension's JSON dispatch API is internal and versioned together with its
Python adapters. It is not a security boundary for untrusted Python code running
inside the same process.

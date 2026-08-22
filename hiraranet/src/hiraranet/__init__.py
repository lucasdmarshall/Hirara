"""HiraraNet — self-hosted network tools for AI agents. No API keys.

v1 ships ``dns_lookup``. Further network tools (scoped) land in this package
over time — see the repo root TOOLS.md roadmap.
"""

from .config import ALLOWED_RECORD_TYPES, DEFAULT_RECORD_TYPES, NetConfig
from .lookup import Answer, LookupError, LookupResult, lookup_dns, result_to_dict
from .tools import DNS_LOOKUP_SCHEMA, Toolset

__all__ = [
    "ALLOWED_RECORD_TYPES",
    "DEFAULT_RECORD_TYPES",
    "DNS_LOOKUP_SCHEMA",
    "Answer",
    "LookupError",
    "LookupResult",
    "NetConfig",
    "Toolset",
    "lookup_dns",
    "result_to_dict",
]

__version__ = "0.1.0"

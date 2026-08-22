"""HiraraNet — self-hosted network tools for AI agents. No API keys.

Ships ``dns_lookup`` and ``port_scan``. Further tools land here over time —
see the repo root TOOLS.md roadmap.
"""

from .config import (
    ALLOWED_RECORD_TYPES,
    DEFAULT_RECORD_TYPES,
    DEFAULT_SCAN_PORTS,
    NetConfig,
)
from .lookup import Answer, LookupError, LookupResult, lookup_dns, result_to_dict
from .scan import (
    PortResult,
    ScanError,
    ScanResult,
    parse_ports,
    resolve_host,
    scan_ports,
    scan_result_to_dict,
)
from .tools import DNS_LOOKUP_SCHEMA, PORT_SCAN_SCHEMA, Toolset

__all__ = [
    "ALLOWED_RECORD_TYPES",
    "DEFAULT_RECORD_TYPES",
    "DEFAULT_SCAN_PORTS",
    "DNS_LOOKUP_SCHEMA",
    "PORT_SCAN_SCHEMA",
    "Answer",
    "LookupError",
    "LookupResult",
    "NetConfig",
    "PortResult",
    "ScanError",
    "ScanResult",
    "Toolset",
    "lookup_dns",
    "parse_ports",
    "resolve_host",
    "result_to_dict",
    "scan_ports",
    "scan_result_to_dict",
]

__version__ = "0.1.0"

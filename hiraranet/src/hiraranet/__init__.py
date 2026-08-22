"""HiraraNet — self-hosted network tools for AI agents. No API keys.

Ships ``dns_lookup``, ``port_scan``, and ``service_enum``. Further tools land
here over time — see the repo root TOOLS.md roadmap.
"""

from .config import (
    ALLOWED_RECORD_TYPES,
    DEFAULT_RECORD_TYPES,
    DEFAULT_SCAN_PORTS,
    NetConfig,
)
from .enum_svc import (
    PORT_HINTS,
    EnumResult,
    ServiceResult,
    classify_banner,
    enum_result_to_dict,
    enum_services,
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
from .tools import DNS_LOOKUP_SCHEMA, PORT_SCAN_SCHEMA, SERVICE_ENUM_SCHEMA, Toolset

__all__ = [
    "ALLOWED_RECORD_TYPES",
    "DEFAULT_RECORD_TYPES",
    "DEFAULT_SCAN_PORTS",
    "DNS_LOOKUP_SCHEMA",
    "PORT_HINTS",
    "PORT_SCAN_SCHEMA",
    "SERVICE_ENUM_SCHEMA",
    "Answer",
    "EnumResult",
    "LookupError",
    "LookupResult",
    "NetConfig",
    "PortResult",
    "ScanError",
    "ScanResult",
    "ServiceResult",
    "Toolset",
    "classify_banner",
    "enum_result_to_dict",
    "enum_services",
    "lookup_dns",
    "parse_ports",
    "resolve_host",
    "result_to_dict",
    "scan_ports",
    "scan_result_to_dict",
]

__version__ = "0.1.0"

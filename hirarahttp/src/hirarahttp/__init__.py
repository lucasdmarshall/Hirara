"""HiraraHttp — self-hosted HTTP tools for AI agents.

Ships ``http_request``, ``http_history``, inspect tools, and
``directory_enum``.
"""

from .config import HttpConfig
from .enum_dir import (
    DEFAULT_PATHS,
    EnumError,
    EnumResult,
    PathHit,
    directory_enum,
    enum_result_to_dict,
)
from .history import HistoryEntry, HistoryStore, entry_to_dict, entry_to_summary
from .inspect import (
    CookieRecord,
    CookieView,
    HeaderView,
    InspectCookiesResult,
    InspectHeadersResult,
    InspectResponseResult,
    inspect_cookies_from_entry,
    inspect_cookies_from_maps,
    inspect_cookies_result_to_dict,
    inspect_headers_from_entry,
    inspect_headers_from_maps,
    inspect_headers_result_to_dict,
    inspect_response_from_entry,
    inspect_response_from_parts,
    inspect_response_result_to_dict,
)
from .request import RequestError, RequestResult, http_request, result_to_dict
from .tools import (
    DIRECTORY_ENUM_SCHEMA,
    HTTP_HISTORY_SCHEMA,
    HTTP_REQUEST_SCHEMA,
    INSPECT_COOKIES_SCHEMA,
    INSPECT_HEADERS_SCHEMA,
    INSPECT_RESPONSE_SCHEMA,
    TOOL_NAMES,
    Toolset,
    call_tool,
    tool_schemas,
)

__all__ = [
    "DEFAULT_PATHS",
    "DIRECTORY_ENUM_SCHEMA",
    "HTTP_HISTORY_SCHEMA",
    "HTTP_REQUEST_SCHEMA",
    "INSPECT_COOKIES_SCHEMA",
    "INSPECT_HEADERS_SCHEMA",
    "INSPECT_RESPONSE_SCHEMA",
    "TOOL_NAMES",
    "CookieRecord",
    "CookieView",
    "EnumError",
    "EnumResult",
    "HeaderView",
    "HistoryEntry",
    "HistoryStore",
    "HttpConfig",
    "InspectCookiesResult",
    "InspectHeadersResult",
    "InspectResponseResult",
    "PathHit",
    "RequestError",
    "RequestResult",
    "Toolset",
    "call_tool",
    "directory_enum",
    "entry_to_dict",
    "entry_to_summary",
    "enum_result_to_dict",
    "http_request",
    "inspect_cookies_from_entry",
    "inspect_cookies_from_maps",
    "inspect_cookies_result_to_dict",
    "inspect_headers_from_entry",
    "inspect_headers_from_maps",
    "inspect_headers_result_to_dict",
    "inspect_response_from_entry",
    "inspect_response_from_parts",
    "inspect_response_result_to_dict",
    "result_to_dict",
    "tool_schemas",
]

__version__ = "0.1.0"

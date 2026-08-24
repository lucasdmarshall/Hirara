"""HiraraHttp — self-hosted HTTP tools for AI agents.

Ships ``http_request``, ``http_history``, ``inspect_headers``,
``inspect_cookies``, and ``inspect_response``.
"""

from .config import HttpConfig
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
    "HTTP_HISTORY_SCHEMA",
    "HTTP_REQUEST_SCHEMA",
    "INSPECT_COOKIES_SCHEMA",
    "INSPECT_HEADERS_SCHEMA",
    "INSPECT_RESPONSE_SCHEMA",
    "TOOL_NAMES",
    "CookieRecord",
    "CookieView",
    "HeaderView",
    "HistoryEntry",
    "HistoryStore",
    "HttpConfig",
    "InspectCookiesResult",
    "InspectHeadersResult",
    "InspectResponseResult",
    "RequestError",
    "RequestResult",
    "Toolset",
    "call_tool",
    "entry_to_dict",
    "entry_to_summary",
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

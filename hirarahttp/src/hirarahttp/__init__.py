"""HiraraHttp — self-hosted HTTP tools for AI agents.

Ships ``http_request`` and ``http_history``. See ``TOOLS.md`` for inspect /
replay tools next.
"""

from .config import HttpConfig
from .history import HistoryEntry, HistoryStore, entry_to_dict, entry_to_summary
from .request import RequestError, RequestResult, http_request, result_to_dict
from .tools import (
    HTTP_HISTORY_SCHEMA,
    HTTP_REQUEST_SCHEMA,
    TOOL_NAMES,
    Toolset,
    call_tool,
    tool_schemas,
)

__all__ = [
    "HTTP_HISTORY_SCHEMA",
    "HTTP_REQUEST_SCHEMA",
    "TOOL_NAMES",
    "HistoryEntry",
    "HistoryStore",
    "HttpConfig",
    "RequestError",
    "RequestResult",
    "Toolset",
    "call_tool",
    "entry_to_dict",
    "entry_to_summary",
    "http_request",
    "result_to_dict",
    "tool_schemas",
]

__version__ = "0.1.0"

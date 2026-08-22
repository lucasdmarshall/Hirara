"""HiraraHttp — self-hosted HTTP tools for AI agents.

Ships ``http_request``. See ``TOOLS.md`` for the rest of the cluster
(``http_history``, ``inspect_*``, replay / compare).
"""

from .config import HttpConfig
from .request import RequestError, RequestResult, http_request, result_to_dict
from .tools import HTTP_REQUEST_SCHEMA, TOOL_NAMES, Toolset, call_tool, tool_schemas

__all__ = [
    "HTTP_REQUEST_SCHEMA",
    "TOOL_NAMES",
    "HttpConfig",
    "RequestError",
    "RequestResult",
    "Toolset",
    "call_tool",
    "http_request",
    "result_to_dict",
    "tool_schemas",
]

__version__ = "0.1.0"

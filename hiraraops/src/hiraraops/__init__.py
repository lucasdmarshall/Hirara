"""HiraraOps — self-hosted ops tools for AI agents. No API keys.

Ships ``application_logs``, ``process_list``, and ``environment_read``.
"""

from .config import DEFAULT_REDACT_PATTERNS, OpsConfig
from .environ import EnvironError, EnvironResult, environment_read
from .environ import result_to_dict as environ_result_to_dict
from .logs import LogLine, LogsError, LogsResult, application_logs, resolve_log_path
from .logs import result_to_dict as logs_result_to_dict
from .processes import ProcessError, ProcessInfo, ProcessListResult, process_list
from .processes import result_to_dict as process_result_to_dict
from .tools import (
    APPLICATION_LOGS_SCHEMA,
    ENVIRONMENT_READ_SCHEMA,
    PROCESS_LIST_SCHEMA,
    Toolset,
)

__all__ = [
    "APPLICATION_LOGS_SCHEMA",
    "DEFAULT_REDACT_PATTERNS",
    "ENVIRONMENT_READ_SCHEMA",
    "PROCESS_LIST_SCHEMA",
    "EnvironError",
    "EnvironResult",
    "LogLine",
    "LogsError",
    "LogsResult",
    "OpsConfig",
    "ProcessError",
    "ProcessInfo",
    "ProcessListResult",
    "Toolset",
    "application_logs",
    "environment_read",
    "environ_result_to_dict",
    "logs_result_to_dict",
    "process_list",
    "process_result_to_dict",
    "resolve_log_path",
]

__version__ = "0.1.0"

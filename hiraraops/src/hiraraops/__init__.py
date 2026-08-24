"""HiraraOps — self-hosted ops tools for AI agents. No API keys.

Ships ``application_logs`` and ``process_list``. ``environment_read`` lands
here later — see TOOLS.md.
"""

from .config import OpsConfig
from .logs import LogLine, LogsError, LogsResult, application_logs, resolve_log_path
from .logs import result_to_dict as logs_result_to_dict
from .processes import ProcessError, ProcessInfo, ProcessListResult, process_list
from .processes import result_to_dict as process_result_to_dict
from .tools import APPLICATION_LOGS_SCHEMA, PROCESS_LIST_SCHEMA, Toolset

__all__ = [
    "APPLICATION_LOGS_SCHEMA",
    "PROCESS_LIST_SCHEMA",
    "LogLine",
    "LogsError",
    "LogsResult",
    "OpsConfig",
    "ProcessError",
    "ProcessInfo",
    "ProcessListResult",
    "Toolset",
    "application_logs",
    "logs_result_to_dict",
    "process_list",
    "process_result_to_dict",
    "resolve_log_path",
]

__version__ = "0.1.0"

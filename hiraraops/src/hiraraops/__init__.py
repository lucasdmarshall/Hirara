"""HiraraOps — self-hosted ops tools for AI agents. No API keys.

Ships ``application_logs``. ``process_list`` / ``environment_read`` land here
later — see TOOLS.md.
"""

from .config import OpsConfig
from .logs import LogLine, LogsError, LogsResult, application_logs, resolve_log_path, result_to_dict
from .tools import APPLICATION_LOGS_SCHEMA, Toolset

__all__ = [
    "APPLICATION_LOGS_SCHEMA",
    "LogLine",
    "LogsError",
    "LogsResult",
    "OpsConfig",
    "Toolset",
    "application_logs",
    "resolve_log_path",
    "result_to_dict",
]

__version__ = "0.1.0"

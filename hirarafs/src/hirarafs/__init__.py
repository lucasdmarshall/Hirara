"""HiraraFs — self-hosted filesystem tools for AI agents. No API keys.

Ships ``file_read`` and ``file_write``.
"""

from .config import FsConfig
from .paths import PathError, resolve_existing_file, resolve_write_target
from .reader import ReadError, ReadResult, file_read, resolve_path, result_to_dict
from .tools import FILE_READ_SCHEMA, FILE_WRITE_SCHEMA, Toolset
from .writer import WriteError, WriteResult, file_write, write_result_to_dict

__all__ = [
    "FILE_READ_SCHEMA",
    "FILE_WRITE_SCHEMA",
    "FsConfig",
    "PathError",
    "ReadError",
    "ReadResult",
    "Toolset",
    "WriteError",
    "WriteResult",
    "file_read",
    "file_write",
    "resolve_existing_file",
    "resolve_path",
    "resolve_write_target",
    "result_to_dict",
    "write_result_to_dict",
]

__version__ = "0.1.0"

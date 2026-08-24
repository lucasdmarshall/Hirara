"""HiraraFs — self-hosted filesystem tools for AI agents. No API keys.

Ships ``file_read``. ``file_write`` lands here later — see the repo root
TOOLS.md roadmap.
"""

from .config import FsConfig
from .reader import ReadError, ReadResult, file_read, resolve_path, result_to_dict
from .tools import FILE_READ_SCHEMA, Toolset

__all__ = [
    "FILE_READ_SCHEMA",
    "FsConfig",
    "ReadError",
    "ReadResult",
    "Toolset",
    "file_read",
    "resolve_path",
    "result_to_dict",
]

__version__ = "0.1.0"

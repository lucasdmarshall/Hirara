"""HiraraUtil — self-hosted utility tools for AI agents. No API keys.

Ships ``decode``. ``hash`` / JWT tools land here later — see TOOLS.md.
"""

from .config import UtilConfig
from .decode import FORMATS, DecodeError, DecodeResult, decode, result_to_dict
from .tools import DECODE_SCHEMA, Toolset

__all__ = [
    "DECODE_SCHEMA",
    "FORMATS",
    "DecodeError",
    "DecodeResult",
    "Toolset",
    "UtilConfig",
    "decode",
    "result_to_dict",
]

__version__ = "0.1.0"

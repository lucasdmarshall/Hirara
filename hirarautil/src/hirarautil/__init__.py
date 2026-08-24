"""HiraraUtil — self-hosted utility tools for AI agents. No API keys.

Ships ``decode``, ``hash``, ``jwt_inspect``, and ``jwt_decode``.
"""

from .config import UtilConfig
from .decode import FORMATS, DecodeError, DecodeResult, decode
from .decode import result_to_dict as decode_result_to_dict
from .hashing import ALGORITHMS, HashError, HashResult, hash_input
from .hashing import result_to_dict as hash_result_to_dict
from .jwt import JwtDecodeResult, JwtError, JwtInspectResult, jwt_decode, jwt_inspect
from .jwt import decode_result_to_dict as jwt_decode_result_to_dict
from .jwt import inspect_result_to_dict as jwt_inspect_result_to_dict
from .tools import (
    DECODE_SCHEMA,
    HASH_SCHEMA,
    JWT_DECODE_SCHEMA,
    JWT_INSPECT_SCHEMA,
    Toolset,
)

__all__ = [
    "ALGORITHMS",
    "DECODE_SCHEMA",
    "FORMATS",
    "HASH_SCHEMA",
    "JWT_DECODE_SCHEMA",
    "JWT_INSPECT_SCHEMA",
    "DecodeError",
    "DecodeResult",
    "HashError",
    "HashResult",
    "JwtDecodeResult",
    "JwtError",
    "JwtInspectResult",
    "Toolset",
    "UtilConfig",
    "decode",
    "decode_result_to_dict",
    "hash_input",
    "hash_result_to_dict",
    "jwt_decode",
    "jwt_decode_result_to_dict",
    "jwt_inspect",
    "jwt_inspect_result_to_dict",
]

__version__ = "0.1.0"

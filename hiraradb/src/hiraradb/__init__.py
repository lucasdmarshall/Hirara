"""HiraraDb — self-hosted database tools for AI agents. No API keys.

Ships ``database_query``. ``database_schema`` lands here later — see TOOLS.md.
"""

from .config import DbConfig
from .query import QueryError, QueryResult, database_query, resolve_db_path, result_to_dict
from .tools import DATABASE_QUERY_SCHEMA, Toolset

__all__ = [
    "DATABASE_QUERY_SCHEMA",
    "DbConfig",
    "QueryError",
    "QueryResult",
    "Toolset",
    "database_query",
    "resolve_db_path",
    "result_to_dict",
]

__version__ = "0.1.0"

"""HiraraDb — self-hosted database tools for AI agents. No API keys.

Ships ``database_query`` and ``database_schema``.
"""

from .config import DbConfig
from .query import QueryError, QueryResult, database_query, resolve_db_path
from .query import result_to_dict as query_result_to_dict
from .schema import (
    ColumnInfo,
    SchemaResult,
    TableInfo,
    database_schema,
    schema_result_to_dict,
)
from .tools import DATABASE_QUERY_SCHEMA, DATABASE_SCHEMA_TOOL, Toolset

__all__ = [
    "DATABASE_QUERY_SCHEMA",
    "DATABASE_SCHEMA_TOOL",
    "ColumnInfo",
    "DbConfig",
    "QueryError",
    "QueryResult",
    "SchemaResult",
    "TableInfo",
    "Toolset",
    "database_query",
    "database_schema",
    "query_result_to_dict",
    "resolve_db_path",
    "schema_result_to_dict",
]

__version__ = "0.1.0"

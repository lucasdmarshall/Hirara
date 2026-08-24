"""Toolset / schema / health."""

from __future__ import annotations

import sqlite3

import pytest

from hiraradb.config import DbConfig
from hiraradb.tools import DATABASE_QUERY_SCHEMA, TOOL_NAMES, Toolset, call_tool


def test_schema():
    assert DATABASE_QUERY_SCHEMA["name"] == "database_query"
    assert "sql" in DATABASE_QUERY_SCHEMA["input_schema"]["required"]


def test_health(tmp_path):
    ts = Toolset(
        config=DbConfig(
            databases={"default": str(tmp_path / "a.db")},
            readonly=True,
        )
    )
    h = ts.health()
    assert h["status"] == "ok"
    assert h["tools"] == ["database_query"]
    assert h["databases"] == ["default"]
    assert h["readonly"] is True


@pytest.mark.asyncio
async def test_toolset_query(tmp_path):
    db = tmp_path / "t.db"
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE t (x INTEGER)")
    conn.execute("INSERT INTO t VALUES (7)")
    conn.commit()
    conn.close()

    ts = Toolset(config=DbConfig(allow_any_path=True))
    r = await ts.database_query(sql="SELECT x FROM t", path=str(db))
    assert r["error"] is None
    assert r["rows"] == [[7]]


@pytest.mark.asyncio
async def test_call_tool_unknown():
    assert TOOL_NAMES == ("database_query",)
    with pytest.raises(KeyError):
        await call_tool("nope", {})

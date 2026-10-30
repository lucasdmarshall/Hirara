"""Real server tests. Start services as documented in docs/native-tools.md."""
import os

import pytest

pytest.importorskip("hiraradb", reason="optional native database integration dependency")
from hiraradb.config import DbConfig
from hiraradb.tools import Toolset

pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(
    os.getenv("HIRARA_DATABASE_INTEGRATION") != "1", reason="requires PostgreSQL/MySQL test services")]


@pytest.mark.parametrize("kind,url", [
    ("pg", "postgresql://postgres:hirara-test@127.0.0.1:15432/hirara?sslmode=disable"),
    ("mysql", "mysql://root:hirara-test@127.0.0.1:13306/hirara?ssl-mode=disabled"),
])
async def test_database_roundtrip(kind, url):
    writer = Toolset(DbConfig(databases={"default": url}, readonly=False, timeout=10, max_rows=2))
    reader = Toolset(DbConfig(databases={"default": url}, timeout=10, max_rows=2))
    await writer.database_query(sql="DROP TABLE IF EXISTS hirara_native_items")
    result = await writer.database_query(sql="CREATE TABLE hirara_native_items (id INTEGER PRIMARY KEY, name VARCHAR(100), amount DECIMAL(10,2), enabled BOOLEAN, created DATE, nullable INTEGER)")
    assert result["error"] is None, result
    placeholder = "$1, $2" if kind == "pg" else "?, ?"
    for i in range(3):
        result = await writer.database_query(
            sql=f"INSERT INTO hirara_native_items (id,name,amount,enabled,created) VALUES ({placeholder},12.34,TRUE,'2026-01-01')",
            params=[i, f"name-{i}"])
        assert result["error"] is None, result
        assert result["row_count"] == 1, result
    result = await reader.database_query(sql="SELECT id,name,amount,enabled,created,nullable FROM hirara_native_items ORDER BY id", max_rows=500)
    assert result["error"] is None, result
    assert result["row_count"] == 2 and result["truncated"]
    assert result["rows"][0] == [0,"name-0","12.34",True,"2026-01-01",None], result
    empty = await reader.database_query(sql="SELECT id FROM hirara_native_items WHERE id = 100")
    assert empty["error"] is None and empty["columns"] == ["id"], empty
    assert (await reader.database_query(sql="DELETE FROM hirara_native_items", readonly=False))["error"]
    assert (await reader.database_query(sql="SELECT 1; DELETE FROM hirara_native_items"))["error"]
    assert (await reader.database_query(sql="SET TRANSACTION READ WRITE"))["error"]
    schema = await reader.database_schema(table="hirara_native_items", include_indexes=True, include_foreign_keys=True, include_sql=True)
    assert schema["error"] is None, schema
    assert schema["tables"][0]["columns"][0]["pk"] == 1
    assert schema["tables"][0]["indexes"]
    # Semicolons inside a literal are not multiple statements.
    assert (await reader.database_query(sql="SELECT ';' AS semicolon"))["rows"] == [[";"]]
    null_sql = "UPDATE hirara_native_items SET nullable = " + ("$1" if kind == "pg" else "?") + " WHERE id = 0"
    result = await writer.database_query(sql=null_sql, params=[None])
    assert result["error"] is None, result
    slow = Toolset(DbConfig(databases={"default":url}, timeout=0.2))
    result = await slow.database_query(sql="SELECT pg_sleep(2)" if kind == "pg" else "SELECT SLEEP(2)")
    assert result["error"], result
    assert "hirara-test" not in str(result)
    assert (await reader.database_query(sql="SELECT 1"))["error"] is None
    assert (await writer.database_query(sql="DROP TABLE hirara_native_items"))["error"] is None

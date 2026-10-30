import pytest
from hiraradb.config import DbConfig
from hiraradb.tools import Toolset
from hiraradb import network

@pytest.mark.asyncio
async def test_only_configured_network_connections(monkeypatch):
    captured = []
    async def native(action, **kwargs):
        captured.append((action, kwargs))
        return {"rows": [], "error": None}
    monkeypatch.setattr(network,"native_call",native)
    ts=Toolset(DbConfig(databases={"pg":"postgresql://user:secret@db/app"},max_rows=5))
    assert (await ts.database_query(sql="SELECT 1",path="postgresql://attacker/other"))["error"]
    assert captured == []
    result = await ts.database_query(sql="SELECT 1",database="pg",readonly=False,max_rows=100)
    assert result["error"] is None
    assert captured[0][1]["readonly"] is True
    assert captured[0][1]["max_rows"] == 5
    assert "secret" not in str(result)
    await ts.database_schema(database="pg", max_tables=100)
    assert captured[-1][1]["max_tables"] == 5
    writable=Toolset(DbConfig(databases={"default":"mysql://user:secret@db/app"},readonly=False))
    await writable.database_query(sql="DELETE FROM x")
    assert captured[-1][1]["readonly"] is False

@pytest.mark.asyncio
async def test_bad_limits_do_not_connect(monkeypatch):
    async def forbidden(*args, **kwargs):
        raise AssertionError("must not call native backend")
    monkeypatch.setattr(network,"native_call",forbidden)
    ts=Toolset(DbConfig(databases={"default":"postgresql://db/app"}))
    assert (await ts.database_query(sql="SELECT 1", max_rows=0))["error"]

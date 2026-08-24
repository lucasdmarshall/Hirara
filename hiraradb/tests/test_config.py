"""Config defaults / env."""

from hiraradb.config import DbConfig


def test_defaults():
    cfg = DbConfig()
    assert cfg.max_rows == 1_000
    assert cfg.readonly is True
    assert cfg.allow_any_path is True
    assert cfg.resolved_databases() == {}


def test_from_env(monkeypatch):
    monkeypatch.setenv("CDB_PATH", "/data/app.db")
    monkeypatch.setenv("CDB_DATABASES", "analytics=/data/a.db,other=/data/o.db")
    monkeypatch.setenv("CDB_READONLY", "false")
    monkeypatch.setenv("CDB_MAX_ROWS", "50")
    monkeypatch.setenv("CDB_ROOTS", "/data")
    monkeypatch.setenv("CDB_ALLOW_ANY_PATH", "false")
    cfg = DbConfig.from_env()
    assert cfg.readonly is False
    assert cfg.max_rows == 50
    assert cfg.roots == ("/data",)
    assert cfg.allow_any_path is False
    dbs = cfg.resolved_databases()
    assert dbs["default"] == "/data/app.db"
    assert dbs["analytics"] == "/data/a.db"
    assert dbs["other"] == "/data/o.db"

"""database_query unit tests (temp sqlite files)."""

from __future__ import annotations

import sqlite3

from hiraradb.config import DbConfig
from hiraradb.query import database_query


def _seed(path: str) -> None:
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("INSERT INTO users (name) VALUES ('ada'), ('bob')")
    conn.commit()
    conn.close()


def test_select(tmp_path):
    db = tmp_path / "app.db"
    _seed(str(db))
    cfg = DbConfig(allow_any_path=True, readonly=True)
    r = database_query(
        "SELECT id, name FROM users ORDER BY id",
        path=str(db),
        config=cfg,
    )
    assert r.error is None
    assert r.columns == ["id", "name"]
    assert r.rows == [[1, "ada"], [2, "bob"]]
    assert r.row_count == 2
    assert r.readonly is True


def test_params(tmp_path):
    db = tmp_path / "app.db"
    _seed(str(db))
    r = database_query(
        "SELECT name FROM users WHERE id = ?",
        params=[2],
        path=str(db),
        config=DbConfig(allow_any_path=True),
    )
    assert r.error is None
    assert r.rows == [["bob"]]


def test_named_database(tmp_path):
    db = tmp_path / "named.db"
    _seed(str(db))
    cfg = DbConfig(
        databases={"default": str(db)},
        allow_any_path=True,
    )
    r = database_query("SELECT COUNT(*) AS n FROM users", config=cfg)
    assert r.error is None
    assert r.rows == [[2]]
    assert r.database == "default"


def test_readonly_blocks_write(tmp_path):
    db = tmp_path / "app.db"
    _seed(str(db))
    r = database_query(
        "DELETE FROM users",
        path=str(db),
        config=DbConfig(allow_any_path=True, readonly=True),
    )
    assert r.error and "blocked" in r.error


def test_multi_statement_rejected(tmp_path):
    db = tmp_path / "app.db"
    _seed(str(db))
    r = database_query(
        "SELECT 1; SELECT 2",
        path=str(db),
        config=DbConfig(allow_any_path=True),
    )
    assert r.error and "multiple" in r.error


def test_max_rows_truncates(tmp_path):
    db = tmp_path / "app.db"
    _seed(str(db))
    r = database_query(
        "SELECT id FROM users ORDER BY id",
        path=str(db),
        max_rows=1,
        config=DbConfig(allow_any_path=True),
    )
    assert r.row_count == 1
    assert r.truncated is True


def test_roots_deny(tmp_path):
    allowed = tmp_path / "ok"
    allowed.mkdir()
    db = tmp_path / "secret.db"
    _seed(str(db))
    r = database_query(
        "SELECT 1",
        path=str(db),
        config=DbConfig(roots=(str(allowed),), allow_any_path=False),
    )
    assert r.error and "outside allowed roots" in r.error


def test_write_when_allowed(tmp_path):
    db = tmp_path / "w.db"
    _seed(str(db))
    cfg = DbConfig(allow_any_path=True, readonly=False)
    r = database_query(
        "INSERT INTO users (name) VALUES (?)",
        params=["cara"],
        path=str(db),
        config=cfg,
    )
    assert r.error is None
    check = database_query(
        "SELECT name FROM users WHERE name = ?",
        params=["cara"],
        path=str(db),
        config=cfg,
    )
    assert check.rows == [["cara"]]


def test_memory_select():
    r = database_query(
        "SELECT 1 AS n",
        path=":memory:",
        config=DbConfig(allow_any_path=True),
    )
    assert r.error is None
    assert r.rows == [[1]]

"""database_schema unit tests."""

from __future__ import annotations

import sqlite3

from hiraradb.config import DbConfig
from hiraradb.schema import database_schema


def _seed(path: str) -> None:
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE users ("
        "id INTEGER PRIMARY KEY, "
        "name TEXT NOT NULL, "
        "email TEXT)"
    )
    conn.execute(
        "CREATE TABLE posts ("
        "id INTEGER PRIMARY KEY, "
        "user_id INTEGER REFERENCES users(id), "
        "title TEXT)"
    )
    conn.execute("CREATE INDEX idx_posts_user ON posts(user_id)")
    conn.execute("CREATE VIEW user_names AS SELECT id, name FROM users")
    conn.commit()
    conn.close()


def test_list_tables(tmp_path):
    db = tmp_path / "s.db"
    _seed(str(db))
    r = database_schema(path=str(db), config=DbConfig(allow_any_path=True))
    assert r.error is None
    names = {t.name: t for t in r.tables}
    assert "users" in names
    assert "posts" in names
    assert "user_names" in names
    assert names["user_names"].type == "view"
    cols = {c.name: c for c in names["users"].columns}
    assert cols["name"].notnull is True
    assert cols["id"].pk == 1


def test_table_filter(tmp_path):
    db = tmp_path / "s.db"
    _seed(str(db))
    r = database_schema(
        path=str(db),
        table="posts",
        include_indexes=True,
        include_foreign_keys=True,
        include_sql=True,
        config=DbConfig(allow_any_path=True),
    )
    assert r.error is None
    assert r.table_count == 1
    t = r.tables[0]
    assert t.name == "posts"
    assert t.indexes and any(i["name"] == "idx_posts_user" for i in t.indexes)
    assert t.foreign_keys and t.foreign_keys[0]["table"] == "users"
    assert t.sql and "CREATE TABLE" in t.sql


def test_missing_table(tmp_path):
    db = tmp_path / "s.db"
    _seed(str(db))
    r = database_schema(
        path=str(db),
        table="nope",
        config=DbConfig(allow_any_path=True),
    )
    assert r.error and "not found" in r.error


def test_exclude_views(tmp_path):
    db = tmp_path / "s.db"
    _seed(str(db))
    r = database_schema(
        path=str(db),
        include_views=False,
        config=DbConfig(allow_any_path=True),
    )
    names = {t.name for t in r.tables}
    assert "user_names" not in names
    assert "users" in names

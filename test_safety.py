import sqlite3

import pandas as pd
import pytest

from db import _is_safe_sql, safe_execute


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE t (id INTEGER, note TEXT)")
    c.executemany("INSERT INTO t VALUES (?, ?)", [(1, "a"), (2, "please update later")])
    c.commit()
    return c


# ── _is_safe_sql ────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("sql", [
    "SELECT * FROM t",
    "WITH x AS (SELECT 1) SELECT * FROM x",
    "select id from t where note = 'please update later'",  # banned word in a literal
])
def test_safe_queries_allowed(sql):
    ok, reason = _is_safe_sql(sql)
    assert ok, reason


@pytest.mark.parametrize("sql", [
    "UPDATE t SET id = 9",
    "DELETE FROM t",
    "DROP TABLE t",
    "INSERT INTO t VALUES (3, 'x')",
    "SELECT 1; DROP TABLE t",          # multiple statements
    "ALTER TABLE t ADD COLUMN z INT",
    "",                                 # empty
])
def test_unsafe_queries_rejected(sql):
    ok, _ = _is_safe_sql(sql)
    assert not ok


# ── safe_execute ────────────────────────────────────────────────────────────────
def test_safe_execute_runs_select(conn):
    df, err = safe_execute("SELECT id FROM t ORDER BY id", conn)
    assert err is None
    assert list(df["id"]) == [1, 2]


def test_safe_execute_blocks_mutation(conn):
    df, err = safe_execute("DELETE FROM t", conn)
    assert df is None and err is not None
    # Data must be untouched
    assert conn.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 2


def test_safe_execute_caps_rows(conn):
    big = pd.DataFrame({"n": range(10)})
    big.to_sql("big", conn, index=False)
    df, err = safe_execute("SELECT * FROM big", conn, limit=3)
    assert err is None and len(df) == 3

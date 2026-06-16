import hashlib
import sqlite3
from datetime import datetime
from pathlib import Path

import pandas as pd

DB_PATH = Path(__file__).parent / "drill_history.db"


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            username      TEXT PRIMARY KEY,
            password_hash TEXT NOT NULL,
            created_at    TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS attempts (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            username    TEXT NOT NULL DEFAULT 'guest',
            timestamp   TEXT NOT NULL,
            dataset     TEXT NOT NULL,
            topic       TEXT NOT NULL,
            difficulty  TEXT NOT NULL,
            time_seconds REAL NOT NULL,
            passed      INTEGER NOT NULL,
            my_sql      TEXT
        )
    """)
    # Migrate older DBs that lack the username column
    cols = [r[1] for r in conn.execute("PRAGMA table_info(attempts)").fetchall()]
    if "username" not in cols:
        conn.execute("ALTER TABLE attempts ADD COLUMN username TEXT NOT NULL DEFAULT 'guest'")
    conn.commit()
    return conn


def _hash(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


# ── Auth ───────────────────────────────────────────────────────────────────────
def register_user(username: str, password: str) -> tuple[bool, str]:
    username = username.strip().lower()
    if not username or not password:
        return False, "Username and password are required."
    conn = _get_conn()
    existing = conn.execute(
        "SELECT 1 FROM users WHERE username = ?", (username,)
    ).fetchone()
    if existing:
        conn.close()
        return False, "That username is taken."
    conn.execute(
        "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
        (username, _hash(password), datetime.utcnow().isoformat()),
    )
    conn.commit()
    conn.close()
    return True, "Account created."


def login_user(username: str, password: str) -> tuple[bool, str]:
    username = username.strip().lower()
    conn = _get_conn()
    row = conn.execute(
        "SELECT password_hash FROM users WHERE username = ?", (username,)
    ).fetchone()
    conn.close()
    if not row:
        return False, "No account with that username."
    if row[0] != _hash(password):
        return False, "Incorrect password."
    return True, "Signed in."


# ── Attempts ───────────────────────────────────────────────────────────────────
def log_attempt(
    username: str,
    dataset: str,
    topic: str,
    difficulty: str,
    time_seconds: float,
    passed: bool,
    my_sql: str,
) -> None:
    conn = _get_conn()
    conn.execute(
        "INSERT INTO attempts (username, timestamp, dataset, topic, difficulty, time_seconds, passed, my_sql) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (username, datetime.utcnow().isoformat(), dataset, topic, difficulty, time_seconds, int(passed), my_sql),
    )
    conn.commit()
    conn.close()


def get_stats(username: str) -> pd.DataFrame:
    conn = _get_conn()
    df = pd.read_sql_query(
        """
        SELECT
            dataset,
            topic,
            COUNT(*) AS attempts,
            ROUND(AVG(passed) * 100, 1) AS pass_rate,
            ROUND(AVG(time_seconds), 1) AS avg_time_seconds,
            ROUND(
                (SELECT AVG(time_seconds) FROM (
                    SELECT time_seconds, ROW_NUMBER() OVER (ORDER BY time_seconds) AS rn, COUNT(*) OVER () AS cnt
                    FROM attempts a2 WHERE a2.dataset = a.dataset AND a2.topic = a.topic AND a2.username = a.username
                ) WHERE rn IN ((cnt+1)/2, (cnt+2)/2)
                ), 1
            ) AS median_time_seconds
        FROM attempts a
        WHERE username = ?
        GROUP BY dataset, topic
        ORDER BY pass_rate ASC
        """,
        conn,
        params=(username,),
    )
    conn.close()
    return df


def get_weakest_topic(username: str) -> tuple[str, str] | None:
    conn = _get_conn()
    row = conn.execute(
        """
        SELECT dataset, topic, AVG(passed) AS pr
        FROM attempts
        WHERE username = ?
        GROUP BY dataset, topic
        HAVING COUNT(*) >= 2
        ORDER BY pr ASC
        LIMIT 1
        """,
        (username,),
    ).fetchone()
    conn.close()
    if row:
        return row[0], row[1]
    return None

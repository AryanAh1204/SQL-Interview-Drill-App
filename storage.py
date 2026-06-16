import sqlite3
from datetime import datetime
from pathlib import Path

import pandas as pd

DB_PATH = Path(__file__).parent / "drill_history.db"


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS attempts (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp   TEXT NOT NULL,
            dataset     TEXT NOT NULL,
            topic       TEXT NOT NULL,
            difficulty  TEXT NOT NULL,
            time_seconds REAL NOT NULL,
            passed      INTEGER NOT NULL,
            my_sql      TEXT
        )
    """)
    conn.commit()
    return conn


def log_attempt(
    dataset: str,
    topic: str,
    difficulty: str,
    time_seconds: float,
    passed: bool,
    my_sql: str,
) -> None:
    conn = _get_conn()
    conn.execute(
        "INSERT INTO attempts (timestamp, dataset, topic, difficulty, time_seconds, passed, my_sql) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (datetime.utcnow().isoformat(), dataset, topic, difficulty, time_seconds, int(passed), my_sql),
    )
    conn.commit()
    conn.close()


def get_stats() -> pd.DataFrame:
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
                    FROM attempts a2 WHERE a2.dataset = a.dataset AND a2.topic = a.topic
                ) WHERE rn IN ((cnt+1)/2, (cnt+2)/2)
                ), 1
            ) AS median_time_seconds
        FROM attempts a
        GROUP BY dataset, topic
        ORDER BY pass_rate ASC
        """,
        conn,
    )
    conn.close()
    return df


def get_weakest_topic() -> tuple[str, str] | None:
    conn = _get_conn()
    row = conn.execute(
        """
        SELECT dataset, topic, AVG(passed) AS pr
        FROM attempts
        GROUP BY dataset, topic
        HAVING COUNT(*) >= 2
        ORDER BY pr ASC
        LIMIT 1
        """
    ).fetchone()
    conn.close()
    if row:
        return row[0], row[1]
    return None

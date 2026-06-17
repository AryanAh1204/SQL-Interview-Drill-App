import hashlib
import hmac
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

_PBKDF2_ROUNDS = 200_000
_DB_PATH = Path(__file__).parent / "drill_history.db"
_DATABASE_URL = os.environ.get("DATABASE_URL")


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Backend — Postgres when DATABASE_URL is set, else SQLite ──────────────────
if _DATABASE_URL:
    import psycopg2

    @contextmanager
    def _connection():
        conn = psycopg2.connect(_DATABASE_URL)
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _q(sql: str) -> str:
        return sql.replace("?", "%s")

    def _execute(sql: str, params: tuple = ()) -> None:
        with _connection() as conn:
            conn.cursor().execute(_q(sql), params)

    def _fetchone(sql: str, params: tuple = ()):
        with _connection() as conn:
            cur = conn.cursor()
            cur.execute(_q(sql), params)
            return cur.fetchone()

    def _fetchall(sql: str, params: tuple = ()):
        with _connection() as conn:
            cur = conn.cursor()
            cur.execute(_q(sql), params)
            return cur.fetchall()

    def _read_df(sql: str, params: tuple = ()) -> pd.DataFrame:
        with _connection() as conn:
            return pd.read_sql_query(_q(sql), conn, params=params)

    def _init_schema() -> None:
        with _connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    username      TEXT PRIMARY KEY,
                    password_hash TEXT NOT NULL,
                    created_at    TEXT NOT NULL
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS attempts (
                    id            SERIAL PRIMARY KEY,
                    username      TEXT NOT NULL DEFAULT 'guest',
                    timestamp     TEXT NOT NULL,
                    dataset       TEXT NOT NULL,
                    topic         TEXT NOT NULL,
                    difficulty    TEXT NOT NULL,
                    time_seconds  REAL NOT NULL,
                    passed        INTEGER NOT NULL,
                    my_sql        TEXT
                )
            """)
            cur.execute("""
                SELECT column_name FROM information_schema.columns
                WHERE table_name = 'attempts' AND column_name = 'username'
            """)
            if not cur.fetchone():
                cur.execute(
                    "ALTER TABLE attempts ADD COLUMN username TEXT NOT NULL DEFAULT 'guest'"
                )

else:
    @contextmanager
    def _connection():
        conn = sqlite3.connect(_DB_PATH)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _q(sql: str) -> str:
        return sql

    def _execute(sql: str, params: tuple = ()) -> None:
        with _connection() as conn:
            conn.execute(sql, params)

    def _fetchone(sql: str, params: tuple = ()):
        with _connection() as conn:
            return conn.execute(sql, params).fetchone()

    def _fetchall(sql: str, params: tuple = ()):
        with _connection() as conn:
            return conn.execute(sql, params).fetchall()

    def _read_df(sql: str, params: tuple = ()) -> pd.DataFrame:
        with _connection() as conn:
            return pd.read_sql_query(sql, conn, params=params)

    def _init_schema() -> None:
        with _connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    username      TEXT PRIMARY KEY,
                    password_hash TEXT NOT NULL,
                    created_at    TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS attempts (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    username     TEXT NOT NULL DEFAULT 'guest',
                    timestamp    TEXT NOT NULL,
                    dataset      TEXT NOT NULL,
                    topic        TEXT NOT NULL,
                    difficulty   TEXT NOT NULL,
                    time_seconds REAL NOT NULL,
                    passed       INTEGER NOT NULL,
                    my_sql       TEXT
                )
            """)
            cols = [r[1] for r in conn.execute("PRAGMA table_info(attempts)").fetchall()]
            if "username" not in cols:
                conn.execute(
                    "ALTER TABLE attempts ADD COLUMN username TEXT NOT NULL DEFAULT 'guest'"
                )


_init_schema()


# ── Password hashing ───────────────────────────────────────────────────────────
def _hash_password(password: str, salt: bytes | None = None) -> str:
    """Salted PBKDF2-SHA256 → 'pbkdf2$<salt_hex>$<hash_hex>'."""
    if salt is None:
        salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ROUNDS)
    return f"pbkdf2${salt.hex()}${dk.hex()}"


def _verify_password(password: str, stored: str) -> bool:
    """Constant-time verification; supports legacy bare-sha256 hashes."""
    try:
        if stored.startswith("pbkdf2$"):
            _, salt_hex, hash_hex = stored.split("$")
            candidate = hashlib.pbkdf2_hmac(
                "sha256", password.encode(), bytes.fromhex(salt_hex), _PBKDF2_ROUNDS
            ).hex()
            return hmac.compare_digest(candidate, hash_hex)
        return hmac.compare_digest(hashlib.sha256(password.encode()).hexdigest(), stored)
    except Exception:
        return False


# ── Auth ───────────────────────────────────────────────────────────────────────
def register_user(username: str, password: str) -> tuple[bool, str]:
    username = username.strip().lower()
    if not username or not password:
        return False, "Username and password are required."
    if _fetchone("SELECT 1 FROM users WHERE username = ?", (username,)):
        return False, "That username is taken."
    _execute(
        "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
        (username, _hash_password(password), _utcnow_iso()),
    )
    return True, "Account created."


def login_user(username: str, password: str) -> tuple[bool, str]:
    username = username.strip().lower()
    row = _fetchone("SELECT password_hash FROM users WHERE username = ?", (username,))
    if not row:
        return False, "No account with that username."
    if not _verify_password(password, row[0]):
        return False, "Incorrect password."
    # Transparently upgrade legacy unsalted hashes on successful login
    if not row[0].startswith("pbkdf2$"):
        _execute(
            "UPDATE users SET password_hash = ? WHERE username = ?",
            (_hash_password(password), username),
        )
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
    _execute(
        "INSERT INTO attempts "
        "(username, timestamp, dataset, topic, difficulty, time_seconds, passed, my_sql) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (username, _utcnow_iso(), dataset, topic, difficulty, time_seconds, int(passed), my_sql),
    )


def get_stats(username: str) -> pd.DataFrame:
    return _read_df(
        """
        SELECT
            dataset,
            topic,
            COUNT(*) AS attempts,
            ROUND(CAST(AVG(passed) * 100 AS numeric), 1) AS pass_rate,
            ROUND(CAST(AVG(time_seconds) AS numeric), 1) AS avg_time_seconds
        FROM attempts
        WHERE username = ?
        GROUP BY dataset, topic
        ORDER BY pass_rate ASC
        """,
        (username,),
    )


def get_daily_stats(username: str) -> pd.DataFrame:
    return _read_df(
        """
        SELECT
            substr(timestamp, 1, 10) AS day,
            COUNT(*)                 AS attempts,
            SUM(passed)              AS passed,
            ROUND(CAST(AVG(passed) * 100 AS numeric), 1) AS pass_rate,
            ROUND(CAST(AVG(time_seconds) AS numeric), 1) AS avg_time_seconds
        FROM attempts
        WHERE username = ?
        GROUP BY day
        ORDER BY day
        """,
        (username,),
    )


def get_streak(username: str) -> dict:
    from datetime import date, timedelta

    rows = _fetchall(
        "SELECT DISTINCT substr(timestamp, 1, 10) FROM attempts WHERE username = ?",
        (username,),
    )
    today_count = _fetchone(
        "SELECT COUNT(*) FROM attempts WHERE username = ? "
        "AND substr(timestamp, 1, 10) = ?",
        (username, date.today().isoformat()),
    )[0]

    days = sorted({date.fromisoformat(r[0]) for r in rows if r[0]})
    if not days:
        return {"current": 0, "best": 0, "today": 0}

    best = run = 1
    for prev, cur in zip(days, days[1:]):
        run = run + 1 if (cur - prev).days == 1 else 1
        best = max(best, run)

    today = date.today()
    current = 0
    if days[-1] in (today, today - timedelta(days=1)):
        current = 1
        for prev, cur in zip(reversed(days), reversed(days[:-1])):
            if (prev - cur).days == 1:
                current += 1
            else:
                break
    return {"current": current, "best": best, "today": today_count}


def get_weakest_topic(username: str) -> tuple[str, str] | None:
    row = _fetchone(
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
    )
    if row:
        return row[0], row[1]
    return None

import hashlib
import hmac
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

DB_PATH = Path(__file__).parent / "drill_history.db"

# PBKDF2 parameters — salted, slow, and verified in constant time.
_PBKDF2_ROUNDS = 200_000


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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


def _hash_password(password: str, salt: bytes | None = None) -> str:
    """Return a salted PBKDF2-SHA256 hash, encoded as 'pbkdf2$<salt_hex>$<hash_hex>'."""
    if salt is None:
        salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ROUNDS)
    return f"pbkdf2${salt.hex()}${dk.hex()}"


def _verify_password(password: str, stored: str) -> bool:
    """Constant-time verification. Supports legacy bare-sha256 hashes for migration."""
    try:
        if stored.startswith("pbkdf2$"):
            _, salt_hex, hash_hex = stored.split("$")
            candidate = hashlib.pbkdf2_hmac(
                "sha256", password.encode(), bytes.fromhex(salt_hex), _PBKDF2_ROUNDS
            ).hex()
            return hmac.compare_digest(candidate, hash_hex)
        # Legacy unsalted sha256 (pre-upgrade accounts)
        return hmac.compare_digest(hashlib.sha256(password.encode()).hexdigest(), stored)
    except Exception:
        return False


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
        (username, _hash_password(password), _utcnow_iso()),
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
    if not row:
        return False, "No account with that username."
    if not _verify_password(password, row[0]):
        return False, "Incorrect password."
    # Transparently upgrade legacy unsalted hashes on successful login
    if not row[0].startswith("pbkdf2$"):
        conn.execute(
            "UPDATE users SET password_hash = ? WHERE username = ?",
            (_hash_password(password), username),
        )
        conn.commit()
    conn.close()
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
        (username, _utcnow_iso(), dataset, topic, difficulty, time_seconds, int(passed), my_sql),
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


def get_daily_stats(username: str) -> pd.DataFrame:
    """Per-day attempts, passes, pass-rate %, and avg time for charting."""
    conn = _get_conn()
    df = pd.read_sql_query(
        """
        SELECT
            substr(timestamp, 1, 10) AS day,
            COUNT(*)                 AS attempts,
            SUM(passed)              AS passed,
            ROUND(AVG(passed) * 100, 1) AS pass_rate,
            ROUND(AVG(time_seconds), 1) AS avg_time_seconds
        FROM attempts
        WHERE username = ?
        GROUP BY day
        ORDER BY day
        """,
        conn,
        params=(username,),
    )
    conn.close()
    return df


def get_streak(username: str) -> dict:
    """Return {'current': int, 'best': int, 'today': int} from attempt days."""
    from datetime import date, timedelta

    conn = _get_conn()
    rows = conn.execute(
        "SELECT DISTINCT substr(timestamp, 1, 10) FROM attempts WHERE username = ?",
        (username,),
    ).fetchall()
    today_count = conn.execute(
        "SELECT COUNT(*) FROM attempts WHERE username = ? "
        "AND substr(timestamp, 1, 10) = ?",
        (username, date.today().isoformat()),
    ).fetchone()[0]
    conn.close()

    days = sorted({date.fromisoformat(r[0]) for r in rows if r[0]})
    if not days:
        return {"current": 0, "best": 0, "today": 0}

    # Best streak: longest run of consecutive calendar days.
    best = run = 1
    for prev, cur in zip(days, days[1:]):
        run = run + 1 if (cur - prev).days == 1 else 1
        best = max(best, run)

    # Current streak: consecutive days ending today or yesterday.
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

import re
import sqlite3
from pathlib import Path

import pandas as pd


def get_connection(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def introspect_schema(conn: sqlite3.Connection) -> dict[str, list[tuple[str, str]]]:
    schema: dict[str, list[tuple[str, str]]] = {}
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )
    tables = [r[0] for r in cur.fetchall()]
    for table in tables:
        cols_cur = conn.execute(f"PRAGMA table_info('{table}')")
        schema[table] = [(row[1], row[2]) for row in cols_cur.fetchall()]
    return schema


def _is_safe_sql(sql: str) -> tuple[bool, str]:
    stripped = sql.strip()
    if not stripped:
        return False, "Empty query."
    first_token = stripped.split()[0].upper()
    if first_token not in ("SELECT", "WITH"):
        return False, f"Only SELECT/WITH queries are allowed. Got: {first_token}"
    # Reject multiple statements: a semicolon followed by non-whitespace
    if re.search(r";\s*\S", stripped):
        return False, "Multiple statements are not allowed."
    # Secondary guard: scan for mutating keywords, but ignore string literals and
    # quoted identifiers so a legitimate SELECT containing e.g. 'please update'
    # is not falsely rejected. (The read-only connection is the real protection.)
    scrubbed = re.sub(r"'(?:[^']|'')*'", "''", stripped)   # single-quoted strings
    scrubbed = re.sub(r'"(?:[^"]|"")*"', '""', scrubbed)   # double-quoted identifiers
    upper = scrubbed.upper()
    for kw in ("INSERT", "UPDATE", "DELETE", "DROP", "CREATE", "ALTER", "ATTACH", "DETACH"):
        if re.search(rf"\b{kw}\b", upper):
            return False, f"Mutating keyword '{kw}' is not allowed."
    return True, ""


def safe_execute(
    sql: str, conn: sqlite3.Connection, limit: int = 5000
) -> tuple[pd.DataFrame | None, str | None]:
    ok, reason = _is_safe_sql(sql)
    if not ok:
        return None, reason
    try:
        conn.execute("PRAGMA query_only = ON")
        df = pd.read_sql_query(sql, conn)
        if len(df) > limit:
            df = df.head(limit)
        return df, None
    except Exception as e:
        return None, str(e)


def _round_floats(df: pd.DataFrame, decimals: int = 4) -> pd.DataFrame:
    df = df.copy()
    for col in df.select_dtypes(include="float").columns:
        df[col] = df[col].round(decimals)
    return df


_NULL_SENTINEL = "␀NULL␀"  # cannot collide with real data


def _normalise(df: pd.DataFrame, order_matters: bool) -> pd.DataFrame:
    """Round floats, (optionally) sort deterministically, and fill NULLs."""
    df = _round_floats(df.reset_index(drop=True))
    canon = [f"c{i}" for i in range(len(df.columns))]
    df.columns = canon
    if not order_matters and canon:
        # Deterministic, always-orderable sort (stringified) so mixed-type
        # columns never silently skip sorting and flip the comparison semantics.
        df = df.sort_values(by=canon, key=lambda s: s.astype(str)).reset_index(drop=True)
    return df.fillna(_NULL_SENTINEL)


def _frames_match(ref_sub: pd.DataFrame, user_sub: pd.DataFrame, order_matters: bool):
    """Return (passed, reason, ref_display_cols) comparing two equal-width frames."""
    ref_display = list(ref_sub.columns)
    ref_n = _normalise(ref_sub, order_matters)
    user_n = _normalise(user_sub, order_matters)
    if len(ref_n) != len(user_n):
        return False, f"Wrong row count: expected {len(ref_n)}, got {len(user_n)}", ref_display
    for i, (r_row, u_row) in enumerate(
        zip(ref_n.itertuples(index=False), user_n.itertuples(index=False))
    ):
        if r_row != u_row:
            j = next(idx for idx, (a, b) in enumerate(zip(r_row, u_row)) if a != b)
            return (
                False,
                f"Value mismatch at row {i+1}, column '{ref_display[j]}': "
                f"expected {r_row[j]!r}, got {u_row[j]!r}",
                ref_display,
            )
    return True, "All required columns and rows match.", ref_display


def compare_results(
    ref_df: pd.DataFrame,
    user_df: pd.DataFrame,
    required_cols: list[str],
    order_matters: bool,
) -> tuple[bool, str]:
    # Reference is projected to the required answer columns.
    ref_map = {c.lower(): c for c in ref_df.columns}
    ref_cols = [ref_map[c.lower()] for c in required_cols if c.lower() in ref_map]
    ref_sub = ref_df[ref_cols]
    k = len(ref_cols)

    # Primary path: the user's headers match the required names. Use them and
    # return the detailed result (so a genuine value mismatch is reported clearly).
    user_cols_lower = {c.lower() for c in user_df.columns}
    if all(c.lower() in user_cols_lower for c in required_cols):
        col_map = {c.lower(): c for c in user_df.columns}
        user_sub = user_df[[col_map[c.lower()] for c in required_cols]]
        passed, reason, _ = _frames_match(ref_sub, user_sub, order_matters)
        return passed, reason

    # Header-agnostic path: names don't match. Grade by DATA — try every
    # order-preserving combination of the user's columns of the right width, so
    # both aliased columns AND a superset of columns still pass when the rows match.
    if len(user_df.columns) < k:
        return False, (
            f"Wrong number of columns: expected {k} "
            f"({', '.join(required_cols)}), got {len(user_df.columns)}"
        )

    from itertools import combinations

    last_reason = "Result rows do not match the expected answer."
    for combo in combinations(range(len(user_df.columns)), k):
        user_sub = user_df.iloc[:, list(combo)]
        passed, reason, _ = _frames_match(ref_sub, user_sub, order_matters)
        if passed:
            return True, reason
        last_reason = reason
    return False, last_reason


def result_diff(
    ref_df: pd.DataFrame,
    user_df: pd.DataFrame,
    required_cols: list[str],
) -> dict:
    """Compare result sets and return a structured diff for teaching on failure.

    Returns: {
        aligned: bool,                  # could we line up the columns?
        expected_rows, your_rows: int,
        missing: DataFrame,             # rows in the expected set you didn't return
        extra: DataFrame,               # rows you returned that aren't expected
        summary: str,
    }
    """
    ref_map = {c.lower(): c for c in ref_df.columns}
    ref_cols = [ref_map[c.lower()] for c in required_cols if c.lower() in ref_map]
    ref_sub = ref_df[ref_cols]
    k = len(ref_cols)

    # Align the user's columns the same way grading does.
    user_cols_lower = {c.lower() for c in user_df.columns}
    if user_df is None:
        user_sub = None
    elif all(c.lower() in user_cols_lower for c in required_cols):
        col_map = {c.lower(): c for c in user_df.columns}
        user_sub = user_df[[col_map[c.lower()] for c in required_cols]]
    elif len(user_df.columns) == k:
        user_sub = user_df
    else:
        # Can't line columns up — only a count-level summary is meaningful.
        return {
            "aligned": False,
            "expected_rows": len(ref_sub),
            "your_rows": 0 if user_df is None else len(user_df),
            "missing": ref_sub.head(0),
            "extra": ref_sub.head(0),
            "summary": (
                f"Expected {k} column(s) ({', '.join(required_cols)}); "
                f"you returned {0 if user_df is None else len(user_df.columns)}."
            ),
        }

    ref_n = _normalise(ref_sub, order_matters=False)
    user_n = _normalise(user_sub, order_matters=False)
    merged = ref_n.merge(user_n, how="outer", indicator=True)
    missing = merged[merged["_merge"] == "left_only"].drop(columns="_merge")
    extra = merged[merged["_merge"] == "right_only"].drop(columns="_merge")

    # Restore readable names + NULL labels for display.
    def _pretty(df):
        df = df.copy()
        df.columns = list(ref_cols)
        return df.replace(_NULL_SENTINEL, "NULL")

    return {
        "aligned": True,
        "expected_rows": len(ref_sub),
        "your_rows": len(user_sub),
        "missing": _pretty(missing),
        "extra": _pretty(extra),
        "summary": (
            f"Expected {len(ref_sub)} rows; you returned {len(user_sub)}. "
            f"{len(missing)} expected row(s) missing, {len(extra)} unexpected row(s)."
        ),
    }

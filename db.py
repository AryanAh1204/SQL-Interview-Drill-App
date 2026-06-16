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
    # Reject dangerous keywords as a secondary guard
    upper = stripped.upper()
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


def compare_results(
    ref_df: pd.DataFrame,
    user_df: pd.DataFrame,
    required_cols: list[str],
    order_matters: bool,
) -> tuple[bool, str]:
    # Column presence check (case-insensitive)
    user_cols_lower = {c.lower() for c in user_df.columns}
    missing = [c for c in required_cols if c.lower() not in user_cols_lower]
    if missing:
        return False, f"Missing required column(s): {', '.join(missing)}"

    # Align to required_cols (case-insensitive column selection)
    col_map = {c.lower(): c for c in user_df.columns}
    ref_map = {c.lower(): c for c in ref_df.columns}

    try:
        ref_sub = ref_df[[ref_map[c.lower()] for c in required_cols if c.lower() in ref_map]]
        user_sub = user_df[[col_map[c.lower()] for c in required_cols if c.lower() in col_map]]
    except KeyError as e:
        return False, f"Column mapping error: {e}"

    ref_sub = _round_floats(ref_sub.reset_index(drop=True))
    user_sub = _round_floats(user_sub.reset_index(drop=True))

    # Normalise column names to lowercase for comparison
    ref_sub.columns = [c.lower() for c in ref_sub.columns]
    user_sub.columns = [c.lower() for c in user_sub.columns]

    if not order_matters:
        try:
            ref_sub = ref_sub.sort_values(by=list(ref_sub.columns)).reset_index(drop=True)
            user_sub = user_sub.sort_values(by=list(user_sub.columns)).reset_index(drop=True)
        except Exception:
            pass

    if len(ref_sub) != len(user_sub):
        return False, (
            f"Wrong row count: expected {len(ref_sub)}, got {len(user_sub)}"
        )

    # Row-by-row comparison
    for i, (r_row, u_row) in enumerate(zip(ref_sub.itertuples(index=False), user_sub.itertuples(index=False))):
        if r_row != u_row:
            col = ref_sub.columns[
                next(j for j, (a, b) in enumerate(zip(r_row, u_row)) if a != b)
            ]
            exp_val = getattr(r_row, col.replace(" ", "_"))
            got_val = getattr(u_row, col.replace(" ", "_"))
            return False, (
                f"Value mismatch at row {i+1}, column '{col}': "
                f"expected {exp_val!r}, got {got_val!r}"
            )

    return True, "All required columns and rows match."

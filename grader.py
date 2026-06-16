import sqlite3

import anthropic
import pandas as pd

from db import compare_results, safe_execute


def grade(
    user_sql: str,
    ref_df: pd.DataFrame,
    question: dict,
    conn: sqlite3.Connection,
) -> dict:
    user_df, err = safe_execute(user_sql, conn)
    if err:
        return {"passed": False, "reason": f"Query error: {err}", "user_df": None}

    passed, reason = compare_results(
        ref_df,
        user_df,
        question["required_columns"],
        question["order_matters"],
    )
    return {"passed": passed, "reason": reason, "user_df": user_df}


def get_style_feedback(
    user_sql: str,
    ref_sql: str,
    question_text: str,
    client: anthropic.Anthropic,
) -> str:
    prompt = f"""You are a senior SQL interviewer at a top tech/finance firm reviewing a candidate's query.

Question asked: {question_text}

Candidate's query:
{user_sql}

Reference (optimal) query:
{ref_sql}

The candidate's answer was CORRECT (result sets matched). Now give brief style/efficiency feedback in ≤4 sentences.
Focus only on: SQL idioms, efficiency, readability, or approach (e.g. "a window function would be cleaner than a self-join here").
Do NOT comment on correctness. Do NOT reveal the reference query. Do NOT say "the reference query uses...".
Be direct and constructive, as a Piramal/McKinsey analyst interviewer would be."""

    resp = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.content[0].text.strip()

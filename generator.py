import json
import re
import sqlite3
from pathlib import Path

import anthropic

from db import introspect_schema, safe_execute

TOPICS = [
    "single-table aggregation",
    "GROUP BY + HAVING",
    "CTEs",
    "window functions (ROW_NUMBER / RANK / DENSE_RANK)",
    "LAG / LEAD",
    "running totals / rolling aggregates",
    "multi-table JOIN",
    "correlated subqueries",
]

SYSTEM_PROMPT = """You are a SQL interview question generator for data analyst and data engineering interviews.
You produce questions grounded in real industry datasets and frame them as authentic business analyst tasks.

Rules:
1. Return ONLY valid JSON — no markdown, no explanation.
2. reference_sql must use only tables and columns that exist in the provided schema.
3. reference_sql must be a single SELECT or WITH statement — never INSERT/UPDATE/DELETE/DROP.
4. required_columns must be a subset of columns that appear in the SELECT output.
5. business_context should sound like a real stakeholder request (e.g. "The Head of Revenue asks...").
6. Vary difficulty: easy = single table simple aggregate; medium = JOIN or window; hard = CTE + window + subquery.
"""

JSON_SCHEMA = """{
  "question": "<the question text shown to the user>",
  "business_context": "<2-3 sentence stakeholder framing>",
  "topic": "<topic from the provided list>",
  "difficulty": "<easy|medium|hard>",
  "reference_sql": "<the correct SQL query>",
  "required_columns": ["<col1>", "<col2>"],
  "order_matters": <true|false>
}"""


def _schema_to_text(schema: dict) -> str:
    lines = []
    for table, cols in schema.items():
        col_strs = ", ".join(f"{name} ({dtype})" for name, dtype in cols)
        lines.append(f"  {table}({col_strs})")
    return "\n".join(lines)


def _extract_json(text: str) -> dict:
    text = text.strip()
    # Strip markdown fences if present
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return json.loads(text)


def generate_question(
    schema: dict,
    dataset_meta: dict,
    topic: str,
    difficulty: str,
    conn: sqlite3.Connection,
    client: anthropic.Anthropic,
    max_retries: int = 4,
) -> dict:
    schema_text = _schema_to_text(schema)
    user_msg = f"""Dataset: {dataset_meta['industry']}
Context: {dataset_meta['description']}

Schema:
{schema_text}

Generate a {difficulty} SQL interview question on the topic: "{topic}"

Return exactly this JSON structure:
{JSON_SCHEMA}"""

    for attempt in range(max_retries):
        try:
            resp = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=1500,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_msg}],
            )
            raw = resp.content[0].text
            q = _extract_json(raw)

            # Validate required fields
            for field in ("question", "business_context", "reference_sql", "required_columns", "order_matters"):
                if field not in q:
                    raise ValueError(f"Missing field: {field}")

            # Validate reference SQL executes cleanly and returns rows
            df, err = safe_execute(q["reference_sql"], conn)
            if err:
                raise ValueError(f"reference_sql error: {err}")
            if df is None or len(df) == 0:
                raise ValueError("reference_sql returned zero rows")

            # Validate required_columns appear in result
            result_cols_lower = {c.lower() for c in df.columns}
            missing = [c for c in q["required_columns"] if c.lower() not in result_cols_lower]
            if missing:
                raise ValueError(f"required_columns not in output: {missing}")

            q["_ref_df"] = df  # cache result for grader
            return q

        except Exception as e:
            print(f"  Generation attempt {attempt + 1}/{max_retries} failed: {e}")
            if attempt == max_retries - 1:
                raise RuntimeError(
                    f"Failed to generate a valid question after {max_retries} attempts. Last error: {e}"
                )

    raise RuntimeError("Unreachable")

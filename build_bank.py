"""One-time script to generate a static question bank.

Run this ONCE (with a valid ANTHROPIC_API_KEY) to populate question_bank.json.
After that, the app reads from the bank and never calls the API for questions.

Usage:
    python build_bank.py [--per-combo N]
"""
import argparse
import json
import os
from pathlib import Path

import anthropic
from dotenv import load_dotenv

load_dotenv()

from datasets import DATASETS, ensure_datasets
from db import get_connection, introspect_schema
from generator import TOPICS, generate_question

BANK_PATH = Path(__file__).parent / "question_bank.json"


def build(per_combo: int = 1):
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise SystemExit("Set ANTHROPIC_API_KEY in .env before building the bank.")
    client = anthropic.Anthropic(api_key=api_key)

    available = ensure_datasets()
    difficulties = ["easy", "medium", "hard"]

    # Load any existing bank so we can append / resume
    bank = []
    if BANK_PATH.exists():
        bank = json.loads(BANK_PATH.read_text())
        print(f"Loaded existing bank with {len(bank)} questions.")

    total_targets = len(available) * len(TOPICS) * len(difficulties) * per_combo
    done = 0

    for ds_id, path in available.items():
        conn = get_connection(path)
        schema = introspect_schema(conn)
        for topic in TOPICS:
            for difficulty in difficulties:
                for _ in range(per_combo):
                    done += 1
                    label = f"[{done}/{total_targets}] {ds_id} / {topic} / {difficulty}"
                    try:
                        q = generate_question(
                            schema=schema,
                            dataset_meta=DATASETS[ds_id],
                            topic=topic,
                            difficulty=difficulty,
                            conn=conn,
                            client=client,
                        )
                        q.pop("_ref_df", None)  # don't store the DataFrame
                        q["dataset"] = ds_id
                        bank.append(q)
                        # Save incrementally so a crash doesn't lose progress
                        BANK_PATH.write_text(json.dumps(bank, indent=2))
                        print(f"  ✓ {label}")
                    except Exception as e:
                        print(f"  ✗ {label} — skipped ({str(e)[:80]})")
        conn.close()

    print(f"\nDone. Bank now has {len(bank)} questions at {BANK_PATH}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-combo", type=int, default=1, help="questions per dataset/topic/difficulty")
    args = ap.parse_args()
    build(args.per_combo)

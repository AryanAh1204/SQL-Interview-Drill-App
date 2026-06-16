"""Static question bank loader — replaces runtime API question generation."""
import json
import random
from pathlib import Path

BANK_PATH = Path(__file__).parent / "question_bank.json"


def load_bank() -> list[dict]:
    if not BANK_PATH.exists():
        return []
    return json.loads(BANK_PATH.read_text())


def available_topics(bank: list[dict], dataset: str | None = None) -> list[str]:
    qs = [q for q in bank if dataset is None or q["dataset"] == dataset]
    return sorted({q["topic"] for q in qs})


def pick_question(
    bank: list[dict],
    dataset: str,
    topic: str | None = None,
    difficulty: str | None = None,
    exclude: set[int] | None = None,
) -> tuple[dict | None, int | None]:
    """Pick a random matching question. Returns (question, index_in_bank)."""
    exclude = exclude or set()
    candidates = [
        (i, q)
        for i, q in enumerate(bank)
        if q["dataset"] == dataset
        and (topic is None or q["topic"] == topic)
        and (difficulty is None or q["difficulty"] == difficulty)
        and i not in exclude
    ]
    # If everything is excluded (user exhausted the pool), allow repeats
    if not candidates:
        candidates = [
            (i, q)
            for i, q in enumerate(bank)
            if q["dataset"] == dataset
            and (topic is None or q["topic"] == topic)
            and (difficulty is None or q["difficulty"] == difficulty)
        ]
    if not candidates:
        return None, None
    idx, q = random.choice(candidates)
    return q, idx

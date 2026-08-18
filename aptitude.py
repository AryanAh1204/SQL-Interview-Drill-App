"""Live aptitude question generation via NVIDIA NIM.

NIM exposes an OpenAI-compatible REST endpoint, so this talks to it with plain
`requests` — no extra SDK dependency.

Unlike the SQL bank (static, pre-built by build_bank.py), aptitude questions are
generated on demand: there's no schema to ground them in and no reference query
to execute, so there's nothing to gain from baking them ahead of time.

Set NVIDIA_API_KEY in .env (or as a host secret). NVIDIA_MODEL is optional and
overrides the default model — useful when a model id is retired.

    python aptitude.py --list-models    # what your key can actually call
    python aptitude.py --selfcheck      # offline validation tests, no API call
"""
import json
import os
import random
import re

import requests

NIM_BASE = "https://integrate.api.nvidia.com/v1"
# Chosen by measurement, not by size. On the free tier the big dense models
# (llama-3.1-70b, llama-3.3-70b) take 60s+ or time out outright, and the small
# ones (llama-3.1-8b) emit self-contradictory arithmetic. This MoE reasoning
# model answered correctly in ~10s across trials. NVIDIA retires ids
# periodically — override with NVIDIA_MODEL; see --list-models.
DEFAULT_MODEL = os.getenv("NVIDIA_MODEL") or "nvidia/nemotron-3-super-120b-a12b"

DIFFICULTIES = ["easy", "medium", "hard"]

# Each topic is its own section in the UI. Areas are listed individually rather
# than as one blob so the prefetcher can hand each parallel worker a different
# one — without that, five workers given identical prompts return near-identical
# questions.
TOPICS = {
    "Quantitative Aptitude": [
        "percentages", "ratio & proportion", "time-speed-distance", "time & work",
        "profit & loss", "averages", "mixtures & alligation",
        "simple & compound interest", "number systems", "permutations & probability",
    ],
    "Logical Reasoning": [
        "number series", "letter series", "blood relations", "syllogisms",
        "seating arrangements", "coding-decoding", "direction sense",
        "statement and conclusion", "odd one out", "calendar & clock puzzles",
    ],
    "Data Interpretation": [
        "totals and subtotals from a table", "year-on-year growth rates",
        "ratios between segments", "percentage share of a whole",
        "averages across categories", "finding the largest/smallest mover",
    ],
    "Verbal Ability": [
        "sentence correction", "synonyms in context", "antonyms in context",
        "para-jumbles", "critical reasoning", "reading-comprehension inference",
        "idioms and phrases", "fill in the blanks",
    ],
}

# Extra per-topic instruction, where the topic needs one beyond its areas.
TOPIC_NOTES = {
    "Data Interpretation": (
        "Include the data inline as a markdown table in the question text so the "
        "question is fully self-contained."
    ),
}

SYSTEM_PROMPT = """You write aptitude test questions for campus placement rounds and competitive exams (CAT / GRE / company aptitude tests).

Rules:
1. Return ONLY valid JSON — no markdown fences, no commentary, no preamble.
2. Provide exactly 4 options.
3. "answer_index" is 0-based and points at the single correct option.
4. Exactly one option is correct, and the other three must be definitively WRONG.
   Distractors should be the answers a candidate reaches by making a common mistake —
   never filler, and never a statement that is also true. For "which of the following
   can be inferred" style questions especially: check each distractor and confirm it is
   actually false given the question. Two defensible options makes the question invalid.
5. The question must be fully self-contained: solvable from its own text alone. Never
   refer to an image, an external chart, or "the passage above" unless you include it.
6. CRITICAL — the question must be fully DETERMINED. Every quantity needed to reach the
   answer must be stated in the question. Before answering, check that you are not
   assuming any value the question never gave you. If your solution needs a number that
   is not in the question, the question is broken: rewrite it to state that number.
7. Solve the question yourself, step by step, before choosing answer_index. The
   "explanation" must derive the answer only from quantities stated in the question —
   if a step introduces an unstated assumption, the question is invalid.
8. Keep the arithmetic clean enough to do without a calculator.
9. "explanation" is the worked solution in 2-4 short steps, ending with the answer.
"""

JSON_SCHEMA = """{
  "question": "<the question text; include any table/passage inline>",
  "options": ["<option A>", "<option B>", "<option C>", "<option D>"],
  "answer_index": <0|1|2|3>,
  "explanation": "<2-4 step worked solution>"
}"""


def _extract_json(text: str) -> dict:
    """Parse the model's reply into a dict, tolerating the usual wrappers."""
    text = text.strip()
    # Reasoning models emit a <think>...</think> preamble before the answer.
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    # Strip markdown fences.
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    # Some models still wrap prose around the object — fall back to the outermost braces.
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise
        return json.loads(text[start:end + 1])


def validate(q: dict) -> dict:
    """Raise ValueError unless `q` is a well-formed MCQ. Returns it on success.

    We can't verify the answer is *correct* — there's no oracle for arithmetic the
    way safe_execute() is an oracle for SQL — but shape errors and degenerate
    option sets are catchable, and they're the failures that actually show up.
    """
    for field in ("question", "options", "answer_index", "explanation"):
        if field not in q:
            raise ValueError(f"missing field: {field}")

    if not isinstance(q["question"], str) or not q["question"].strip():
        raise ValueError("question is empty")
    if not isinstance(q["explanation"], str) or not q["explanation"].strip():
        raise ValueError("explanation is empty")

    opts = q["options"]
    if not isinstance(opts, list) or len(opts) != 4:
        raise ValueError(f"expected 4 options, got {len(opts) if isinstance(opts, list) else type(opts).__name__}")
    if any(not isinstance(o, str) or not o.strip() for o in opts):
        raise ValueError("an option is empty or not a string")
    # Duplicate options make the question unanswerable — a real failure mode.
    normalised = [o.strip().lower() for o in opts]
    if len(set(normalised)) != 4:
        raise ValueError("options are not distinct")

    idx = q["answer_index"]
    if isinstance(idx, str) and idx.strip().isdigit():
        idx = int(idx)  # models sometimes stringify it
    if not isinstance(idx, int) or isinstance(idx, bool) or not 0 <= idx <= 3:
        raise ValueError(f"answer_index out of range: {q['answer_index']!r}")
    q["answer_index"] = idx

    return q


def _post(api_key: str, payload: dict, timeout: int) -> dict:
    resp = requests.post(
        f"{NIM_BASE}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
        json=payload,
        timeout=timeout,
    )
    # NVIDIA returns 403 (not 401) for a bad/expired key — both mean "don't retry".
    if resp.status_code in (401, 403):
        raise RuntimeError(
            f"NVIDIA rejected the API key ({resp.status_code}). "
            f"Check NVIDIA_API_KEY — get one at https://build.nvidia.com."
        )
    if resp.status_code == 404:
        raise RuntimeError(
            f"Model '{payload['model']}' not found (404). "
            f"Run `python aptitude.py --list-models` and set NVIDIA_MODEL to a live id."
        )
    if resp.status_code == 429:
        raise RuntimeError("NVIDIA rate limit hit (429). Wait a moment and retry.")
    resp.raise_for_status()
    return resp.json()


def list_models(api_key: str, timeout: int = 30) -> list[str]:
    """Model ids this key can call — the fix for a retired DEFAULT_MODEL."""
    resp = requests.get(
        f"{NIM_BASE}/models",
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=timeout,
    )
    resp.raise_for_status()
    return sorted(m["id"] for m in resp.json().get("data", []))


def generate_question(
    topic: str,
    difficulty: str,
    api_key: str,
    model: str | None = None,
    avoid: list[str] | None = None,
    focus: str | None = None,
    max_retries: int = 2,
    timeout: int = 45,
) -> dict:
    """Generate one validated MCQ. Raises RuntimeError if all retries fail.

    `avoid` is a list of recently-shown question texts — passed to the model so a
    session doesn't keep serving the same three percentage problems.
    """
    if not api_key:
        raise RuntimeError("No NVIDIA API key. Set NVIDIA_API_KEY in .env or host secrets.")
    if topic not in TOPICS:
        raise ValueError(f"unknown topic: {topic}")

    model = model or DEFAULT_MODEL
    avoid_block = ""
    if avoid:
        recent = "\n".join(f"- {t[:160]}" for t in avoid[-8:])
        avoid_block = (
            f"\n\nDo NOT repeat or trivially rephrase any of these recently used questions:\n{recent}"
        )

    # A specific area beats "pick something from this list": parallel workers given
    # the same open-ended prompt converge on the same textbook question.
    area = focus or random.choice(TOPICS[topic])
    note = TOPIC_NOTES.get(topic, "")
    user_msg = (
        f"Generate ONE {difficulty} aptitude question on: {topic}\n"
        f"Specifically about: {area}\n"
        f"{note}\n"
        f"{avoid_block}\n\n"
        f"Return exactly this JSON structure:\n{JSON_SCHEMA}"
    )

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        # Reasoning models spend tokens thinking BEFORE writing `content`, and that
        # thinking counts against this budget. Too low and the reply comes back with
        # an empty/truncated content field — the whole call wasted. The answer itself
        # needs ~300; the rest is headroom for reasoning.
        "max_tokens": 2400,
        # High-ish temperature: these are generated live and repetition is the
        # main way the feature disappoints.
        "temperature": 0.9,
        "top_p": 0.95,
        # NIM honours OpenAI-style constrained decoding. This is the single biggest
        # latency win: without it, a reply wrapped in prose fails json.loads and
        # costs a whole extra generation to retry.
        "response_format": {"type": "json_object"},
    }

    last_err = None
    for attempt in range(max_retries):
        try:
            data = _post(api_key, payload, timeout)
            choice = data["choices"][0]
            raw = choice["message"].get("content")
            if not raw or not raw.strip():
                # Reasoning model ran out of budget while thinking, so it never got
                # to the answer. Distinct from malformed JSON — say so plainly.
                raise ValueError(
                    f"model returned no content (finish_reason="
                    f"{choice.get('finish_reason')}); try raising max_tokens"
                )
            q = validate(_extract_json(raw))
            q["topic"] = topic
            q["difficulty"] = difficulty
            return q
        except RuntimeError:
            raise  # auth / missing model / rate limit — retrying won't help
        except Exception as e:
            last_err = e

    raise RuntimeError(
        f"Could not generate a valid question after {max_retries} attempts. Last error: {last_err}"
    )


def _selfcheck():
    """Offline validation tests — no API key, no network."""
    good = {
        "question": "A train covers 120 km in 2 hours. What is its average speed?",
        "options": ["50 km/h", "60 km/h", "70 km/h", "80 km/h"],
        "answer_index": 1,
        "explanation": "Speed = distance / time = 120 / 2 = 60 km/h.",
    }
    assert validate(dict(good))["answer_index"] == 1

    # answer_index arriving as a string is common and should be coerced, not rejected.
    assert validate({**good, "answer_index": "2"})["answer_index"] == 2

    def rejects(bad, why):
        try:
            validate(bad)
        except ValueError:
            return
        raise AssertionError(f"should have rejected: {why}")

    rejects({**good, "options": ["a", "b", "c"]}, "3 options")
    rejects({**good, "options": ["a", "b", "c", "A"]}, "duplicate options")
    rejects({**good, "answer_index": 4}, "index out of range")
    rejects({**good, "answer_index": True}, "bool masquerading as int")
    rejects({**good, "question": "  "}, "blank question")
    rejects({k: v for k, v in good.items() if k != "explanation"}, "missing explanation")

    # Parser tolerance: fences and reasoning preambles.
    assert _extract_json('```json\n{"a": 1}\n```')["a"] == 1
    assert _extract_json('<think>hmm, let me see</think>\n{"a": 2}')["a"] == 2
    assert _extract_json('Here you go:\n{"a": 3}\nHope that helps!')["a"] == 3

    print("aptitude selfcheck: all passed")


if __name__ == "__main__":
    import argparse

    from dotenv import load_dotenv

    load_dotenv()

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--list-models", action="store_true", help="print model ids this key can call")
    ap.add_argument("--selfcheck", action="store_true", help="run offline validation tests")
    ap.add_argument("--try", dest="try_topic", metavar="TOPIC", help="generate one question and print it")
    args = ap.parse_args()

    if args.selfcheck:
        _selfcheck()
    elif args.list_models:
        key = os.getenv("NVIDIA_API_KEY", "")
        if not key:
            raise SystemExit("Set NVIDIA_API_KEY in .env first.")
        for mid in list_models(key):
            print(mid)
    elif args.try_topic:
        key = os.getenv("NVIDIA_API_KEY", "")
        if not key:
            raise SystemExit("Set NVIDIA_API_KEY in .env first.")
        print(json.dumps(generate_question(args.try_topic, "medium", key), indent=2))
    else:
        ap.print_help()


# ── Prefetch ───────────────────────────────────────────────────────────────────
# Generation takes ~10-25s, which is fine once but grating every question. The app
# keeps a small buffer per (topic, difficulty) and tops it up off the main thread.
BUFFER_TARGET = 5


def _is_duplicate(question: str, existing: list[str], threshold: float = 0.82) -> bool:
    """True if `question` is a near-restatement of something already seen."""
    import difflib

    q = " ".join(question.lower().split())
    for other in existing:
        o = " ".join(str(other).lower().split())
        if difflib.SequenceMatcher(None, q, o).ratio() >= threshold:
            return True
    return False


def fill_buffer(buffer, topic, difficulty, api_key, avoid, target=BUFFER_TARGET):
    """Top `buffer` up to `target` questions, fetching the shortfall in parallel.

    Runs on a worker thread, so it must never touch Streamlit APIs — it only
    appends to the plain list handed to it. list.append is atomic under the GIL,
    so the main thread can pop from the front while this appends to the back.
    A question that fails to generate is skipped: a short buffer is not an error.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    need = target - len(buffer)
    if need <= 0:
        return

    # Distinct area per worker so the batch doesn't come back five variations of
    # the same problem. Sampled without replacement when there are enough areas.
    areas = TOPICS[topic]
    picks = random.sample(areas, need) if need <= len(areas) else [
        random.choice(areas) for _ in range(need)
    ]

    with ThreadPoolExecutor(max_workers=need) as pool:
        futures = [
            pool.submit(generate_question, topic, difficulty, api_key, None, list(avoid), area)
            for area in picks
        ]
        for fut in as_completed(futures):
            try:
                q = fut.result()
            except Exception:
                continue  # a failed prefetch just means a shorter buffer
            # Same-area collisions still happen occasionally; drop near-dupes of
            # what's already queued rather than serve the same question twice.
            if not _is_duplicate(q["question"], [b["question"] for b in buffer] + list(avoid)):
                buffer.append(q)

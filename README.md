# SQL Drill ⚡

A dark, interactive SQL interview prep app. Business-framed questions across real industry datasets, graded by result-set equivalence — never by matching your SQL text.

## Setup

```bash
cd sql-drill
pip install -r requirements.txt
streamlit run app.py
```

That's it — **no API key required to run**. The app ships with a pre-built bank of
358 questions (`question_bank.json`), so it works forever with zero API cost.

On first run it downloads three industry datasets (~5 MB total) into `data/`:
- **Northwind** — B2B distribution (orders, customers, products)
- **Chinook** — Digital music store (tracks, invoices, customers)
- **Factbook** — Demographics / government (countries, GDP, population)

## Optional: AI style feedback

If you set an `ANTHROPIC_API_KEY` (in `.env` locally or Streamlit Cloud secrets),
the app adds a short "interviewer style feedback" note after each correct answer.
Without a key, everything else works exactly the same — questions and grading are
fully offline.

```bash
cp .env.example .env   # then add your key
```

## Aptitude section

A fourth tab covers non-SQL placement prep — **Quantitative Aptitude**, **Logical
Reasoning**, **Data Interpretation**, and **Verbal Ability**, each its own section.

Unlike the SQL bank (static, pre-built), these are generated **live** on each
request via [NVIDIA NIM](https://build.nvidia.com), so the pool never runs out and
there's nothing to memorise. That means the tab needs a key at runtime:

```bash
NVIDIA_API_KEY=nvapi-...   # in .env locally, or as a host secret when deployed
```

Without a key the tab shows a setup notice and the rest of the app is unaffected.
Answers are graded locally by option match — no API call is needed to score, only
to fetch the question.

Generation takes ~10-25s, so the app keeps a buffer of 5 ready questions per
(section, difficulty) and tops it up on a background thread while you answer. The
first question of a session blocks; after that they arrive in well under a second.
Each parallel prefetch is pinned to a different area within the section — without
that, five workers handed the same prompt come back with five variants of the same
textbook question — and near-duplicates are dropped before entering the buffer.

### Model choice matters a lot here

The default is `nvidia/nemotron-3-super-120b-a12b`, picked by measurement rather than
by size. On the free tier:

| Model | Result |
|---|---|
| `meta/llama-3.1-70b-instruct` | 65s per question, then repeated timeouts; produced a question whose correct answer wasn't among its own options |
| `meta/llama-3.1-8b-instruct` | Fast (~2s) but self-contradictory arithmetic and malformed JSON |
| `nvidia/nemotron-3-super-120b-a12b` | ~10-25s, correct answers, valid JSON |

Reasoning models spend tokens *thinking* before emitting `content`, and that counts
against `max_tokens` — set it too low and the reply comes back empty. That's why
`max_tokens` is 2400 rather than the few hundred the answer itself needs.

NVIDIA retires model ids periodically. If generation starts failing with a 404:

```bash
python aptitude.py --list-models          # what your key can actually call
python aptitude.py --try "Logical Reasoning"   # generate one and print it
```

Then set `NVIDIA_MODEL` to a live id. To check the parsing/validation logic
without spending an API call: `python aptitude.py --selfcheck`.

> Aptitude answers come from the model, and there's no oracle to verify them the
> way `safe_execute()` verifies SQL. Shape errors (wrong option count, duplicate
> options, out-of-range answer index) are rejected automatically, but a confidently
> wrong answer can still get through — the worked explanation is shown so you can
> catch it.

## Accounts & history storage

User accounts, scores, and attempt history are stored through a backend chosen
automatically at startup based on the `DATABASE_URL` environment variable:

- **`DATABASE_URL` set** → **Postgres** (e.g. [Neon](https://neon.tech)). Data is
  durable and survives restarts/redeploys. Passwords are stored as salted
  PBKDF2-SHA256 hashes — never plaintext.
- **`DATABASE_URL` unset** → local **SQLite** (`drill_history.db`). Great for local
  dev, but on Streamlit Cloud this file is **ephemeral** and resets on every
  redeploy — use Postgres for permanent accounts.

The schema is created automatically on first connect, so no manual migration step
is needed. `requirements.txt` already includes `psycopg2-binary` for the Postgres path.

## Deploying to Streamlit Community Cloud

1. Push this repo to GitHub.
2. At [share.streamlit.io](https://share.streamlit.io): **Create app** → select the
   repo, branch `main`, main file `app.py`.
3. Under **Advanced settings → Secrets**, add (see
   `.streamlit/secrets.toml.example` for the template):

   ```toml
   DATABASE_URL = "postgresql://user:pass@host/dbname?sslmode=require"
   NVIDIA_API_KEY = "nvapi-..."       # required for the Aptitude tab
   ANTHROPIC_API_KEY = "sk-ant-..."   # optional, for AI feedback
   ```

4. Deploy. The app promotes `DATABASE_URL` from Streamlit secrets into the
   environment before storage initializes, so persistence works out of the box.

> Never commit a real `.streamlit/secrets.toml` or `.env` — both are gitignored.

## Rebuilding / expanding the question bank

The bank is static. To regenerate or add more questions (requires an API key):

```bash
python build_bank.py --per-combo 2   # questions per dataset × topic × difficulty
```

Each generated question is validated (its reference query must run and return rows)
before being saved, so the bank never contains a broken question.

## Features

- **Dark UI** (Nocturne palette) — flat surfaces, line-art iconography, Inter + JetBrains Mono
- **Mechanical keyboard typing sound** (synthesized Topre "thock", toggleable with a volume control)
- **358-question bank** grounded in real schemas — only valid columns used
- **8 SQL topics**: single-table aggregation, GROUP BY + HAVING, CTEs, window
  functions (ROW_NUMBER / RANK / DENSE_RANK), LAG / LEAD, running totals / rolling
  aggregates, multi-table JOINs, correlated subqueries
- **3 difficulty levels**: easy, medium, hard
- **Result-set grading**: correct answers with different SQL still pass
- **Safety**: only SELECT/WITH allowed; mutations rejected
- **Pressure mode**: configurable countdown timer
- **Aptitude tab**: live-generated quant / logical / data-interpretation / verbal
  MCQs via NVIDIA NIM, prefetched 5 deep so questions arrive instantly
- **User sign-in**: per-user progress tracking — pass rate, average time,
  daily stats, streaks, and weakest-topic targeting

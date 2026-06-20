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

- **Dark UI** (Tokyo Night palette) with ambient cursor glow + gradient hover effects
- **Mechanical keyboard typing sound** (synthesized Topre "thock", toggleable with a volume control)
- **358-question bank** grounded in real schemas — only valid columns used
- **8 SQL topics**: single-table aggregation, GROUP BY + HAVING, CTEs, window
  functions (ROW_NUMBER / RANK / DENSE_RANK), LAG / LEAD, running totals / rolling
  aggregates, multi-table JOINs, correlated subqueries
- **3 difficulty levels**: easy, medium, hard
- **Result-set grading**: correct answers with different SQL still pass
- **Safety**: only SELECT/WITH allowed; mutations rejected
- **Pressure mode**: configurable countdown timer
- **User sign-in**: per-user progress tracking — pass rate, average time,
  daily stats, streaks, and weakest-topic targeting

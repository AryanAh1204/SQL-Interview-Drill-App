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

## Rebuilding / expanding the question bank

The bank is static. To regenerate or add more questions (requires an API key):

```bash
python build_bank.py --per-combo 2   # questions per dataset × topic × difficulty
```

Each generated question is validated (its reference query must run and return rows)
before being saved, so the bank never contains a broken question.

## Features

- **Dark UI** (Tokyo Night palette) with ambient cursor glow + gradient hover effects
- **143-question bank** grounded in real schemas — only valid columns used
- **8 SQL topics**: aggregation, GROUP BY+HAVING, CTEs, window functions, LAG/LEAD, running totals, JOINs, correlated subqueries
- **Result-set grading**: correct answers with different SQL still pass
- **Safety**: only SELECT/WITH allowed; mutations rejected
- **Pressure mode**: configurable countdown timer
- **User sign-in**: per-user progress tracking (pass rate, median time, weakest-topic targeting)

> Note: on Streamlit Cloud the SQLite history/login DB resets on each redeploy. For
> permanent accounts, wire in an external database.

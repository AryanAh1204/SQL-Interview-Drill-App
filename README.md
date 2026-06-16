# SQL Drill ⚡

A dark, interactive SQL interview prep app. AI-generated questions across real industry datasets, graded by result-set equivalence — never by matching your SQL text.

## Setup

```bash
cd sql-drill
pip install -r requirements.txt
cp .env.example .env
# Edit .env and add your ANTHROPIC_API_KEY
streamlit run app.py
```

On first run the app downloads three industry datasets (~5 MB total) into `data/`:
- **Northwind** — B2B distribution (orders, customers, products)
- **Chinook** — Digital music store (tracks, invoices, customers)
- **World** — Demographics / government (countries, cities, languages)

## Features

- **Dark UI** (Tokyo Night palette) with cursor-glow and hover effects
- **AI questions** grounded in real schema — only valid columns used
- **8 SQL topics**: aggregation, GROUP BY+HAVING, CTEs, window functions, LAG/LEAD, running totals, JOINs, correlated subqueries
- **Result-set grading**: correct answers with different SQL still pass
- **Safety**: only SELECT/WITH allowed; mutations rejected
- **Pressure mode**: configurable countdown timer
- **Style feedback** from Claude after each pass (efficiency / idiom review)
- **Progress tracking**: SQLite log, per-topic pass rate + median time, weakest-topic targeting

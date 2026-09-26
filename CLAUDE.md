# English-to-SQL Generator

Natural-language-to-SQL system: user asks a question in English, the system generates
a SQL query against a fixed, synthetic dataset, executes it, and reports whether the
query is *correct* using explicit evaluation metrics. Metrics are surfaced in a
dashboard alongside the query itself, not just logged to a file.

## Scope boundary (read first)

The system only ever answers questions that can be resolved against the schema in
`data/schema.sql`. It must never invent tables/columns, silently query a different
dataset, or answer general knowledge / non-SQL questions.

- If a question references an entity or attribute not present in the schema, the
  generator returns a **refusal**, not a best-guess query. Example refusal payload:
  `{"status": "out_of_scope", "reason": "no column for 'employee salary' in schema"}`.
- The system prompt sent to the model must include the full schema (DDL + a short
  description of each table) and an explicit instruction: "If the question cannot be
  answered using only these tables/columns, respond with OUT_OF_SCOPE instead of SQL."
- "Out-of-scope rejection rate" (see Evaluation) exists specifically to catch
  regressions here — don't let it silently drop.

## Synthetic dataset

Tables live in `data/schema.sql` (DDL) and are seeded by `data/seed.py` into a local
SQLite file at `data/synthetic.db`. Keep the domain small and closed so "context" is
easy to reason about — this is a retail/e-commerce toy dataset:

```
customers(customer_id PK, name, email, city, signup_date)
products(product_id PK, name, category, unit_price)
orders(order_id PK, customer_id FK->customers, order_date, status)
order_items(order_item_id PK, order_id FK->orders, product_id FK->products, quantity)
```

Rules for this dataset:
- Do not add columns/tables ad hoc while implementing a feature. If a task needs data
  the schema doesn't have, either add it to `data/schema.sql` + `data/seed.py` as a
  deliberate schema change (and update this file), or treat the question as
  out-of-scope.
- Seed data should be small (dozens to low hundreds of rows per table) but internally
  consistent (valid FKs, plausible dates/prices) so execution-based metrics are
  meaningful.
- `data/gold_queries.json` holds a labeled eval set: `{question, gold_sql}` pairs
  covering SELECT/WHERE/JOIN/GROUP BY/ORDER BY/aggregation cases. This is the fixture
  the evaluation metrics run against — extend it whenever new query patterns are
  supported, don't hand-wave "it works" without adding a case here.

## Architecture

```
nl2sql/
  generate.py     # prompt construction + call to the model, returns SQL or OUT_OF_SCOPE
  execute.py       # runs SQL against data/synthetic.db, returns rows or an error
  evaluate.py      # computes metrics for one (question, generated_sql) pair vs gold
  metrics.py       # metric definitions/aggregation used by evaluate.py and the dashboard
data/
  schema.sql
  seed.py
  synthetic.db
  gold_queries.json
dashboard/
  app.py           # Streamlit app: query box + results + metrics panel
```

- Generation: use the Claude API (Anthropic SDK) with the schema embedded in the
  system prompt. Keep prompt construction in `generate.py`, not scattered inline.
- Execution: always run generated SQL read-only against `synthetic.db` (SELECT only —
  reject/strip any DDL/DML the model might emit).
- Every generated query, whether correct or not, gets logged with its metrics so the
  dashboard has history to show.

## Evaluation metrics

Defined in `nl2sql/metrics.py`, computed per-query in `evaluate.py`. A query is not
"correct" just because it parses — correctness is decided against these metrics:

- **Execution Accuracy (EX)** — primary metric. Run generated SQL and gold SQL against
  `synthetic.db`; compare result sets (order-insensitive for non-`ORDER BY` queries,
  order-sensitive when the question implies ordering). Pass/fail per query.
- **Exact Match (EM)** — normalized SQL string/AST match against gold (ignore
  whitespace/alias naming/literal quoting differences). Stricter than EX; tracked
  separately since a query can be EX-correct with a different valid formulation.
- **Component F1** — precision/recall over SELECT columns, WHERE predicates, JOIN
  conditions, GROUP BY, ORDER BY, and aggregation functions, compared to gold's parsed
  components. Useful for partial credit when EM/EX both fail.
- **Valid SQL Rate** — fraction of generated queries that execute without a DB error
  (syntax/semantic errors, unknown columns, etc.).
- **Out-of-Scope Rejection Rate** — for questions in `gold_queries.json` intentionally
  marked `expected: OUT_OF_SCOPE`, fraction correctly refused instead of hallucinated.
- **Latency (ms)** — generation time per query, tracked for dashboard trend, not a
  correctness signal.

`evaluate.py` returns one metrics object per query; `metrics.py` also aggregates these
across the full `gold_queries.json` run (accuracy over time, per-pattern breakdown by
query type — single table / join / aggregation / etc.).

## Dashboard requirements

`dashboard/app.py` (Streamlit) must show, not just the final SQL:

1. Input box for an English question + the generated SQL + execution results table.
2. A correctness badge for that query (EX pass/fail against gold if the question
   matches a `gold_queries.json` entry; otherwise mark "ungraded — no gold reference").
3. A metrics panel with the aggregate numbers above (EX, EM, Component F1, Valid SQL
   Rate, Out-of-Scope Rejection Rate, avg latency) and a trend view across the run
   history, not only the latest single-query result.
4. A schema browser panel listing the in-scope tables/columns, so users can see the
   boundary of what's answerable before they ask.
5. A history log of past questions, generated SQL, and their per-query metrics.

Use the `dataviz` skill when building any chart/trend/stat-tile in this dashboard.

## Conventions

- Python 3.11+, SQLite for the synthetic store (no external DB dependency).
- Keep `nl2sql/` fully decoupled from `dashboard/` — the dashboard imports and calls
  the pipeline, it doesn't reimplement generation/evaluation logic.
- Every new supported question *pattern* (e.g. first multi-join question, first
  window function) gets a corresponding entry in `data/gold_queries.json` before
  being called "supported."

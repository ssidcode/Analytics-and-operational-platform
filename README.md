# HackTU Analytics & Operations Platform

A data platform for managing and analyzing a college hackathon — built after
organizing HackTU 5.0, to solve a real problem: organizers had no easy way
to see registration trends, judge scoring consistency, or track-level
submission rates in one place.

## What's here

| File | Purpose |
|---|---|
| `schema.sql` | PostgreSQL DDL — normalized OLTP schema, indexes, stored procedures, and an OLAP star schema for analytics |
| `generate_data.py` | Generates realistic synthetic hackathon data (participants, teams, scores, submissions), including intentional messiness (duplicate emails, inconsistent casing) to simulate a real Google Forms export |
| `etl_pipeline.py` | Extract → Transform → Load pipeline: reads raw CSVs, deduplicates and cleans data, aggregates it into a fact table, loads everything into a database, and runs data-quality validation checks |
| `raw_data/` | Generated "source" CSVs (simulating Forms/spreadsheet/GitHub exports) |
| `hacktu.db` | Output SQLite database after running the ETL (portable demo target — `schema.sql` is written for Postgres and the ETL can be pointed at it with a driver swap) |

## Architecture

```
raw_data/*.csv  (messy, source-of-truth exports)
        │
        ▼
   EXTRACT  (pandas read_csv)
        │
        ▼
   TRANSFORM (dedupe emails, standardize college names,
              compute team size / submission lag / rank,
              build star schema fact table)
        │
        ▼
   LOAD  (writes clean OLTP + OLAP tables to DB)
        │
        ▼
   VALIDATE (data-quality assertions: no dupes, no orphans,
             scores within valid range)
```

## Running it

```bash
pip install faker pandas
python generate_data.py     # creates raw_data/*.csv
python etl_pipeline.py       # cleans + loads into hacktu.db, runs validations
```

To use the full Postgres schema (with stored procedures) instead of the
SQLite demo target:
```bash
psql -U postgres -d hacktu -f schema.sql
```

## Skills demonstrated

- **SQL & database design** — normalized OLTP schema, foreign keys, check
  constraints, indexes (`idx_scores_team_judge`, `idx_submissions_status`)
  added specifically to speed up the most common organizer queries.
- **Stored procedures** — `sp_assign_track` (capacity-aware team assignment),
  `sp_calculate_final_score` (multi-judge aggregation), `sp_flag_incomplete_teams`.
- **ETL / data modeling** — OLTP → OLAP star schema (`fact_team_performance`
  with `dim_track`, `dim_college`, `dim_sponsor`), with a real transform
  layer (dedup, cleaning, derived metrics).
- **Data quality / SDLC practices** — validation checks that run on every
  load (no duplicate emails, no orphaned foreign keys, scores in range).
- **BI-ready output** — `hacktu.db` / the Postgres warehouse is directly
  connectable to Power BI or Tableau for dashboards on participation,
  judging consistency, and track engagement.

## Text-to-SQL agent (`text_to_sql_agent.py`)

An agentic layer on top of the warehouse: ask a question in plain English,
and it generates SQL, runs it, and answers in natural language.

```bash
pip install anthropic
export ANTHROPIC_API_KEY=sk-...

python text_to_sql_agent.py "Which track has the lowest submission rate?"

# or interactive mode
python text_to_sql_agent.py
```

**How it works:**
1. Introspects the live DB schema (`PRAGMA table_info`) so the prompt never
   drifts out of sync with the actual tables.
2. Sends the question + schema to Claude, which returns a single SQL query.
3. Runs the query through a safety filter — only `SELECT` statements are
   allowed; anything containing `INSERT/UPDATE/DELETE/DROP/ALTER` or a
   second stacked statement is rejected before it ever touches the database.
4. Executes the query and asks Claude to summarize the result in 2-4 plain
   English sentences.

This part was tested end-to-end except for the live model calls (no API key
in the build sandbox) — schema introspection, the safety filter (6/6 test
cases including SQL injection via stacked statements), and query execution
were all verified directly against `hacktu.db`.

## Next steps
- Connect Power BI/Tableau to the warehouse tables for the three planned
  dashboards (participation overview, judging & performance, sponsor engagement).
- Point `text_to_sql_agent.py` at a real `ANTHROPIC_API_KEY` and try it live.

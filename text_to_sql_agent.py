"""
text_to_sql_agent.py
----------------------
An agentic assistant for hackathon organizers: ask a question in plain
English, and it will:
    1. Look at the database schema
    2. Generate a SQL query using Claude
    3. Validate the query is read-only (safety guardrail)
    4. Execute it against hacktu.db
    5. Summarize the result back in natural language

This is the "Agentic AI" layer referenced in the README — it turns the
warehouse built by etl_pipeline.py into something a non-technical organizer
can query directly, instead of needing to know SQL.

Requires:
    pip install anthropic
    export ANTHROPIC_API_KEY=sk-...

Usage:
    python text_to_sql_agent.py "Which track has the lowest submission rate?"

    # or interactive mode:
    python text_to_sql_agent.py
"""

import sqlite3
import sys
import re
import os

try:
    import anthropic
except ImportError:
    print("Missing dependency. Run: pip install anthropic")
    sys.exit(1)

DB_PATH = "hacktu.db"
MODEL = "claude-sonnet-4-6"

# Only these statement types are ever allowed to execute.
# Anything else (INSERT/UPDATE/DELETE/DROP/ALTER/etc.) is rejected before
# it ever touches the database — the agent can look, but never write.
ALLOWED_SQL_PREFIX = re.compile(r"^\s*SELECT\b", re.IGNORECASE)
FORBIDDEN_KEYWORDS = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|ATTACH|PRAGMA)\b",
    re.IGNORECASE,
)


def get_schema_description(conn):
    """Introspect the live DB so the agent's prompt always matches reality."""
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [row[0] for row in cur.fetchall()]

    schema_lines = []
    for table in tables:
        cur.execute(f"PRAGMA table_info({table})")
        cols = cur.fetchall()
        col_desc = ", ".join(f"{c[1]} {c[2]}" for c in cols)
        schema_lines.append(f"- {table}({col_desc})")

    return "\n".join(schema_lines)


def build_system_prompt(schema_desc):
    return f"""You are a SQL generation assistant for a hackathon analytics database (SQLite).

Database schema:
{schema_desc}

Notes:
- fact_team_performance is a precomputed analytics table: use it for questions
  about scores, rankings, submission status, team size, or mentorship counts
  per team/track/college, rather than joining raw tables yourself.
- submissions.status is one of: 'submitted', 'not_submitted', 'disqualified'.
- Respond with ONLY a single SQL SELECT query. No explanation, no markdown
  fences, no semicolon-separated multiple statements.
- Never write INSERT/UPDATE/DELETE/DROP/ALTER — you only ever read data.
- If the question can't be answered from this schema, respond with:
  NO_QUERY: <short reason>
"""


def generate_sql(client, question, schema_desc):
    system_prompt = build_system_prompt(schema_desc)
    response = client.messages.create(
        model=MODEL,
        max_tokens=300,
        system=system_prompt,
        messages=[{"role": "user", "content": question}],
    )
    text = "".join(block.text for block in response.content if block.type == "text").strip()
    # strip accidental markdown fences just in case
    text = re.sub(r"^```sql|```$", "", text, flags=re.IGNORECASE).strip()
    return text


def is_safe_query(sql):
    if not ALLOWED_SQL_PREFIX.match(sql):
        return False
    if FORBIDDEN_KEYWORDS.search(sql):
        return False
    if ";" in sql.strip().rstrip(";"):  # no stacked statements
        return False
    return True


def run_query(conn, sql):
    cur = conn.cursor()
    cur.execute(sql)
    columns = [desc[0] for desc in cur.description]
    rows = cur.fetchall()
    return columns, rows


def summarize_result(client, question, sql, columns, rows):
    # cap rows sent back to the model to keep the summary prompt small
    preview_rows = rows[:20]
    result_text = ", ".join(columns) + "\n" + "\n".join(
        ", ".join(str(v) for v in row) for row in preview_rows
    )
    if not rows:
        result_text = "(no rows returned)"

    prompt = f"""The user asked: "{question}"

This SQL query was run:
{sql}

Result ({len(rows)} row(s), showing up to 20):
{result_text}

Give a short, plain-English answer (2-4 sentences) based only on this result.
Do not mention SQL or the query itself in your answer."""

    response = client.messages.create(
        model=MODEL,
        max_tokens=250,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(block.text for block in response.content if block.type == "text").strip()


def ask(client, conn, schema_desc, question):
    print(f"\nQ: {question}")

    sql = generate_sql(client, question, schema_desc)

    if sql.startswith("NO_QUERY"):
        print(f"A: I can't answer that from this database. ({sql.replace('NO_QUERY:', '').strip()})")
        return

    if not is_safe_query(sql):
        print(f"A: Generated query failed the safety check and was blocked:\n    {sql}")
        return

    try:
        columns, rows = run_query(conn, sql)
    except sqlite3.Error as e:
        print(f"A: The query failed to run ({e}). SQL was:\n    {sql}")
        return

    answer = summarize_result(client, question, sql, columns, rows)
    print(f"A: {answer}")
    print(f"   [query used: {sql}]")


def main():
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("Set ANTHROPIC_API_KEY before running this script.")
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    schema_desc = get_schema_description(conn)
    client = anthropic.Anthropic()

    if len(sys.argv) > 1:
        question = " ".join(sys.argv[1:])
        ask(client, conn, schema_desc, question)
    else:
        print("HackTU Analytics Assistant — ask a question, or type 'exit' to quit.")
        print("Example: Which track has the lowest submission rate?\n")
        while True:
            question = input("> ").strip()
            if question.lower() in ("exit", "quit"):
                break
            if question:
                ask(client, conn, schema_desc, question)

    conn.close()


if __name__ == "__main__":
    main()

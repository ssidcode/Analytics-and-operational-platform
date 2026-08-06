"""
etl_pipeline.py
-----------------
Extract -> Transform -> Load pipeline for the HackTU Analytics Platform.

EXTRACT:  reads raw CSVs from ./raw_data/ (simulating exports from
          Google Forms, a judge scoring sheet, and a GitHub submission log)
TRANSFORM: cleans participant data (dedupes, trims whitespace, standardizes
          college names), computes derived fields (team size, submission
          lag), and reshapes into a star schema
LOAD:     writes clean data into hacktu.db (SQLite, used here for a
          zero-setup demo -- schema.sql targets Postgres and can be used
          identically in production by swapping the DB driver)

Usage:
    python etl_pipeline.py
"""

import sqlite3
import pandas as pd
from datetime import datetime
import os

RAW_DIR = "raw_data"
DB_PATH = "hacktu.db"


def get_connection():
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)  # fresh load each run, mirrors a nightly ETL job
    return sqlite3.connect(DB_PATH)


# ------------------------------------------------------------
# EXTRACT
# ------------------------------------------------------------

def extract():
    print("[EXTRACT] Reading raw source files...")
    data = {
        "sponsors": pd.read_csv(f"{RAW_DIR}/sponsors.csv"),
        "tracks": pd.read_csv(f"{RAW_DIR}/tracks.csv"),
        "participants_raw": pd.read_csv(f"{RAW_DIR}/participants_raw.csv"),
        "mentors": pd.read_csv(f"{RAW_DIR}/mentors.csv"),
        "judges": pd.read_csv(f"{RAW_DIR}/judges.csv"),
        "teams": pd.read_csv(f"{RAW_DIR}/teams.csv"),
        "team_members": pd.read_csv(f"{RAW_DIR}/team_members.csv"),
        "mentorship_sessions": pd.read_csv(f"{RAW_DIR}/mentorship_sessions.csv"),
        "submissions": pd.read_csv(f"{RAW_DIR}/submissions.csv"),
        "scores": pd.read_csv(f"{RAW_DIR}/scores.csv"),
    }
    for name, df in data.items():
        print(f"    {name}: {len(df)} rows")
    return data


# ------------------------------------------------------------
# TRANSFORM
# ------------------------------------------------------------

def clean_participants(df):
    """Business rules: dedupe by email, trim/standardize college names."""
    before = len(df)
    df["college"] = df["college"].str.strip().str.title()
    df["email"] = df["email"].str.strip().str.lower()
    df = df.drop_duplicates(subset="email", keep="first")
    df["registered_at"] = pd.to_datetime(df["registered_at"])
    after = len(df)
    print(f"[TRANSFORM] participants: {before} -> {after} rows after dedupe/cleaning "
          f"({before - after} duplicates removed)")
    return df


def build_fact_team_performance(teams, team_members, submissions, scores, mentorship_sessions):
    """Aggregate multiple OLTP tables into one analytics fact table."""

    # team size
    team_size = team_members.groupby("team_id").size().rename("team_size")

    # avg score per team
    avg_score = scores.groupby("team_id")["score"].mean().round(2).rename("avg_score")

    # mentorship session count per team
    mentorship_count = (
        mentorship_sessions.groupby("team_id").size().rename("mentorship_sessions_count")
    )

    # submission lag: minutes between team creation and submission
    subs = submissions.copy()
    subs["submitted_at"] = pd.to_datetime(subs["submitted_at"], errors="coerce")
    teams_dt = teams.copy()
    teams_dt["created_at"] = pd.to_datetime(teams_dt["created_at"])

    merged = teams_dt.merge(subs, on="team_id", how="left")
    merged["submission_lag_mins"] = (
        (merged["submitted_at"] - merged["created_at"]).dt.total_seconds() / 60
    ).round(1)

    fact = merged[["team_id", "track_id", "status", "submission_lag_mins"]].rename(
        columns={"status": "submission_status"}
    )
    fact = fact.set_index("team_id")
    fact = fact.join(team_size).join(avg_score).join(mentorship_count)
    fact["team_size"] = fact["team_size"].fillna(0).astype(int)
    fact["mentorship_sessions_count"] = fact["mentorship_sessions_count"].fillna(0).astype(int)
    fact["avg_score"] = fact["avg_score"].fillna(0)

    # rank within track by avg_score
    fact["rank_in_track"] = (
        fact.groupby("track_id")["avg_score"].rank(ascending=False, method="min").astype(int)
    )

    fact = fact.reset_index()
    print(f"[TRANSFORM] fact_team_performance: {len(fact)} rows built")
    return fact


def transform(data):
    print("[TRANSFORM] Cleaning and reshaping data...")
    participants_clean = clean_participants(data["participants_raw"])

    dim_college = (
        participants_clean[["college"]]
        .drop_duplicates()
        .reset_index(drop=True)
    )
    dim_college.insert(0, "college_id", range(1, len(dim_college) + 1))

    dim_track = data["tracks"][["track_id", "name", "sponsor_id"]].rename(
        columns={"name": "track_name"}
    )
    dim_sponsor = data["sponsors"][["sponsor_id", "name", "prize_pool"]].rename(
        columns={"name": "sponsor_name"}
    )

    fact = build_fact_team_performance(
        data["teams"], data["team_members"], data["submissions"],
        data["scores"], data["mentorship_sessions"]
    )
    # attach college_id to fact via team lead's college
    leads = data["team_members"][data["team_members"]["role"] == "lead"]
    leads = leads.merge(participants_clean[["participant_id", "college"]], on="participant_id", how="left")
    leads = leads.merge(dim_college, on="college", how="left")
    fact = fact.merge(leads[["team_id", "college_id"]], on="team_id", how="left")

    return {
        "participants_clean": participants_clean,
        "dim_college": dim_college,
        "dim_track": dim_track,
        "dim_sponsor": dim_sponsor,
        "fact_team_performance": fact,
        # pass through OLTP tables unchanged
        "teams": data["teams"],
        "team_members": data["team_members"],
        "mentors": data["mentors"],
        "judges": data["judges"],
        "mentorship_sessions": data["mentorship_sessions"],
        "submissions": data["submissions"],
        "scores": data["scores"],
    }


# ------------------------------------------------------------
# LOAD
# ------------------------------------------------------------

def load(clean_data):
    print("[LOAD] Writing to hacktu.db (SQLite)...")
    conn = get_connection()

    table_map = {
        "participants": clean_data["participants_clean"],
        "teams": clean_data["teams"],
        "team_members": clean_data["team_members"],
        "mentors": clean_data["mentors"],
        "judges": clean_data["judges"],
        "mentorship_sessions": clean_data["mentorship_sessions"],
        "submissions": clean_data["submissions"],
        "scores": clean_data["scores"],
        "dim_college": clean_data["dim_college"],
        "dim_track": clean_data["dim_track"],
        "dim_sponsor": clean_data["dim_sponsor"],
        "fact_team_performance": clean_data["fact_team_performance"],
    }

    for name, df in table_map.items():
        df.to_sql(name, conn, if_exists="replace", index=False)
        print(f"    loaded {name}: {len(df)} rows")

    conn.commit()
    conn.close()
    print("[LOAD] Done. Database ready at ./hacktu.db")


# ------------------------------------------------------------
# Simple validation tests (mirrors what a pytest suite would check)
# ------------------------------------------------------------

def run_basic_validations(clean_data):
    print("\n[VALIDATE] Running basic data quality checks...")
    p = clean_data["participants_clean"]
    assert p["email"].is_unique, "FAIL: duplicate emails still present"
    print("    PASS: no duplicate participant emails")

    fact = clean_data["fact_team_performance"]
    assert (fact["avg_score"] >= 0).all() and (fact["avg_score"] <= 10).all(), \
        "FAIL: avg_score out of [0,10] range"
    print("    PASS: avg_score within valid range")

    tm = clean_data["team_members"]
    orphaned = tm[~tm["team_id"].isin(clean_data["teams"]["team_id"])]
    assert orphaned.empty, "FAIL: orphaned team_members rows found"
    print("    PASS: no orphaned team_members rows")

    print("[VALIDATE] All checks passed.\n")


if __name__ == "__main__":
    raw = extract()
    clean = transform(raw)
    run_basic_validations(clean)
    load(clean)

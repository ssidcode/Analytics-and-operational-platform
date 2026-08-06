"""
generate_data.py
-----------------
Generates synthetic HackTU hackathon data (participants, teams, tracks,
sponsors, mentors, judges, submissions, scores) and writes it out as CSV
files that mimic what you'd get from real sources:
    - Google Forms export (participants)
    - Manual sponsor/track setup sheet
    - Judge scoring spreadsheet
    - GitHub submission log

These CSVs are the "raw source" layer that etl_pipeline.py will ingest,
clean, and load into the OLTP + OLAP schema.

Usage:
    pip install faker --break-system-packages
    python generate_data.py
"""

import csv
import random
from datetime import datetime, timedelta
from faker import Faker

fake = Faker("en_IN")
random.seed(42)
Faker.seed(42)

OUT_DIR = "raw_data"
import os
os.makedirs(OUT_DIR, exist_ok=True)

EVENT_START = datetime(2026, 3, 14, 9, 0)   # hackathon start
EVENT_END   = datetime(2026, 3, 15, 18, 0)  # 33-hour event, submissions close 6pm day 2

COLLEGES = [
    "Thapar Institute of Engineering and Technology", "IIT Ropar", "NIT Jalandhar",
    "PEC Chandigarh", "DAV College Chandigarh", "Chitkara University",
    "LPU Jalandhar", "UIET Panjab University", "IIIT Una", "GNDU Amritsar",
    "PU SSG Regional Centre", "Guru Nanak Dev Engineering College"
]

SKILLS_POOL = ["python", "react", "ml", "nodejs", "flutter", "cpp", "ros",
               "computer-vision", "blockchain", "figma", "aws", "sql", "arduino"]

SPONSORS = [
    ("TechCorp India", 150000),
    ("Nimbus Analytics", 200000),
    ("CloudNine Systems",100000),
    ("DataWave Analytics", 120000),
]

TRACKS = [
    ("AI/ML Innovation", "TechCorp India"),
    ("FinTech & Data Analytics", "Nimbus Analytics"),
    ("Cloud & DevOps", "CloudNine Systems"),
    ("Open Innovation", "DataWave Analytics"),
    ("Robotics & IoT", "TechCorp India"),
]

STATUS_WEIGHTS = ["submitted"] * 78 + ["not_submitted"] * 15 + ["disqualified"] * 7


def gen_sponsors():
    rows = []
    for i, (name, prize) in enumerate(SPONSORS, start=1):
        rows.append({
            "sponsor_id": i,
            "name": name,
            "prize_pool": prize,
            "contact_email": f"partnerships@{name.lower().replace(' ', '')}.com"
        })
    with open(f"{OUT_DIR}/sponsors.csv", "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    return rows


def gen_tracks(sponsors):
    sponsor_lookup = {s["name"]: s["sponsor_id"] for s in sponsors}
    rows = []
    for i, (name, sponsor_name) in enumerate(TRACKS, start=1):
        rows.append({
            "track_id": i,
            "name": name,
            "description": f"Build solutions for the {name} track.",
            "sponsor_id": sponsor_lookup[sponsor_name],
            "max_teams": random.choice([15, 20, 25])
        })
    with open(f"{OUT_DIR}/tracks.csv", "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    return rows


def gen_participants(n=520):
    rows = []
    for i in range(1, n + 1):
        name = fake.name()
        # intentionally inject some messy data for the ETL to clean:
        email = f"{name.lower().replace(' ', '.')}{random.randint(1,999)}@gmail.com"
        college = random.choice(COLLEGES)
        if random.random() < 0.05:  # 5% messy college names (extra whitespace/case)
            college = college.upper() + "  "
        skills = ",".join(random.sample(SKILLS_POOL, k=random.randint(2, 5)))
        reg_time = fake.date_time_between(start_date="-30d", end_date="-1d")
        rows.append({
            "participant_id": i,
            "name": name,
            "email": email,
            "college": college,
            "year_of_study": random.choice([1, 2, 3, 4]),
            "skills": skills,
            "registered_at": reg_time.isoformat()
        })
    # inject a handful of duplicate emails (common real-world registration issue)
    for _ in range(8):
        dup = random.choice(rows).copy()
        dup["participant_id"] = n + _ + 1
        rows.append(dup)

    with open(f"{OUT_DIR}/participants_raw.csv", "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    return rows


def gen_mentors(n=15):
    rows = []
    for i in range(1, n + 1):
        rows.append({
            "mentor_id": i,
            "name": fake.name(),
            "expertise": random.choice(SKILLS_POOL)
        })
    with open(f"{OUT_DIR}/mentors.csv", "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    return rows


def gen_judges(n=10):
    rows = []
    for i in range(1, n + 1):
        rows.append({
            "judge_id": i,
            "name": fake.name(),
            "expertise": random.choice(SKILLS_POOL)
        })
    with open(f"{OUT_DIR}/judges.csv", "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    return rows


def gen_teams_and_members(participants, tracks, n_teams=110):
    teams = []
    members = []
    used_participants = set()
    pid_pool = [p["participant_id"] for p in participants]

    for i in range(1, n_teams + 1):
        track = random.choice(tracks)
        created = fake.date_time_between(start_date=EVENT_START - timedelta(days=2),
                                          end_date=EVENT_START)
        teams.append({
            "team_id": i,
            "team_name": f"{fake.color_name()}{fake.word().capitalize()}",
            "track_id": track["track_id"],
            "created_at": created.isoformat()
        })

        team_size = random.choice([1, 2, 3, 3, 4, 4])  # skew toward 3-4
        available = [p for p in pid_pool if p not in used_participants]
        if len(available) < team_size:
            team_size = max(1, len(available))
        chosen = random.sample(available, k=team_size) if available else []
        for j, pid in enumerate(chosen):
            used_participants.add(pid)
            members.append({
                "team_id": i,
                "participant_id": pid,
                "role": "lead" if j == 0 else "member"
            })

    with open(f"{OUT_DIR}/teams.csv", "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=teams[0].keys())
        writer.writeheader()
        writer.writerows(teams)

    with open(f"{OUT_DIR}/team_members.csv", "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=members[0].keys())
        writer.writeheader()
        writer.writerows(members)

    return teams, members


def gen_mentorship_sessions(teams, mentors, avg_per_team=1.5):
    rows = []
    sid = 1
    for t in teams:
        n_sessions = max(0, round(random.gauss(avg_per_team, 1)))
        for _ in range(n_sessions):
            session_time = fake.date_time_between(start_date=EVENT_START, end_date=EVENT_END)
            rows.append({
                "session_id": sid,
                "team_id": t["team_id"],
                "mentor_id": random.choice(mentors)["mentor_id"],
                "session_time": session_time.isoformat(),
                "notes": fake.sentence(nb_words=8)
            })
            sid += 1
    with open(f"{OUT_DIR}/mentorship_sessions.csv", "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    return rows


def gen_submissions(teams):
    rows = []
    for t in teams:
        status = random.choice(STATUS_WEIGHTS)
        if status == "submitted":
            submitted_at = fake.date_time_between(start_date=EVENT_START + timedelta(hours=20),
                                                    end_date=EVENT_END)
            link = f"https://github.com/{fake.user_name()}/{t['team_name'].lower()}"
        elif status == "not_submitted":
            submitted_at = ""
            link = ""
        else:  # disqualified
            submitted_at = fake.date_time_between(start_date=EVENT_START + timedelta(hours=20),
                                                    end_date=EVENT_END).isoformat()
            link = f"https://github.com/{fake.user_name()}/{t['team_name'].lower()}"

        rows.append({
            "team_id": t["team_id"],
            "submitted_at": submitted_at if isinstance(submitted_at, str) else submitted_at.isoformat(),
            "github_link": link,
            "status": status
        })
    with open(f"{OUT_DIR}/submissions.csv", "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    return rows


def gen_scores(teams, judges, submissions):
    rows = []
    submitted_team_ids = {s["team_id"] for s in submissions if s["status"] == "submitted"}
    criteria_list = ["innovation", "technical", "presentation", "impact"]

    for t in teams:
        if t["team_id"] not in submitted_team_ids:
            continue
        n_judges = random.choice([2, 3])
        assigned_judges = random.sample(judges, k=n_judges)
        for j in assigned_judges:
            # introduce a "harsh judge" and "lenient judge" pattern for realism
            bias = random.choice([-1.5, 0, 0, 0, 1.0])
            for criteria in criteria_list:
                base_score = round(random.gauss(6.8 + bias, 1.2), 2)
                base_score = max(0, min(10, base_score))
                rows.append({
                    "team_id": t["team_id"],
                    "judge_id": j["judge_id"],
                    "round": 1,
                    "criteria": criteria,
                    "score": base_score
                })
    with open(f"{OUT_DIR}/scores.csv", "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    return rows


if __name__ == "__main__":
    print("Generating synthetic HackTU dataset...")
    sponsors = gen_sponsors()
    tracks = gen_tracks(sponsors)
    participants = gen_participants()
    mentors = gen_mentors()
    judges = gen_judges()
    teams, members = gen_teams_and_members(participants, tracks)
    gen_mentorship_sessions(teams, mentors)
    submissions = gen_submissions(teams)
    gen_scores(teams, judges, submissions)

    print(f"Done. Files written to ./{OUT_DIR}/")
    print(f"  Participants (raw, incl. dupes/messy data): {len(participants)}")
    print(f"  Teams: {len(teams)}")
    print(f"  Team members: {len(members)}")
    print("Next: run etl_pipeline.py to clean + load into the warehouse.")

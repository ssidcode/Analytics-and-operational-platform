-- ============================================================
-- HackTU Analytics & Operations Platform
-- OLTP Schema (Normalized)
-- ============================================================

DROP TABLE IF EXISTS scores CASCADE;
DROP TABLE IF EXISTS submissions CASCADE;
DROP TABLE IF EXISTS mentorship_sessions CASCADE;
DROP TABLE IF EXISTS team_members CASCADE;
DROP TABLE IF EXISTS teams CASCADE;
DROP TABLE IF EXISTS judges CASCADE;
DROP TABLE IF EXISTS mentors CASCADE;
DROP TABLE IF EXISTS tracks CASCADE;
DROP TABLE IF EXISTS sponsors CASCADE;
DROP TABLE IF EXISTS participants CASCADE;

-- ------------------------------------------------------------
-- Core reference tables
-- ------------------------------------------------------------

CREATE TABLE sponsors (
    sponsor_id      SERIAL PRIMARY KEY,
    name             VARCHAR(120) NOT NULL,
    prize_pool       NUMERIC(10,2) DEFAULT 0,
    contact_email    VARCHAR(150)
);

CREATE TABLE tracks (
    track_id        SERIAL PRIMARY KEY,
    name             VARCHAR(120) NOT NULL,
    description      TEXT,
    sponsor_id       INT REFERENCES sponsors(sponsor_id),
    max_teams        INT DEFAULT 20
);

CREATE TABLE participants (
    participant_id  SERIAL PRIMARY KEY,
    name             VARCHAR(120) NOT NULL,
    email            VARCHAR(150) UNIQUE NOT NULL,
    college          VARCHAR(150),
    year_of_study    INT,
    skills           TEXT,           -- comma separated tags, e.g. 'python,ml,react'
    registered_at    TIMESTAMP DEFAULT NOW()
);

CREATE TABLE mentors (
    mentor_id       SERIAL PRIMARY KEY,
    name             VARCHAR(120) NOT NULL,
    expertise        VARCHAR(150)
);

CREATE TABLE judges (
    judge_id        SERIAL PRIMARY KEY,
    name             VARCHAR(120) NOT NULL,
    expertise        VARCHAR(150)
);

-- ------------------------------------------------------------
-- Team formation
-- ------------------------------------------------------------

CREATE TABLE teams (
    team_id         SERIAL PRIMARY KEY,
    team_name        VARCHAR(150) NOT NULL,
    track_id         INT REFERENCES tracks(track_id),
    created_at       TIMESTAMP DEFAULT NOW()
);

CREATE TABLE team_members (
    team_id          INT REFERENCES teams(team_id) ON DELETE CASCADE,
    participant_id   INT REFERENCES participants(participant_id) ON DELETE CASCADE,
    role             VARCHAR(50) DEFAULT 'member',   -- 'lead' or 'member'
    PRIMARY KEY (team_id, participant_id)
);

-- ------------------------------------------------------------
-- Event activity
-- ------------------------------------------------------------

CREATE TABLE mentorship_sessions (
    session_id       SERIAL PRIMARY KEY,
    team_id          INT REFERENCES teams(team_id) ON DELETE CASCADE,
    mentor_id        INT REFERENCES mentors(mentor_id),
    session_time     TIMESTAMP,
    notes            TEXT
);

CREATE TABLE submissions (
    submission_id    SERIAL PRIMARY KEY,
    team_id          INT REFERENCES teams(team_id) ON DELETE CASCADE,
    submitted_at     TIMESTAMP,
    github_link      VARCHAR(255),
    status           VARCHAR(30) DEFAULT 'not_submitted'  -- not_submitted / submitted / disqualified
);

CREATE TABLE scores (
    score_id         SERIAL PRIMARY KEY,
    team_id          INT REFERENCES teams(team_id) ON DELETE CASCADE,
    judge_id         INT REFERENCES judges(judge_id),
    round            INT DEFAULT 1,
    criteria         VARCHAR(60),      -- 'innovation','technical','presentation','impact'
    score            NUMERIC(4,2) CHECK (score >= 0 AND score <= 10),
    scored_at        TIMESTAMP DEFAULT NOW()
);

-- ============================================================
-- Indexes (deliberately added to demonstrate query optimization)
-- ============================================================

CREATE INDEX idx_scores_team_judge   ON scores(team_id, judge_id);
CREATE INDEX idx_submissions_status  ON submissions(status, submitted_at);
CREATE INDEX idx_participants_college ON participants(college);
CREATE INDEX idx_teams_track          ON teams(track_id);
CREATE INDEX idx_mentorship_team      ON mentorship_sessions(team_id);

-- ============================================================
-- Stored Procedures / Functions
-- ============================================================

-- 1. Assign a team to a track, enforcing capacity limits
CREATE OR REPLACE FUNCTION sp_assign_track(p_team_id INT, p_track_id INT)
RETURNS TEXT AS $$
DECLARE
    current_count INT;
    track_capacity INT;
BEGIN
    SELECT COUNT(*) INTO current_count FROM teams WHERE track_id = p_track_id;
    SELECT max_teams INTO track_capacity FROM tracks WHERE track_id = p_track_id;

    IF current_count >= track_capacity THEN
        RETURN 'REJECTED: Track is at full capacity (' || track_capacity || ' teams)';
    END IF;

    UPDATE teams SET track_id = p_track_id WHERE team_id = p_team_id;
    RETURN 'SUCCESS: Team ' || p_team_id || ' assigned to track ' || p_track_id;
END;
$$ LANGUAGE plpgsql;

-- 2. Calculate a team's final aggregated score (avg across judges & rounds)
CREATE OR REPLACE FUNCTION sp_calculate_final_score(p_team_id INT)
RETURNS NUMERIC AS $$
DECLARE
    final_score NUMERIC;
BEGIN
    SELECT ROUND(AVG(score), 2) INTO final_score
    FROM scores
    WHERE team_id = p_team_id;

    RETURN COALESCE(final_score, 0);
END;
$$ LANGUAGE plpgsql;

-- 3. Flag teams that are under the minimum team size before a cutoff time
CREATE OR REPLACE FUNCTION sp_flag_incomplete_teams(p_min_size INT DEFAULT 2)
RETURNS TABLE(team_id INT, team_name VARCHAR, member_count BIGINT) AS $$
BEGIN
    RETURN QUERY
    SELECT t.team_id, t.team_name, COUNT(tm.participant_id) AS member_count
    FROM teams t
    LEFT JOIN team_members tm ON t.team_id = tm.team_id
    GROUP BY t.team_id, t.team_name
    HAVING COUNT(tm.participant_id) < p_min_size;
END;
$$ LANGUAGE plpgsql;

-- ============================================================
-- OLAP Star Schema (Analytics Warehouse)
-- Populated by the ETL pipeline (etl_pipeline.py)
-- ============================================================

DROP TABLE IF EXISTS fact_team_performance CASCADE;
DROP TABLE IF EXISTS dim_track CASCADE;
DROP TABLE IF EXISTS dim_college CASCADE;
DROP TABLE IF EXISTS dim_time CASCADE;
DROP TABLE IF EXISTS dim_sponsor CASCADE;

CREATE TABLE dim_track (
    track_id        INT PRIMARY KEY,
    track_name       VARCHAR(120),
    sponsor_id       INT
);

CREATE TABLE dim_sponsor (
    sponsor_id      INT PRIMARY KEY,
    sponsor_name     VARCHAR(120),
    prize_pool       NUMERIC(10,2)
);

CREATE TABLE dim_college (
    college_id      SERIAL PRIMARY KEY,
    college_name     VARCHAR(150) UNIQUE
);

CREATE TABLE dim_time (
    date_id         DATE PRIMARY KEY,
    day              INT,
    month            INT,
    year             INT,
    day_name         VARCHAR(15)
);

CREATE TABLE fact_team_performance (
    fact_id             SERIAL PRIMARY KEY,
    team_id             INT,
    track_id            INT REFERENCES dim_track(track_id),
    college_id          INT REFERENCES dim_college(college_id),
    submission_date_id  DATE REFERENCES dim_time(date_id),
    team_size           INT,
    avg_score           NUMERIC(4,2),
    submission_status   VARCHAR(30),
    submission_lag_mins NUMERIC(10,2),   -- minutes between team creation and submission
    mentorship_sessions_count INT,
    rank_in_track       INT
);

CREATE INDEX idx_fact_track  ON fact_team_performance(track_id);
CREATE INDEX idx_fact_college ON fact_team_performance(college_id);

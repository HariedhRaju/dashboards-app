-- Test case generation schema.
--
-- Separate tables so this dashboard is self-contained.
--
-- Usage:
--   psql -U postgres -d dashboards_dev -f testcase_schema.sql
--
-- NOTE: coverage_level is stored per-case (denormalized from the run). The real
-- generate_test_cases() does not currently persist it per case — this assumes a
-- ~1-line pipeline change to thread it through. test_type, title_normalized,
-- schema_ok, and step_count are computed at ingest/seed time (heuristics).

DO $$ BEGIN
    CREATE TYPE tc_coverage AS ENUM ('Essential', 'Standard', 'Comprehensive');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE tc_priority AS ENUM ('Core', 'High', 'Medium', 'Low');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE tc_run_status AS ENUM ('success', 'partial', 'failed');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE tc_test_type AS ENUM ('happy_path', 'negative', 'boundary', 'error_handling');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

CREATE TABLE IF NOT EXISTS tc_projects (
    id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    code VARCHAR(16)
);

CREATE TABLE IF NOT EXISTS tc_users (
    id    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name  TEXT NOT NULL,
    email TEXT
);

-- One row per "upload a GDD and generate" run.
CREATE TABLE IF NOT EXISTS generation_runs (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id            UUID NOT NULL REFERENCES tc_projects(id),
    reported_by           UUID NOT NULL REFERENCES tc_users(id),
    coverage_level        tc_coverage NOT NULL,
    model                 VARCHAR(100),
    features_extracted    INTEGER NOT NULL DEFAULT 0,
    features_prioritized  INTEGER NOT NULL DEFAULT 0,
    test_cases_generated  INTEGER NOT NULL DEFAULT 0,
    parse_failures        INTEGER NOT NULL DEFAULT 0,
    status                tc_run_status NOT NULL DEFAULT 'success',
    duration_ms           INTEGER,
    created_at            TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- One row per generated test case.
CREATE TABLE IF NOT EXISTS test_cases (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id            UUID NOT NULL REFERENCES generation_runs(id) ON DELETE CASCADE,
    test_case_id      VARCHAR(20),
    feature           VARCHAR(200) NOT NULL,
    priority          tc_priority NOT NULL,
    assigned_priority tc_priority,               -- the feature's prioritized tier
    title             TEXT NOT NULL,
    title_normalized  TEXT,                       -- verb-stripped, for dup detection
    preconditions     TEXT,
    steps             JSONB,
    step_count        INTEGER NOT NULL DEFAULT 0,
    expected_result   TEXT,
    test_type         tc_test_type NOT NULL DEFAULT 'happy_path',
    coverage_level    tc_coverage NOT NULL,
    schema_ok         BOOLEAN NOT NULL DEFAULT TRUE,
    created_at        TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- Prioritized-but-untested features live here so "coverage gaps" can be queried.
-- (A feature that was prioritized but generated zero cases.)
CREATE TABLE IF NOT EXISTS tc_feature_priorities (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id        UUID NOT NULL REFERENCES tc_projects(id),
    feature           VARCHAR(200) NOT NULL,
    assigned_priority tc_priority NOT NULL,
    created_at        TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_test_cases_run       ON test_cases (run_id);
CREATE INDEX IF NOT EXISTS idx_test_cases_feature   ON test_cases (feature);
CREATE INDEX IF NOT EXISTS idx_test_cases_priority  ON test_cases (priority);
CREATE INDEX IF NOT EXISTS idx_test_cases_type      ON test_cases (test_type);
CREATE INDEX IF NOT EXISTS idx_test_cases_created   ON test_cases (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_test_cases_normtitle ON test_cases (feature, title_normalized);
CREATE INDEX IF NOT EXISTS idx_runs_created         ON generation_runs (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_runs_project         ON generation_runs (project_id, created_at DESC);

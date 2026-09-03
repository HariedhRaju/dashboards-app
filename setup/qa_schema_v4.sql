-- ══════════════════════════════════════════════════════════════════════════
--  QA Insights — migration: reporter/tester identity + scheduled reports
-- ══════════════════════════════════════════════════════════════════════════
--
-- Two additions:
--
--   reporter    who filed the bug / owns the test case. A real, common column
--               ("Reporter", "Assigned To", "Tester", "QA Owner") this pipeline
--               never captured — every dashboard filter so far has been about
--               WHAT, never WHO.
--
--   qa_schedules / qa_schedule_runs
--               recurring analysis. A schedule names a source and a cadence;
--               a background loop (agent/scheduler.py) wakes, finds schedules
--               due, re-resolves the LATEST snapshot for that source, and
--               calls the same build_report() a manual "Run analysis" does —
--               with a rolling window sized to the cadence (daily = last 24h
--               of bug activity, weekly = last 7 days). Every run is a new
--               row in the existing append-only qa_reports table, so "look
--               back at last Tuesday's report" is just a query away.
--
-- Additive and idempotent; safe to run over an existing database.
--
--   psql -U postgres -d dashboards_dev -f setup/qa_schema_v4.sql

BEGIN;

-- ── who ──────────────────────────────────────────────────────────────────

ALTER TABLE qa_bugs       ADD COLUMN IF NOT EXISTS reporter TEXT;
ALTER TABLE qa_test_cases ADD COLUMN IF NOT EXISTS reporter TEXT;

CREATE INDEX IF NOT EXISTS ix_qa_bugs_reporter ON qa_bugs (snapshot_id, reporter);
CREATE INDEX IF NOT EXISTS ix_qa_tc_reporter   ON qa_test_cases (snapshot_id, reporter);

-- ── scheduled reports ────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS qa_schedules (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    label         TEXT NOT NULL,
    -- Which snapshot family this schedule targets. Re-resolved to the LATEST
    -- snapshot with this source_label at each run — a schedule follows a
    -- source ("the nightly bug export"), not one frozen snapshot, or it would
    -- go stale the moment a fresher file is ingested.
    source_label  TEXT NOT NULL,
    cadence       TEXT NOT NULL CHECK (cadence IN ('daily', 'weekly')),
    -- Local to the server process — see agent/scheduler.py for the caveat
    -- that this only fires while the backend is running.
    run_at_hour   INTEGER NOT NULL DEFAULT 6 CHECK (run_at_hour BETWEEN 0 AND 23),
    run_at_minute INTEGER NOT NULL DEFAULT 0 CHECK (run_at_minute BETWEEN 0 AND 59),
    -- Only meaningful for cadence='weekly'. 0=Monday .. 6=Sunday (Python's
    -- date.weekday()), so the scheduler never has to translate.
    weekday       INTEGER CHECK (weekday BETWEEN 0 AND 6),
    -- How much of the bug timeline each run covers. 'rolling' sizes the
    -- window to the cadence itself (daily -> last 1 day, weekly -> last 7);
    -- 'whole' analyses everything, same as a manual run with no range picked.
    window_mode   TEXT NOT NULL DEFAULT 'rolling' CHECK (window_mode IN ('rolling', 'whole')),
    enabled       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_run_at   TIMESTAMPTZ,
    last_status   TEXT,             -- 'ok' | 'error' | NULL (never run)
    last_error    TEXT,
    next_run_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_qa_schedules_due
    ON qa_schedules (next_run_at) WHERE enabled;

-- Which report a scheduled run produced, kept separately from qa_reports so
-- a schedule's history is a direct join rather than a text match on labels.
CREATE TABLE IF NOT EXISTS qa_schedule_runs (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    schedule_id   UUID NOT NULL REFERENCES qa_schedules(id) ON DELETE CASCADE,
    report_id     UUID REFERENCES qa_reports(id) ON DELETE SET NULL,
    snapshot_id   UUID REFERENCES qa_snapshots(id) ON DELETE SET NULL,
    ran_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    status        TEXT NOT NULL,    -- 'ok' | 'error'
    error         TEXT
);

CREATE INDEX IF NOT EXISTS ix_qa_schedule_runs_schedule
    ON qa_schedule_runs (schedule_id, ran_at DESC);

-- qa_reports needs its own id exposed for the join above — it already has
-- one (id UUID PRIMARY KEY per setup/qa_schema.sql), nothing to add there.

COMMIT;

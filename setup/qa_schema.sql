-- ══════════════════════════════════════════════════════════════════════════
--  QA Insights — schema for the reporting & summarizing agent
-- ══════════════════════════════════════════════════════════════════════════
--
-- The agent ingests a QA workbook (.xlsx) or reads an existing Postgres
-- source, normalizes it, and writes a SNAPSHOT. Everything downstream — the
-- metrics registry, the insight engine, the narrator — reads these tables and
-- never touches openpyxl again.
--
-- Why snapshots rather than upserts: a QA workbook is a point-in-time
-- statement of test state. Overwriting it destroys the very thing the
-- dashboard is for — how coverage and severity moved between builds. Each
-- ingest appends; nothing is ever mutated in place.
--
-- Bugs carry a real `created` date, so the dashboard's date range filters them
-- directly. Test cases and localization cells have no per-row date — they are
-- the state of a snapshot — so for those the date range selects which
-- SNAPSHOTS are in scope, and metrics read the latest one in the window.
--
--   psql -U postgres -d dashboards_dev -f setup/qa_schema.sql

BEGIN;

-- ── snapshots ────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS qa_snapshots (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_kind   TEXT        NOT NULL CHECK (source_kind IN ('xlsx', 'postgres')),
    source_label  TEXT        NOT NULL,          -- filename, or source table set
    fingerprint   TEXT        NOT NULL,          -- structural hash of the layout
    ingested_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    sheets_json   JSONB       NOT NULL DEFAULT '[]'::jsonb,
    warnings      JSONB       NOT NULL DEFAULT '[]'::jsonb
);

CREATE INDEX IF NOT EXISTS ix_qa_snap_ingested ON qa_snapshots (ingested_at DESC);
CREATE INDEX IF NOT EXISTS ix_qa_snap_finger   ON qa_snapshots (fingerprint);

-- ── bugs ─────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS qa_bugs (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    snapshot_id   UUID NOT NULL REFERENCES qa_snapshots(id) ON DELETE CASCADE,
    bug_key       TEXT NOT NULL,                 -- '11#' as written in the sheet
    source_sheet  TEXT NOT NULL,
    source_row    INTEGER NOT NULL,

    created       DATE,
    severity      TEXT    NOT NULL DEFAULT 'Unknown',
    severity_rank INTEGER NOT NULL DEFAULT 0,    -- Blocker 5 .. Trivial 1
    issue_type    TEXT,
    summary       TEXT,
    description   TEXT,
    steps         TEXT,
    actual        TEXT,
    expected      TEXT,
    build         TEXT,
    status        TEXT    NOT NULL DEFAULT 'Unknown',
    is_open       BOOLEAN NOT NULL DEFAULT FALSE,
    resolution    TEXT,
    dev_comments  TEXT,
    comments      TEXT,

    -- Free-text search is the one thing a column predicate cannot express.
    search        TSVECTOR GENERATED ALWAYS AS (
        to_tsvector('english',
            coalesce(summary, '') || ' ' || coalesce(description, '') || ' ' ||
            coalesce(actual, '')  || ' ' || coalesce(expected, '')    || ' ' ||
            coalesce(dev_comments, '') || ' ' || coalesce(comments, ''))
    ) STORED,

    UNIQUE (snapshot_id, bug_key, source_row)
);

CREATE INDEX IF NOT EXISTS ix_qa_bugs_snap     ON qa_bugs (snapshot_id);
CREATE INDEX IF NOT EXISTS ix_qa_bugs_created  ON qa_bugs (created);
CREATE INDEX IF NOT EXISTS ix_qa_bugs_sev      ON qa_bugs (severity_rank DESC);
CREATE INDEX IF NOT EXISTS ix_qa_bugs_status   ON qa_bugs (status);
CREATE INDEX IF NOT EXISTS ix_qa_bugs_open     ON qa_bugs (is_open) WHERE is_open;
CREATE INDEX IF NOT EXISTS ix_qa_bugs_type     ON qa_bugs (issue_type);
CREATE INDEX IF NOT EXISTS ix_qa_bugs_search   ON qa_bugs USING GIN (search);

-- ── test cases ───────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS qa_test_cases (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    snapshot_id   UUID NOT NULL REFERENCES qa_snapshots(id) ON DELETE CASCADE,
    source_sheet  TEXT NOT NULL,
    source_row    INTEGER NOT NULL,

    module        TEXT,
    section       TEXT,
    description   TEXT,
    steps         TEXT,
    expected      TEXT,
    status        TEXT    NOT NULL DEFAULT 'Not Run',
    was_executed  BOOLEAN NOT NULL DEFAULT FALSE,
    comments      TEXT
);

CREATE INDEX IF NOT EXISTS ix_qa_tc_snap    ON qa_test_cases (snapshot_id);
CREATE INDEX IF NOT EXISTS ix_qa_tc_status  ON qa_test_cases (status);
CREATE INDEX IF NOT EXISTS ix_qa_tc_module  ON qa_test_cases (module);
CREATE INDEX IF NOT EXISTS ix_qa_tc_exec    ON qa_test_cases (was_executed);

-- A test case cites the bugs it failed against. Kept as the raw key rather
-- than an FK: the sheet routinely cites a bug id that no row defines, and
-- losing that citation would hide the dangling reference the report calls out.
CREATE TABLE IF NOT EXISTS qa_test_case_bugs (
    test_case_id  UUID NOT NULL REFERENCES qa_test_cases(id) ON DELETE CASCADE,
    bug_key       TEXT NOT NULL,
    PRIMARY KEY (test_case_id, bug_key)
);

CREATE INDEX IF NOT EXISTS ix_qa_tcb_bug ON qa_test_case_bugs (bug_key);

-- ── localization / compatibility matrix, unpivoted to long form ──────────

CREATE TABLE IF NOT EXISTS qa_matrix_results (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    snapshot_id   UUID NOT NULL REFERENCES qa_snapshots(id) ON DELETE CASCADE,
    source_sheet  TEXT NOT NULL,
    source_row    INTEGER NOT NULL,

    section       TEXT,          -- banner row above the item ('MAIN MENU')
    item          TEXT,          -- row label ('Swordsman')
    dimension     TEXT NOT NULL, -- column header ('Polish')
    status        TEXT NOT NULL DEFAULT 'Unknown',
    comment       TEXT
);

CREATE INDEX IF NOT EXISTS ix_qa_mx_snap   ON qa_matrix_results (snapshot_id);
CREATE INDEX IF NOT EXISTS ix_qa_mx_dim    ON qa_matrix_results (dimension);
CREATE INDEX IF NOT EXISTS ix_qa_mx_status ON qa_matrix_results (status);
CREATE INDEX IF NOT EXISTS ix_qa_mx_item   ON qa_matrix_results (item);

-- ── agent reports ────────────────────────────────────────────────────────
--
-- The narrated report is persisted rather than held in memory, so a restart
-- (or a second worker) does not lose it and the dashboard can render the last
-- known summary while a new analysis runs.

CREATE TABLE IF NOT EXISTS qa_reports (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    snapshot_id   UUID NOT NULL REFERENCES qa_snapshots(id) ON DELETE CASCADE,
    generated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    model_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    model_name    TEXT,
    partial       BOOLEAN NOT NULL DEFAULT FALSE,
    elapsed_s     REAL,
    payload       JSONB NOT NULL          -- {executive_summary, findings, stats, ...}
);

CREATE INDEX IF NOT EXISTS ix_qa_reports_snap ON qa_reports (snapshot_id, generated_at DESC);

COMMIT;

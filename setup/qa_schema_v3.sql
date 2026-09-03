-- ══════════════════════════════════════════════════════════════════════════
--  QA Insights — migration: multi-file snapshots
-- ══════════════════════════════════════════════════════════════════════════
--
-- A snapshot was one file. A real QA cycle is several: a gameplay test plan,
-- a map test plan, this week's bug tracker, last week's. They belong in ONE
-- analysis — the agent should be able to say "the map plan is the one behind"
-- — but each row still has to remember which file it came from, or per-plan
-- reporting is impossible.
--
-- The identity fix matters more than the new column. `qa_bugs` was UNIQUE on
-- (snapshot_id, bug_key, source_row), which is fine when a snapshot is one
-- file and catastrophic when it is four: two trackers both numbering their
-- first bug "1#" on row 2 collide, and the INSERT's ON CONFLICT DO NOTHING
-- drops one silently. No error, no warning, just a bug that never appears in
-- the report. source_file joins the key so that cannot happen.
--
-- Additive and idempotent; safe to run over an existing database.
--
--   psql -U postgres -d dashboards_dev -f setup/qa_schema_v3.sql

BEGIN;

-- ── per-row file attribution ─────────────────────────────────────────────
-- NOT NULL DEFAULT '' rather than nullable: NULLs are distinct from each
-- other in a UNIQUE index, so a nullable source_file would silently switch
-- the constraint below back off for every pre-migration row.

ALTER TABLE qa_bugs           ADD COLUMN IF NOT EXISTS source_file TEXT NOT NULL DEFAULT '';
ALTER TABLE qa_test_cases     ADD COLUMN IF NOT EXISTS source_file TEXT NOT NULL DEFAULT '';
ALTER TABLE qa_matrix_results ADD COLUMN IF NOT EXISTS source_file TEXT NOT NULL DEFAULT '';

CREATE INDEX IF NOT EXISTS ix_qa_bugs_file ON qa_bugs (snapshot_id, source_file);
CREATE INDEX IF NOT EXISTS ix_qa_tc_file   ON qa_test_cases (snapshot_id, source_file);
CREATE INDEX IF NOT EXISTS ix_qa_mx_file   ON qa_matrix_results (snapshot_id, source_file);

-- ── the identity fix ─────────────────────────────────────────────────────

ALTER TABLE qa_bugs DROP CONSTRAINT IF EXISTS qa_bugs_snapshot_id_bug_key_source_row_key;
ALTER TABLE qa_bugs DROP CONSTRAINT IF EXISTS qa_bugs_identity;
ALTER TABLE qa_bugs ADD CONSTRAINT qa_bugs_identity
    UNIQUE (snapshot_id, source_file, source_sheet, bug_key, source_row);

-- ── snapshot-level file manifest ─────────────────────────────────────────
-- What was uploaded, in what order, and what each file turned out to be.
-- Kept alongside sheets_json rather than derived from it so the ingest
-- receipt can show a file that parsed to zero usable rows — which is a
-- result worth seeing, and invisible if files are only inferred from rows.

ALTER TABLE qa_snapshots ADD COLUMN IF NOT EXISTS source_files JSONB NOT NULL DEFAULT '[]'::jsonb;

COMMIT;

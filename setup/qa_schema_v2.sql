-- ══════════════════════════════════════════════════════════════════════════
--  QA Insights — migration: real test case identity
-- ══════════════════════════════════════════════════════════════════════════
--
-- The first schema assumed a test plan identifies its cases only by sheet
-- position, which was true of the pilot workbook. Plenty of plans carry a real
-- "Test Case ID" column (TC-001), plus a Feature, a Priority and a Title, and
-- those are what a tester searches for — a row number is not.
--
-- Additive and idempotent; safe to run over an existing database.
--
--   psql -U postgres -d dashboards_dev -f setup/qa_schema_v2.sql

BEGIN;

ALTER TABLE qa_test_cases ADD COLUMN IF NOT EXISTS case_id       TEXT;
ALTER TABLE qa_test_cases ADD COLUMN IF NOT EXISTS title         TEXT;
ALTER TABLE qa_test_cases ADD COLUMN IF NOT EXISTS priority      TEXT;
ALTER TABLE qa_test_cases ADD COLUMN IF NOT EXISTS preconditions TEXT;

-- Cases are looked up by their id constantly once one exists.
CREATE INDEX IF NOT EXISTS ix_qa_tc_case_id  ON qa_test_cases (case_id);
CREATE INDEX IF NOT EXISTS ix_qa_tc_priority ON qa_test_cases (priority);

COMMIT;

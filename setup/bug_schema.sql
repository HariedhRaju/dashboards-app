-- Bug reports schema for the dashboards dev environment.
--
-- Separate from token_usage — uses its own bug_users / bug_projects tables
-- so the two dashboards don't collide.
--
-- Usage:
--   psql -U postgres -d dashboards_dev -f bug_schema.sql

-- Enum types (create only if absent).
DO $$ BEGIN
    CREATE TYPE bug_severity AS ENUM ('P1', 'P2', 'P3', 'P4');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE bug_status AS ENUM ('open', 'in_progress', 'fixed', 'closed');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

CREATE TABLE IF NOT EXISTS bug_users (
    id    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name  TEXT NOT NULL,
    email TEXT
);

CREATE TABLE IF NOT EXISTS bug_projects (
    id    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name  TEXT NOT NULL,
    code  VARCHAR(16)
);

CREATE TABLE IF NOT EXISTS bug_reports (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id     UUID NOT NULL REFERENCES bug_projects(id),
    reported_by    UUID NOT NULL REFERENCES bug_users(id),
    template_id    UUID,
    title          VARCHAR(300) NOT NULL,
    summary        TEXT,
    severity       bug_severity NOT NULL,
    status         bug_status   NOT NULL DEFAULT 'open',
    dynamic_fields JSONB,
    created_at     TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at     TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- Indexes for dashboard queries.
CREATE INDEX IF NOT EXISTS idx_bug_reports_created   ON bug_reports (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_bug_reports_updated   ON bug_reports (updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_bug_reports_severity  ON bug_reports (severity, status);
CREATE INDEX IF NOT EXISTS idx_bug_reports_status    ON bug_reports (status);
CREATE INDEX IF NOT EXISTS idx_bug_reports_project   ON bug_reports (project_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_bug_reports_reporter  ON bug_reports (reported_by, created_at DESC);

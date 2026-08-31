-- ============================================================================
-- ReportIQ Database Schema
--
-- Usage:
--   psql -U postgres -d your_db -f setup/reportiq_schema.sql
-- ============================================================================

-- 1. Base entities
CREATE TABLE IF NOT EXISTS users (
    id    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name  TEXT NOT NULL,
    email TEXT
);

CREATE TABLE IF NOT EXISTS projects (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            TEXT NOT NULL,
    code            VARCHAR(16),
    progress_pct    INTEGER NOT NULL DEFAULT 0,
    health_status   VARCHAR(20) NOT NULL DEFAULT 'on_track',
    delivery_score  INTEGER NOT NULL DEFAULT 0,
    quality_score   INTEGER NOT NULL DEFAULT 0,
    testing_score   INTEGER NOT NULL DEFAULT 0,
    build_score     INTEGER NOT NULL DEFAULT 0,
    reporting_score INTEGER NOT NULL DEFAULT 0,
    target_date     DATE,
    planned_pct     INTEGER NOT NULL DEFAULT 0
);

-- Ensure all columns exist if table was already created
ALTER TABLE projects ADD COLUMN IF NOT EXISTS progress_pct    INTEGER NOT NULL DEFAULT 0;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS health_status   VARCHAR(20) NOT NULL DEFAULT 'on_track';
ALTER TABLE projects ADD COLUMN IF NOT EXISTS delivery_score  INTEGER NOT NULL DEFAULT 0;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS quality_score   INTEGER NOT NULL DEFAULT 0;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS testing_score   INTEGER NOT NULL DEFAULT 0;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS build_score     INTEGER NOT NULL DEFAULT 0;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS reporting_score INTEGER NOT NULL DEFAULT 0;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS target_date     DATE;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS planned_pct     INTEGER NOT NULL DEFAULT 0;

-- 2. Report Templates & Builds
CREATE TABLE IF NOT EXISTS report_templates (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name                 TEXT NOT NULL,
    category             VARCHAR(50) NOT NULL,
    avg_compile_time_sec FLOAT NOT NULL DEFAULT 3.5,
    default_format       VARCHAR(20) NOT NULL DEFAULT 'pdf',
    created_at           TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS builds (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id   UUID NOT NULL REFERENCES projects(id),
    build_tag    VARCHAR(50),
    version      VARCHAR(50),
    status       VARCHAR(20) NOT NULL DEFAULT 'PASS',
    audit_score  INTEGER NOT NULL DEFAULT 95,
    created_at   TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- 3. Report Logs & Uploads
CREATE TABLE IF NOT EXISTS report_logs (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id           UUID NOT NULL REFERENCES projects(id),
    build_id             UUID REFERENCES builds(id),
    template_id          UUID NOT NULL REFERENCES report_templates(id),
    title                VARCHAR(250) NOT NULL,
    author_id            UUID NOT NULL REFERENCES users(id),
    output_format        VARCHAR(20) NOT NULL DEFAULT 'pdf',
    report_type          VARCHAR(10) NOT NULL DEFAULT 'DSR',
    compilation_time_sec FLOAT NOT NULL DEFAULT 3.2,
    tokens_used          INTEGER NOT NULL DEFAULT 1200,
    pipeline_stage       VARCHAR(20) NOT NULL DEFAULT 'published',
    created_at           TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS uploaded_files (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id       UUID REFERENCES projects(id),
    filename         VARCHAR(255) NOT NULL,
    file_type        VARCHAR(50) NOT NULL DEFAULT 'document',
    file_size_bytes  BIGINT NOT NULL DEFAULT 102400,
    uploaded_by      UUID REFERENCES users(id),
    created_at       TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- 4. Project Tracking & Intelligence Tables
CREATE TABLE IF NOT EXISTS project_milestones (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id   UUID NOT NULL REFERENCES projects(id),
    name         VARCHAR(120) NOT NULL,
    status       VARCHAR(20)  NOT NULL DEFAULT 'upcoming',
    target_date  DATE,
    completed_at DATE,
    sort_order   INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS project_timeline_events (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id  UUID NOT NULL REFERENCES projects(id),
    event_type  VARCHAR(40) NOT NULL,
    title       VARCHAR(200) NOT NULL,
    description TEXT,
    event_date  DATE NOT NULL,
    severity    VARCHAR(20) NOT NULL DEFAULT 'info'
);

CREATE TABLE IF NOT EXISTS project_progress_history (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id   UUID NOT NULL REFERENCES projects(id),
    recorded_date DATE NOT NULL,
    planned_pct  INTEGER NOT NULL DEFAULT 0,
    actual_pct   INTEGER NOT NULL DEFAULT 0,
    UNIQUE (project_id, recorded_date)
);

CREATE TABLE IF NOT EXISTS project_risks (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id  UUID NOT NULL REFERENCES projects(id),
    risk_type   VARCHAR(40) NOT NULL,
    severity    VARCHAR(20) NOT NULL DEFAULT 'warning',
    title       VARCHAR(200) NOT NULL,
    detail      TEXT,
    is_active   BOOLEAN NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- 5. Performance Indexes
CREATE INDEX IF NOT EXISTS idx_report_logs_created   ON report_logs (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_report_logs_project   ON report_logs (project_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_report_logs_template  ON report_logs (template_id);
CREATE INDEX IF NOT EXISTS idx_report_logs_build     ON report_logs (build_id);
CREATE INDEX IF NOT EXISTS idx_builds_project         ON builds (project_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_progress_history_proj ON project_progress_history (project_id, recorded_date);
CREATE INDEX IF NOT EXISTS idx_timeline_proj         ON project_timeline_events (project_id, event_date DESC);
CREATE INDEX IF NOT EXISTS idx_milestones_proj       ON project_milestones (project_id, sort_order ASC);
CREATE INDEX IF NOT EXISTS idx_risks_proj            ON project_risks (project_id, is_active);

-- Database schema for the dashboards dev environment.
--
-- Idempotent: safe to re-run on an existing DB (uses IF NOT EXISTS).
--
-- Usage:
--   psql -U postgres -c "CREATE DATABASE dashboards_dev;"
--   psql -U postgres -d dashboards_dev -f schema.sql

CREATE TABLE IF NOT EXISTS users (
    id    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name  TEXT NOT NULL,
    email TEXT
);

CREATE TABLE IF NOT EXISTS projects (
    id    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name  TEXT NOT NULL,
    code  VARCHAR(16)
);

CREATE TABLE IF NOT EXISTS token_usage (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    timestamp         TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    user_id           UUID NOT NULL REFERENCES users(id),
    project_id        UUID NOT NULL REFERENCES projects(id),
    feature           VARCHAR(50),
    model_name        VARCHAR(100),
    prompt_tokens     INTEGER NOT NULL,
    completion_tokens INTEGER NOT NULL,
    total_tokens      INTEGER NOT NULL
);

-- If schema already existed without these columns, add them.
ALTER TABLE users    ADD COLUMN IF NOT EXISTS email TEXT;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS code  VARCHAR(16);

-- Indexes used by dashboard queries.
CREATE INDEX IF NOT EXISTS idx_token_usage_timestamp  ON token_usage (timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_token_usage_project_ts ON token_usage (project_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_token_usage_user_ts    ON token_usage (user_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_token_usage_model_ts   ON token_usage (model_name, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_token_usage_feature    ON token_usage (feature);

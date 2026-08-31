-- ============================================================================
-- ReportIQ Database Seed Data (Static SQL)
--
-- Usage:
--   psql -U postgres -d your_db -f setup/reportiq_seed.sql
-- ============================================================================

-- Ensure base users exist
INSERT INTO users (name, email)
SELECT name, email FROM (VALUES
  ('Sarah Connor',   'sarah.connor@example.com'),
  ('Alex Chen',      'alex.chen@example.com'),
  ('Elena Rostova',  'elena.rostova@example.com'),
  ('David Kim',      'david.kim@example.com'),
  ('Marcus Vance',   'marcus.vance@example.com')
) AS v(name, email)
WHERE NOT EXISTS (SELECT 1 FROM users WHERE email = v.email);

-- Ensure base projects exist
INSERT INTO projects (name, code, progress_pct, health_status, delivery_score, quality_score, testing_score, build_score, reporting_score, target_date, planned_pct)
SELECT name, code, progress_pct, health_status, delivery_score, quality_score, testing_score, build_score, reporting_score, target_date::date, planned_pct FROM (VALUES
  ('Apollo Core Engine',    'APOLLO', 88, 'on_track', 92, 90, 89, 98, 95, '2026-10-15', 85),
  ('Neon Gateway API',      'NEON',   64, 'at_risk',  68, 72, 60, 88, 80, '2026-11-30', 80),
  ('Titan ML Platform',     'TITAN',  42, 'delayed',  45, 50, 48, 75, 70, '2026-12-15', 65),
  ('Quantum Pay Service',   'QPAY',   92, 'on_track', 95, 96, 94, 100,98, '2026-09-30', 90),
  ('Spectra Cloud Ingest',  'SPEC',   78, 'on_track', 82, 85, 80, 94, 91, '2026-10-31', 78),
  ('Nexus UI Design System','NEXUS',  84, 'on_track', 88, 91, 87, 96, 94, '2026-11-15', 82)
) AS v(name, code, progress_pct, health_status, delivery_score, quality_score, testing_score, build_score, reporting_score, target_date, planned_pct)
WHERE NOT EXISTS (SELECT 1 FROM projects WHERE code = v.code);

-- Wipe and re-insert report templates
TRUNCATE TABLE report_templates CASCADE;

INSERT INTO report_templates (name, category, avg_compile_time_sec, default_format) VALUES
  ('Executive Quality Digest',       'Executive Summary',    2.8, 'pdf'),
  ('Release Gate Readiness Audit',   'Release Gate Audit',   4.5, 'pdf'),
  ('Daily QA Standup & Defect Log',  'Daily QA Standup',     1.9, 'md'),
  ('Sprint Retrospective Analysis',  'Sprint Retrospective', 3.6, 'xlsx'),
  ('Client Release Sign-Off Report', 'Release Gate Audit',   5.1, 'pdf');

-- Builds for projects
TRUNCATE TABLE builds CASCADE;

INSERT INTO builds (project_id, build_tag, version, status, audit_score, created_at)
SELECT p.id, b.tag, b.tag, b.status, b.score, NOW() - (b.age_days * INTERVAL '1 day')
FROM projects p
CROSS JOIN (
  VALUES 
    ('v2.4.0-rc1', 'PASS', 98, 2),
    ('v2.4.0-rc2', 'PASS', 100, 1),
    ('v2.3.9-patch', 'WARN', 82, 5),
    ('v2.3.8-release', 'PASS', 96, 12)
) AS b(tag, status, score, age_days);

-- Insert ~300 report_logs linked to projects, builds, templates, and users
TRUNCATE TABLE report_logs CASCADE;

WITH lookups AS (
    SELECT
        ARRAY(SELECT id FROM users) AS users_arr,
        ARRAY(SELECT id FROM projects) AS projects_arr,
        ARRAY(SELECT id FROM report_templates) AS templates_arr,
        ARRAY(SELECT id FROM builds) AS builds_arr,
        ARRAY['pdf', 'xlsx', 'md']::text[] AS formats_arr,
        ARRAY['DSR', 'DSR', 'DSR', 'WSR']::text[] AS types_arr,
        ARRAY['published', 'published', 'published', 'compiled', 'summarized', 'ingested']::text[] AS stages_arr
)
INSERT INTO report_logs (
    project_id, build_id, template_id, title, author_id,
    output_format, report_type, compilation_time_sec, tokens_used, pipeline_stage, created_at
)
SELECT
    p_id,
    b_id,
    t_id,
    'ReportIQ Audit — ' || (ARRAY['Build Verification', 'Executive Status', 'QA Release Gate', 'Sprint Review', 'Client Delivery'])[1 + floor(random() * 5)::int] || ' #' || i,
    users_arr[1 + floor(random() * array_length(users_arr, 1))::int],
    formats_arr[1 + floor(random() * array_length(formats_arr, 1))::int],
    types_arr[1 + floor(random() * array_length(types_arr, 1))::int],
    ROUND((1.2 + random() * 4.8)::numeric, 1)::float,
    (800 + random() * 2200)::int,
    stages_arr[1 + floor(random() * array_length(stages_arr, 1))::int],
    NOW() - (power(random(), 2) * INTERVAL '90 days')
FROM generate_series(1, 300) i, lookups,
LATERAL (SELECT projects_arr[1 + floor(random() * array_length(projects_arr, 1))::int] AS p_id) p,
LATERAL (SELECT templates_arr[1 + floor(random() * array_length(templates_arr, 1))::int] AS t_id) t,
LATERAL (SELECT builds_arr[1 + floor(random() * array_length(builds_arr, 1))::int] AS b_id) b;

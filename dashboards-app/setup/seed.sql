-- Seed data for local development.
--
-- Wipes existing data and re-inserts. Safe to run repeatedly.
--
-- Produces:
--   ~10 users with realistic emails
--   6 projects with short codes (ATLS, MP, INS, BCN, CMP, plus "Global/No Project")
--   7 features matching typical LLM ops dashboards
--   6 models (mix of qwen, granite, claude, gpt, etc.)
--   200 000 token_usage rows spread over the last 3 years, skewed toward recent

-- Wipe existing.
TRUNCATE TABLE token_usage;
TRUNCATE TABLE users    CASCADE;
TRUNCATE TABLE projects CASCADE;

INSERT INTO users (name, email) VALUES
  ('Sridhar S',        'sridhar.samraj@indium.tech'),
  ('Sanjeev R',        'sanjeev.r@indium.tech'),
  ('Prashanth T S',    'prashanth.ts@indium.tech'),
  ('Divyansh Jain',    'divyansh.jain@indium.tech'),
  ('Sulaiman Khan',    'sulaiman.khan@indium.tech'),
  ('Maya Rodriguez',   'maya.rodriguez@indium.tech'),
  ('Jordan Chen',      'jordan.chen@indium.tech'),
  ('Riya Sharma',      'riya.sharma@indium.tech'),
  ('Marcus Freeman',   'marcus.freeman@indium.tech'),
  ('System/Guest',     'guest@indium.tech');

INSERT INTO projects (name, code) VALUES
  ('Global/No Project', 'GLOBAL'),
  ('Microprose',        'MP'),
  ('Atlas',             'ATLS'),
  ('Copilot',           'CPLT'),
  ('Insight',           'INS'),
  ('Beacon',            'BCN');

-- Precompute arrays once so we don't do per-row subqueries.
WITH lookups AS (
    SELECT
        ARRAY(SELECT id FROM users)    AS users_arr,
        ARRAY(SELECT id FROM projects) AS projects_arr,
        ARRAY['Chat', 'Bug Bot', 'Ask Anything', 'Test Features',
              'Test Case Gen', 'Resource Allocation', 'Unknown']::text[] AS features_arr,
        ARRAY['qwen2.5:14b-instruct', 'granite4.1:8b', 'ornith:latest',
              'gpt-4', 'claude-3-sonnet', 'llama-3']::text[] AS models_arr
)
INSERT INTO token_usage
    (timestamp, user_id, project_id, feature, model_name,
     prompt_tokens, completion_tokens, total_tokens)
SELECT
    -- power(random(), 2) skews toward NOW — recent = denser
    NOW() - (power(random(), 2) * INTERVAL '1095 days'),
    users_arr[1     + floor(random() * array_length(users_arr, 1))::int],
    projects_arr[1  + floor(random() * array_length(projects_arr, 1))::int],
    features_arr[1  + floor(random() * array_length(features_arr, 1))::int],
    models_arr[1    + floor(random() * array_length(models_arr, 1))::int],
    (100 + random() * 2900)::int,      -- prompts range wider (100-3000)
    (30  + random() * 570)::int,       -- completions smaller (30-600)
    0
FROM generate_series(1, 200000), lookups;

UPDATE token_usage
SET total_tokens = prompt_tokens + completion_tokens
WHERE total_tokens = 0;

SELECT
    COUNT(*)             AS total_rows,
    MIN(timestamp)::date AS earliest,
    MAX(timestamp)::date AS latest,
    SUM(total_tokens)    AS total_tokens,
    (SELECT COUNT(*) FROM users)    AS users,
    (SELECT COUNT(*) FROM projects) AS projects
FROM token_usage;

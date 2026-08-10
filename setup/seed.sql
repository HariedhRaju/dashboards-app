-- Seed data for local development.
--
-- Usage:
--   psql -U postgres -d dashboards_dev -f seed.sql
--
-- Produces:
--   10 users, 5 projects, 5000 token_usage rows spread over the last 30 days.

INSERT INTO users (name) VALUES
  ('Maya Rodriguez'), ('Jordan Chen'), ('Alex Patel'),
  ('Sam Kim'),        ('Riya Sharma'), ('Chris Ng'),
  ('Deniz Yılmaz'),   ('Priya Iyer'),  ('Marcus Freeman'),
  ('Elena Vasquez');

INSERT INTO projects (name) VALUES
  ('Atlas'), ('Copilot'), ('Insight'), ('Beacon'), ('Compass');

INSERT INTO token_usage
    (timestamp, user_id, project_id, feature, model_name,
     prompt_tokens, completion_tokens, total_tokens)
SELECT
    NOW() - (random() * INTERVAL '30 days'),
    (SELECT id FROM users    ORDER BY random() LIMIT 1),
    (SELECT id FROM projects ORDER BY random() LIMIT 1),
    (ARRAY['chat', 'summarize', 'code_assist', 'search', 'translate'])
        [floor(random() * 5 + 1)],
    (ARRAY['gpt-4', 'gpt-3.5', 'claude-3', 'llama-3'])
        [floor(random() * 4 + 1)],
    (100 + random() * 400)::int,
    (50  + random() * 300)::int,
    0
FROM generate_series(1, 5000);

UPDATE token_usage
SET total_tokens = prompt_tokens + completion_tokens
WHERE total_tokens = 0;

SELECT COUNT(*) AS total_rows, SUM(total_tokens) AS total_tokens FROM token_usage;

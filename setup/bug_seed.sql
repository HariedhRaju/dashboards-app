-- Bug reports seed data.
--
-- Wipes and re-inserts. Safe to run repeatedly.
--
-- Produces:
--   8 QA reporters, 6 game projects, ~15 000 bug reports over 18 months,
--   realistic severity/status distributions, and updated_at set so that
--   closed bugs have a plausible resolution time after created_at.

TRUNCATE TABLE bug_reports;
TRUNCATE TABLE bug_users    CASCADE;
TRUNCATE TABLE bug_projects CASCADE;

INSERT INTO bug_users (name, email) VALUES
  ('Admin User',    'admin@indium.tech'),
  ('John Tester',   'john.tester@indium.tech'),
  ('Sarah QA',      'sarah.qa@indium.tech'),
  ('Miguel Reyes',  'miguel.reyes@indium.tech'),
  ('Aisha Khan',    'aisha.khan@indium.tech'),
  ('Tom Nguyen',    'tom.nguyen@indium.tech'),
  ('Lena Fischer',  'lena.fischer@indium.tech'),
  ('Raj Malhotra',  'raj.malhotra@indium.tech');

INSERT INTO bug_projects (name, code) VALUES
  ('Stellar Odyssey',  'STLR'),
  ('Lumina',           'LUM'),
  ('Civilization Tab', 'CIV'),
  ('Micoprose',        'MICR'),
  ('Nova Realms',      'NOVA'),
  ('Pixel Quest',      'PXQ');

-- Bug title fragments for realistic-looking titles.
WITH lookups AS (
    SELECT
        ARRAY(SELECT id FROM bug_users)    AS users_arr,
        ARRAY(SELECT id FROM bug_projects) AS projects_arr,
        ARRAY[
            'FPS drops below 15 in dense multiplayer combat',
            'Memory leak causes 4GB allocation spike in main hub',
            'Audio cuts out completely after 45 minutes of gameplay',
            'Item replication exploit in trading window',
            'Texture flickering on ramp entry when Ray Tracing is ON',
            'Screen goes blank during boss fight entry',
            'Close button fails to work in civilization tab',
            'HUD disappears after clearing node and quitting to menu',
            'Game crashes when mutating final pillar with full inventory',
            'Save corruption when quitting during autosave',
            'Character clips through floor near spawn point',
            'Multiplayer desync after host migration',
            'Controller input lag on menu navigation',
            'Shadows render incorrectly at dusk',
            'Quest marker points to wrong location',
            'Inventory sort resets after fast travel'
        ]::text[] AS titles_arr,
        ARRAY['P1','P2','P3','P4']::text[]                    AS sev_arr,
        ARRAY['open','in_progress','fixed','closed']::text[]  AS status_arr
)
INSERT INTO bug_reports
    (project_id, reported_by, title, summary, severity, status, created_at, updated_at)
SELECT
    projects_arr[1 + floor(random() * array_length(projects_arr, 1))::int],
    users_arr[1    + floor(random() * array_length(users_arr, 1))::int],
    titles_arr[1   + floor(random() * array_length(titles_arr, 1))::int],
    'Auto-generated bug summary for dev/testing.',
    -- Severity skew: more P2/P3 than P1/P4 (realistic)
    (ARRAY['P1','P2','P2','P3','P3','P3','P4'])[1 + floor(random() * 7)::int]::bug_severity,
    -- Status skew: assigned below in the UPDATE steps
    'open'::bug_status,
    created_ts,
    created_ts       -- placeholder; updated below
FROM (
    SELECT NOW() - (power(random(), 1.5) * INTERVAL '540 days') AS created_ts
    FROM generate_series(1, 15000)
) gen, lookups;

-- Assign statuses with a realistic distribution.
-- ~24% open, ~21% in_progress, ~16% fixed, ~39% closed (matches the screenshot).
UPDATE bug_reports SET status = CASE
    WHEN random() < 0.24 THEN 'open'
    WHEN random() < 0.45 THEN 'in_progress'
    WHEN random() < 0.61 THEN 'fixed'
    ELSE 'closed'
END::bug_status;

-- For closed bugs, set updated_at to created_at + a resolution delay that
-- scales with severity (P1s fixed fast, P4s slow). Gives meaningful MTTR.
UPDATE bug_reports
SET updated_at = created_at + (
    CASE severity
        WHEN 'P1' THEN (0.2 + random() * 2)   -- 0.2-2.2 days
        WHEN 'P2' THEN (1   + random() * 5)   -- 1-6 days
        WHEN 'P3' THEN (3   + random() * 14)  -- 3-17 days
        ELSE          (7   + random() * 30)   -- 7-37 days
    END * INTERVAL '1 day'
)
WHERE status = 'closed';

-- For non-closed bugs, nudge updated_at slightly after created_at.
UPDATE bug_reports
SET updated_at = created_at + (random() * INTERVAL '2 days')
WHERE status <> 'closed';

SELECT
    COUNT(*)                                               AS total_bugs,
    COUNT(*) FILTER (WHERE status = 'closed')              AS closed,
    COUNT(*) FILTER (WHERE status <> 'closed')             AS unresolved,
    COUNT(*) FILTER (WHERE severity = 'P1')                AS p1,
    MIN(created_at)::date                                  AS earliest,
    MAX(created_at)::date                                  AS latest
FROM bug_reports;

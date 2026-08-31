"""
Seed script for ReportIQ in qa_assistant database.
Populates:
  - Additional projects & builds
  - Report templates
  - Report logs (~350 rows spread over the last 90 days)
"""
import os
import random
import psycopg2

def seed():
    dsn = os.environ.get('DASHBOARDS_REPLICA_DSN', 'postgresql://postgres:ash%40123@localhost:5432/qa_assistant')
    conn = psycopg2.connect(dsn)
    cur = conn.cursor()

    # 1. Ensure report_templates has helpful columns
    cur.execute("""
        ALTER TABLE report_templates ADD COLUMN IF NOT EXISTS name TEXT;
        ALTER TABLE report_templates ADD COLUMN IF NOT EXISTS category VARCHAR(50);
        ALTER TABLE report_templates ADD COLUMN IF NOT EXISTS avg_compile_time_sec FLOAT DEFAULT 3.5;
        ALTER TABLE report_templates ADD COLUMN IF NOT EXISTS default_format VARCHAR(20) DEFAULT 'pdf';
        
        ALTER TABLE builds ADD COLUMN IF NOT EXISTS audit_score INTEGER DEFAULT 95;
        ALTER TABLE builds ADD COLUMN IF NOT EXISTS status VARCHAR(20) DEFAULT 'PASS';
    """)
    conn.commit()

    # 2. Insert additional projects if missing
    projects_data = [
        ('Stellar Odyssey', 'STOD'),
        ('Microprose', 'MP'),
        ('Atlas Core', 'ATLS'),
        ('Copilot AI', 'CPLT'),
        ('Beacon Hub', 'BCN')
    ]
    
    # 2. Fetch existing users first
    cur.execute("SELECT id FROM users LIMIT 10")
    user_ids = [r[0] for r in cur.fetchall()]
    admin_id = user_ids[0] if user_ids else None

    project_ids = []
    for name, code in projects_data:
        cur.execute("SELECT id FROM projects WHERE code = %s", (code,))
        row = cur.fetchone()
        if row:
            project_ids.append(row[0])
        else:
            cur.execute("INSERT INTO projects (id, name, code, created_by) VALUES (gen_random_uuid(), %s, %s, %s) RETURNING id", (name, code, admin_id))
            project_ids.append(cur.fetchone()[0])
    conn.commit()

    # 4. Insert builds per project
    build_ids = []
    statuses = ['PASS', 'PASS', 'PASS', 'WARN', 'FAIL']
    versions = ['v2.4.0-rc1', 'v2.4.0-rc2', 'v2.3.9-patch', 'v2.3.8-release', 'v3.0.0-alpha']
    
    for pid in project_ids:
        for idx, ver in enumerate(versions):
            cur.execute("""
                SELECT id FROM builds WHERE project_id = %s AND version = %s
            """, (pid, ver))
            row = cur.fetchone()
            if row:
                build_ids.append(row[0])
            else:
                score = random.randint(75, 100) if idx != 4 else random.randint(45, 70)
                st = 'PASS' if score >= 85 else ('WARN' if score >= 65 else 'FAIL')
                cur.execute("""
                    INSERT INTO builds (id, project_id, version, platform, is_current, audit_score, status)
                    VALUES (gen_random_uuid(), %s, %s, %s, %s, %s, %s) RETURNING id
                """, (pid, ver, random.choice(['web', 'ios', 'android', 'backend']), idx == 0, score, st))
                build_ids.append(cur.fetchone()[0])
    conn.commit()

    # 5. Insert Report Templates
    templates_data = [
        ('Executive Quality Digest', 'Executive Summary', 2.8, 'pdf'),
        ('Release Gate Readiness Audit', 'Release Gate Audit', 4.5, 'pdf'),
        ('Daily QA Standup & Defect Log', 'Daily QA Standup', 1.9, 'md'),
        ('Sprint Retrospective Analysis', 'Sprint Retrospective', 3.6, 'xlsx'),
        ('Client Release Sign-Off Report', 'Release Gate Audit', 5.1, 'pdf')
    ]
    
    template_ids = []
    for name, category, compile_time, fmt in templates_data:
        cur.execute("SELECT id FROM report_templates WHERE name = %s", (name,))
        row = cur.fetchone()
        if row:
            template_ids.append(row[0])
        else:
            cur.execute("""
                INSERT INTO report_templates (id, name, category, avg_compile_time_sec, default_format, project_id)
                VALUES (gen_random_uuid(), %s, %s, %s, %s, %s) RETURNING id
            """, (name, category, compile_time, fmt, project_ids[0]))
            template_ids.append(cur.fetchone()[0])
    conn.commit()

    # 6. Ensure report_logs table exists & seed ~350 reports
    cur.execute("""
        CREATE TABLE IF NOT EXISTS report_logs (
            id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            project_id           UUID NOT NULL REFERENCES projects(id),
            build_id             UUID REFERENCES builds(id),
            template_id          UUID NOT NULL REFERENCES report_templates(id),
            title                VARCHAR(250) NOT NULL,
            author_id            UUID NOT NULL REFERENCES users(id),
            output_format        VARCHAR(20) NOT NULL DEFAULT 'pdf',
            compilation_time_sec FLOAT NOT NULL DEFAULT 3.2,
            tokens_used          INTEGER NOT NULL DEFAULT 1200,
            pipeline_stage       VARCHAR(20) NOT NULL DEFAULT 'published',
            created_at           TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
        );
    """)
    conn.commit()

    cur.execute("TRUNCATE TABLE report_logs;")
    conn.commit()

    stages = ['published', 'published', 'published', 'compiled', 'summarized', 'ingested']
    formats = ['pdf', 'pdf', 'xlsx', 'md']
    titles_prefix = ['Executive QA Audit', 'Sprint Status Summary', 'Build Release Gate', 'Client Readiness Brief', 'Daily Defect Telemetry']

    for i in range(1, 380):
        pid = random.choice(project_ids)
        bid = random.choice(build_ids)
        tid = random.choice(template_ids)
        uid = random.choice(user_ids)
        fmt = random.choice(formats)
        stage = random.choice(stages)
        title = f"ReportIQ — {random.choice(titles_prefix)} #{i}"
        ctime = round(random.uniform(1.2, 5.8), 1)
        tokens = random.randint(850, 2400)
        
        # SQL insertion over past 90 days
        cur.execute("""
            INSERT INTO report_logs (
                project_id, build_id, template_id, title, author_id,
                output_format, compilation_time_sec, tokens_used, pipeline_stage, created_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s,
                NOW() - (power(random(), 1.8) * INTERVAL '90 days')
            );
        """, (pid, bid, tid, title, uid, fmt, ctime, tokens, stage))

    conn.commit()

    cur.execute("SELECT COUNT(*) FROM report_logs")
    print(f"Successfully seeded {cur.fetchone()[0]} report_logs in qa_assistant!")
    conn.close()

if __name__ == '__main__':
    seed()

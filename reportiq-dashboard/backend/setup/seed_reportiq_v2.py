"""
seed_reportiq_v2.py
====================
Applies the ReportIQ schema and seeds all data needed by the
Project Reporting & Progress Intelligence dashboard.

Run from the backend folder:
    python setup/seed_reportiq_v2.py
"""
import os, sys, random
from datetime import datetime, timedelta, date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg2
from psycopg2.extras import RealDictCursor

if os.path.exists(".env"):
    with open(".env") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip("'\""))

DSN = os.environ.get("DASHBOARDS_REPLICA_DSN", os.environ.get("DATABASE_URL"))
if not DSN:
    print("Error: DASHBOARDS_REPLICA_DSN (or DATABASE_URL) not set.")
    sys.exit(1)

conn = psycopg2.connect(DSN)
cur  = conn.cursor(cursor_factory=RealDictCursor)

print("=== ReportIQ Schema Migration & Autonomous Seeding ===")

# ── 1. Schema Migrations ──────────────────────────────────────────────────────
print("1. Ensuring all required tables and columns exist...")

cur.execute("""
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

    ALTER TABLE projects ADD COLUMN IF NOT EXISTS progress_pct    INTEGER NOT NULL DEFAULT 0;
    ALTER TABLE projects ADD COLUMN IF NOT EXISTS health_status   VARCHAR(20) NOT NULL DEFAULT 'on_track';
    ALTER TABLE projects ADD COLUMN IF NOT EXISTS delivery_score  INTEGER NOT NULL DEFAULT 0;
    ALTER TABLE projects ADD COLUMN IF NOT EXISTS quality_score   INTEGER NOT NULL DEFAULT 0;
    ALTER TABLE projects ADD COLUMN IF NOT EXISTS testing_score   INTEGER NOT NULL DEFAULT 0;
    ALTER TABLE projects ADD COLUMN IF NOT EXISTS build_score     INTEGER NOT NULL DEFAULT 0;
    ALTER TABLE projects ADD COLUMN IF NOT EXISTS reporting_score INTEGER NOT NULL DEFAULT 0;
    ALTER TABLE projects ADD COLUMN IF NOT EXISTS target_date     DATE;
    ALTER TABLE projects ADD COLUMN IF NOT EXISTS planned_pct     INTEGER NOT NULL DEFAULT 0;

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

    CREATE TABLE IF NOT EXISTS uploaded_files (
        id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        project_id       UUID REFERENCES projects(id),
        filename         VARCHAR(255) NOT NULL,
        file_type        VARCHAR(50) NOT NULL DEFAULT 'document',
        file_size        BIGINT DEFAULT 102400,
        file_size_bytes  BIGINT NOT NULL DEFAULT 102400,
        uploaded_by      UUID REFERENCES users(id),
        created_at       TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
    );
""")
conn.commit()
print("   Schema verified.")

# ── 2. Ensure Base Projects & Users Exist ──────────────────────────────────────
print("2. Ensuring base users and projects exist...")

cur.execute("SELECT COUNT(*) FROM users")
if cur.fetchone()["count"] == 0:
    cur.execute("""
        INSERT INTO users (name, email) VALUES
          ('Sarah Connor',   'sarah.connor@example.com'),
          ('Alex Chen',      'alex.chen@example.com'),
          ('Elena Rostova',  'elena.rostova@example.com'),
          ('David Kim',      'david.kim@example.com'),
          ('Marcus Vance',   'marcus.vance@example.com');
    """)
    conn.commit()

cur.execute("SELECT COUNT(*) FROM projects")
if cur.fetchone()["count"] == 0:
    cur.execute("""
        INSERT INTO projects (name, code, progress_pct, health_status, delivery_score, quality_score, testing_score, build_score, reporting_score, target_date, planned_pct) VALUES
          ('Apollo Core Engine',    'APOLLO', 88, 'on_track', 92, 90, 89, 98, 95, CURRENT_DATE + 45, 85),
          ('Neon Gateway API',      'NEON',   64, 'at_risk',  68, 72, 60, 88, 80, CURRENT_DATE + 90, 80),
          ('Titan ML Platform',     'TITAN',  42, 'delayed',  45, 50, 48, 75, 70, CURRENT_DATE + 105, 65),
          ('Quantum Pay Service',   'QPAY',   92, 'on_track', 95, 96, 94, 100,98, CURRENT_DATE + 30, 90),
          ('Spectra Cloud Ingest',  'SPEC',   78, 'on_track', 82, 85, 80, 94, 91, CURRENT_DATE + 60, 78),
          ('Nexus UI Design System','NEXUS',  84, 'on_track', 88, 91, 87, 96, 94, CURRENT_DATE + 75, 82);
    """)
    conn.commit()

cur.execute("SELECT COUNT(*) FROM report_templates")
if cur.fetchone()["count"] == 0:
    cur.execute("""
        INSERT INTO report_templates (name, category, avg_compile_time_sec, default_format) VALUES
          ('Executive Quality Digest',       'Executive Summary',    2.8, 'pdf'),
          ('Release Gate Readiness Audit',   'Release Gate Audit',   4.5, 'pdf'),
          ('Daily QA Standup & Defect Log',  'Daily QA Standup',     1.9, 'md'),
          ('Sprint Retrospective Analysis',  'Sprint Retrospective', 3.6, 'xlsx'),
          ('Client Release Sign-Off Report', 'Release Gate Audit',   5.1, 'pdf');
    """)
    conn.commit()

cur.execute("SELECT id, name, code FROM projects")
projects = cur.fetchall()

cur.execute("SELECT id FROM users")
user_ids = [r["id"] for r in cur.fetchall()]

cur.execute("SELECT id FROM report_templates")
template_ids = [r["id"] for r in cur.fetchall()]

cur.execute("SELECT COUNT(*) FROM builds")
if cur.fetchone()["count"] == 0:
    for p in projects:
        for tag, status, score, age in [('v2.4.0-rc1', 'PASS', 98, 2), ('v2.4.0-rc2', 'PASS', 100, 1), ('v2.3.9-patch', 'WARN', 82, 5), ('v2.3.8-release', 'PASS', 96, 12)]:
            cur.execute("""
                INSERT INTO builds (project_id, build_tag, version, status, audit_score, created_at)
                VALUES (%s, %s, %s, %s, %s, NOW() - (%s * INTERVAL '1 day'))
            """, (p["id"], tag, tag, status, score, age))
    conn.commit()

cur.execute("SELECT id FROM builds")
build_ids = [r["id"] for r in cur.fetchall()]

print(f"   {len(projects)} projects | {len(user_ids)} users | {len(template_ids)} templates | {len(build_ids)} builds")

# ── 3. Update project health data ────────────────────────────────────────────
print("3. Seeding project health scores & progress...")

today = date.today()
statuses = ["on_track", "on_track", "on_track", "at_risk", "at_risk", "delayed"]

project_configs = []
for p in projects:
    health = random.choice(statuses)
    if health == "on_track":
        actual_pct  = random.randint(72, 95)
        planned_pct = actual_pct - random.randint(-5, 3)
    elif health == "at_risk":
        actual_pct  = random.randint(50, 70)
        planned_pct = actual_pct + random.randint(8, 18)
    else:
        actual_pct  = random.randint(25, 50)
        planned_pct = actual_pct + random.randint(15, 30)

    planned_pct = max(0, min(100, planned_pct))
    delivery_score  = max(0, min(100, actual_pct + random.randint(-8, 8)))
    quality_score   = max(0, min(100, actual_pct + random.randint(-12, 5)))
    testing_score   = max(0, min(100, actual_pct + random.randint(-5, 10)))
    build_score     = random.randint(85, 100) if health != "delayed" else random.randint(60, 85)
    reporting_score = random.randint(80, 100)
    target = today + timedelta(days=random.randint(20, 90))

    cur.execute("""
        UPDATE projects
        SET progress_pct    = %s,
            health_status   = %s,
            delivery_score  = %s,
            quality_score   = %s,
            testing_score   = %s,
            build_score     = %s,
            reporting_score = %s,
            planned_pct     = %s,
            target_date     = %s
        WHERE id = %s
    """, (actual_pct, health, delivery_score, quality_score, testing_score,
          build_score, reporting_score, planned_pct, target, p["id"]))

    project_configs.append({
        "id": p["id"], "name": p["name"], "code": p["code"],
        "actual_pct": actual_pct, "planned_pct": planned_pct, "health": health
    })

conn.commit()
print(f"   Updated {len(projects)} projects.")

# ── 4. Seed Milestones ────────────────────────────────────────────────────────
print("4. Seeding project milestones...")

cur.execute("DELETE FROM project_milestones")

milestone_templates = [
    ("Requirements Complete",  -55, -50),
    ("Design Approved",        -45, -40),
    ("Development Complete",   -30, -20),
    ("QA & Testing",           -10,  15),
    ("UAT Sign-off",            16,  30),
    ("Production Release",      31,  60),
]

for pc in project_configs:
    for i, (name, lo, hi) in enumerate(milestone_templates):
        delta = random.randint(lo, hi)
        mdate = today + timedelta(days=delta)

        if mdate < today and pc["actual_pct"] > (i + 1) * 15:
            status = "completed"
            completed_at = mdate
        elif mdate <= today + timedelta(days=10) and pc["actual_pct"] > i * 12:
            status = "in_progress"
            completed_at = None
        else:
            status = "upcoming"
            completed_at = None

        cur.execute("""
            INSERT INTO project_milestones (project_id, name, status, target_date, completed_at, sort_order)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (pc["id"], name, status, mdate, completed_at, i))

conn.commit()
print(f"   Seeded milestones for {len(project_configs)} projects.")

# ── 5. Seed Timeline Events ───────────────────────────────────────────────────
print("5. Seeding project timeline events...")

cur.execute("DELETE FROM project_timeline_events")

event_catalog = [
    ("sprint_done",   "Sprint 1 Completed",          "First sprint delivered all core features.",             "success"),
    ("sprint_done",   "Sprint 2 Completed",           "All user stories closed. 2 bugs carried forward.",     "success"),
    ("sprint_done",   "Sprint 3 Review Done",         "Minor gaps identified. Planned for next sprint.",      "info"),
    ("build_release", "Build v2.3.9 Released",        "Stable release deployed to staging environment.",      "success"),
    ("build_release", "Build v2.4.0-rc1 Released",    "Release candidate submitted for QA review.",           "info"),
    ("build_release", "Build v2.4.0 Released",        "Production build deployed. All tests pass.",           "success"),
    ("bug_spike",     "Critical Bug Spike Detected",  "3 P1 bugs discovered in the core module.",             "critical"),
    ("bug_spike",     "P1 Bug Resolved",              "Critical bug patched. Regression tests passed.",       "warning"),
    ("bug_spike",     "Integration Blocker Flagged",  "Blocker added: API integration mismatch.",             "warning"),
    ("milestone",     "Testing Phase Started",        "Full regression cycle initiated across platforms.",    "info"),
    ("milestone",     "UAT Kick-off",                 "Client UAT session started with 5 test scenarios.",    "info"),
    ("custom",        "Executive Demo Delivered",     "Stakeholder demo delivered. Feedback positive.",       "success"),
    ("custom",        "Team Progress Review",         "Progress confirmed. On track for target release.",     "info"),
]

for pc in project_configs:
    selected = random.sample(event_catalog, random.randint(5, 8))
    day_offset = -58
    for etype, title, description, severity in selected:
        day_offset += random.randint(6, 12)
        edate = min(today, today + timedelta(days=day_offset))
        cur.execute("""
            INSERT INTO project_timeline_events (project_id, event_type, title, description, event_date, severity)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (pc["id"], etype, title, description, edate, severity))

conn.commit()
print("   Seeded timeline events.")

# ── 6. Seed Progress History ─────────────────────────────────────────────────
print("6. Seeding progress history (planned vs actual 60-day velocity)...")

cur.execute("DELETE FROM project_progress_history")

for pc in project_configs:
    for day in range(61):
        d = today - timedelta(days=60 - day)
        frac = day / 60
        planned = max(0, min(100, int(frac * pc["planned_pct"]) + random.randint(-2, 2)))
        actual  = max(0, min(100, int(frac * pc["actual_pct"])  + random.randint(-3, 3)))
        if pc["health"] in ("at_risk", "delayed") and frac > 0.4:
            actual = max(0, actual - random.randint(3, 8))

        cur.execute("""
            INSERT INTO project_progress_history (project_id, recorded_date, planned_pct, actual_pct)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (project_id, recorded_date) DO UPDATE
              SET planned_pct = EXCLUDED.planned_pct,
                  actual_pct  = EXCLUDED.actual_pct
        """, (pc["id"], d, planned, actual))

conn.commit()
print(f"   Seeded 61 days x {len(project_configs)} projects.")

# ── 7. Seed Risks ────────────────────────────────────────────────────────────
print("7. Seeding project risks & blockers...")

cur.execute("DELETE FROM project_risks")

risk_catalog = [
    ("bug",          "critical", "Critical bug still open",              "Unresolved P1 bug affecting core workflow. Escalation pending."),
    ("task_overdue", "warning",  "Tasks are overdue this sprint",        "Sprint tasks past deadline. Delivery impact expected if unresolved."),
    ("progress_gap", "warning",  "Progress lagging planned schedule",    "Actual progress is lagging planned velocity for 3+ days."),
    ("milestone",    "notice",   "UAT deadline approaching",             "UAT sign-off deadline is approaching. Preparation required."),
    ("bug",          "warning",  "P2 bugs pending QA triage",            "Medium-severity bugs require QA triage before UAT can proceed."),
    ("custom",       "notice",   "DSR reporting gap this week",          "Team has not submitted daily status on 2 days this week."),
]

for pc in project_configs:
    count = random.randint(2, 4) if pc["health"] != "on_track" else random.randint(0, 2)
    chosen = random.sample(risk_catalog, min(count, len(risk_catalog)))
    for risk_type, severity, title, detail in chosen:
        cur.execute("""
            INSERT INTO project_risks (project_id, risk_type, severity, title, detail, is_active)
            VALUES (%s, %s, %s, %s, %s, TRUE)
        """, (pc["id"], risk_type, severity, title, detail))

conn.commit()
print("   Seeded risks for all projects.")

# ── 8. Seed/Update Report Logs ───────────────────────────────────────────────
print("8. Seeding report logs with DSR/WSR types...")

cur.execute("SELECT COUNT(*) FROM report_logs")
if cur.fetchone()["count"] < 100:
    for i in range(250):
        p = random.choice(project_configs)
        t = random.choice(template_ids)
        u = random.choice(user_ids)
        b = random.choice(build_ids) if build_ids else None
        fmt = random.choice(["pdf", "xlsx", "md"])
        rtype = "DSR" if random.random() < 0.75 else "WSR"
        stage = random.choice(["published", "published", "published", "compiled", "summarized"])
        days_ago = random.randint(0, 60)
        tokens = random.randint(800, 2800)
        latency = round(random.uniform(1.2, 5.0), 1)

        cur.execute("""
            INSERT INTO report_logs (
                project_id, build_id, template_id, title, author_id,
                output_format, report_type, compilation_time_sec, tokens_used, pipeline_stage, created_at
            ) VALUES (
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, NOW() - (%s * INTERVAL '1 day')
            )
        """, (
            p["id"], b, t, f"ReportIQ {rtype} — Sprint Review #{i+1}", u,
            fmt, rtype, latency, tokens, stage, days_ago
        ))
    conn.commit()
else:
    cur.execute("""
        UPDATE report_logs
        SET report_type = CASE WHEN random() < 0.75 THEN 'DSR' ELSE 'WSR' END
        WHERE report_type IS NULL OR report_type = ''
    """)
    conn.commit()

# ── 9. Seed Uploaded Files ──────────────────────────────────────────────────
print("9. Seeding uploaded technical specifications & files...")

cur.execute("DELETE FROM uploaded_files")

sample_files = [
    ("Architecture_Specification_v2.pdf", "pdf", 2450000),
    ("API_Contract_Spec.json", "json", 340000),
    ("Sprint_Execution_Plan.xlsx", "xlsx", 890000),
    ("QA_Test_Execution_Matrix.xlsx", "xlsx", 1200000),
    ("Security_PenTest_Audit_Report.pdf", "pdf", 4500000),
    ("User_Story_Acceptance_Criteria.docx", "docx", 670000),
    ("Database_Migration_Plan.sql", "sql", 120000),
    ("Release_Gate_Readiness_Checklist.pdf", "pdf", 950000),
]

for pc in project_configs:
    for filename, ftype, fsize in sample_files:
        if random.random() < 0.8:
            delta_days = random.randint(2, 60)
            uid = random.choice(user_ids) if user_ids else None
            cur.execute("""
                INSERT INTO uploaded_files (id, project_id, filename, file_type, file_size, file_size_bytes, uploaded_by, created_at)
                VALUES (gen_random_uuid(), %s, %s, %s, %s, %s, %s, NOW() - (%s * INTERVAL '1 day'))
            """, (pc["id"], filename, ftype, fsize, fsize + random.randint(-50000, 50000), uid, delta_days))

conn.commit()
print("   Seeded uploaded_files.")

# ── Final summary ─────────────────────────────────────────────────────────────
print("\n=== Verification ===")
for table in ["projects", "users", "report_templates", "builds", "report_logs", "project_milestones", "project_timeline_events", "project_progress_history", "project_risks", "uploaded_files"]:
    cur.execute(f"SELECT COUNT(*) FROM {table}")
    print(f"   {table}: {cur.fetchone()['count']} rows")

conn.close()
print("\n[OK] ReportIQ autonomous seeding complete!")

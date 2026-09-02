import csv
import json
import psycopg2
from psycopg2.extras import Json
import os
import random
import uuid

# Connection string
db_url = os.getenv("DATABASE_URL", "dbname=dashboards user=postgres password=postgres host=localhost")

# File to import
CSV_FILE = "a:\\vs _codes\\coe\\dash_board\\dashboards-app\\Copy of The Fertile Crescent - 2025(Bug Tracker).csv"
PROJECT_NAME = "The Fertile Crescent"

FEATURES = [
    "Save / Load",
    "Combat",
    "Inventory",
    "Localization",
    "UI",
    "Multiplayer",
    "Graphics"
]

def map_severity(raw_sev):
    raw = raw_sev.lower().strip()
    if "block" in raw or "critical" in raw: return "P1"
    if "major" in raw or "high" in raw: return "P2"
    if "minor" in raw or "med" in raw: return "P3"
    if "trivial" in raw or "low" in raw: return "P4"
    return "P3"

def map_status(raw_status):
    raw = raw_status.lower().strip()
    if "close" in raw or "resolve" in raw or "done" in raw: return "closed"
    if "progress" in raw or "fixing" in raw: return "in_progress"
    return "open"

def run_import():
    conn = psycopg2.connect(db_url)
    cur = conn.cursor()

    # 1. Get or create project in bug_projects
    cur.execute("SELECT id FROM bug_projects WHERE name = %s", (PROJECT_NAME,))
    row = cur.fetchone()
    if not row:
        project_id = str(uuid.uuid4())
        cur.execute("INSERT INTO bug_projects (id, name, code) VALUES (%s, %s, %s)", (project_id, PROJECT_NAME, "TFC"))
    else:
        project_id = row[0]

    # 1.5 Get or create a dummy user
    cur.execute("SELECT id FROM users LIMIT 1")
    row = cur.fetchone()
    if not row:
        raise Exception("No users found in DB. Run seed scripts first.")
    user_id = row[0]

    # 2. Delete existing bugs for this project to start fresh
    cur.execute("DELETE FROM bug_reports WHERE project_id = %s", (project_id,))
    print(f"Cleared existing bugs for {PROJECT_NAME}")

    # 3. Import from CSV
    count = 0
    with open(CSV_FILE, encoding='utf-8', errors='replace') as f:
        reader = csv.DictReader(f)
        for row in reader:
            issue_no = row.get("Issue No") or row.get("Issue #")
            if not issue_no:
                continue

            title = row.get("Summary", "Unknown Title")
            desc = row.get("Description", "")
            raw_sev = row.get("Severity", "Minor")
            raw_status = row.get("Status", "Open")
            
            # Use deterministic assignment of feature based on issue_no to keep it consistent
            feature_idx = sum(ord(c) for c in issue_no) % len(FEATURES)
            feature = FEATURES[feature_idx]
            
            # Map values
            severity = map_severity(raw_sev)
            status = map_status(raw_status)
            
            dynamic_fields = {
                "issue_no": issue_no,
                "feature": feature,
                "repro_rate": row.get("Repro Rate", ""),
                "issue_type": row.get("Issue Type", ""),
                "build": row.get("Build & Version", ""),
                "steps": row.get("Steps", "")
            }

            bug_id = str(uuid.uuid4())
            cur.execute("""
                INSERT INTO bug_reports (
                    id, project_id, reported_by, title, summary, severity, status, dynamic_fields
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                bug_id,
                project_id,
                user_id,
                title,
                desc,
                severity,
                status,
                Json(dynamic_fields)
            ))
            count += 1

    conn.commit()
    print(f"Successfully imported {count} bugs for {PROJECT_NAME} into Postgres.")
    cur.close()
    conn.close()

if __name__ == "__main__":
    run_import()

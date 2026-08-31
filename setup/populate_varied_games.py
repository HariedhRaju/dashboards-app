"""
Seed script to populate PostgreSQL with a rich variety of game datasets using the actual Excel bug data.
"""
import os
import csv
import json
import uuid
from datetime import datetime, timezone

from dashboards import write_cursor

# 7 Varied Game Projects
GAME_PROJECTS = [
    {"name": "The Fertile Crescent", "code": "TFC", "category": "Chapter Strategy"},
    {"name": "Chariots of Destiny", "code": "COD", "category": "Historical Campaign"},
    {"name": "Candy Crush Saga", "code": "CCS", "category": "Level Match-3 Puzzle"},
    {"name": "Royal Match", "code": "RM", "category": "Level Puzzle Castle"},
    {"name": "PUBG Mobile", "code": "PUBG", "category": "Open World Battle Royale"},
    {"name": "CyberStrike 2099", "code": "CS2099", "category": "Open World Cyberpunk"},
    {"name": "Mythic Realms Online", "code": "MRO", "category": "Fantasy MMORPG"},
]

CSV_PATH = "Copy of The Fertile Crescent - 2025(Bug Tracker).csv"

def parse_csv_date(raw_date: str, idx: int = 0) -> datetime:
    now = datetime.now(timezone.utc)
    # Distribute bugs across the last 20 days so all standard date range filters (30d, 90d, YTD) include them
    days_ago = (idx % 20)
    hours_ago = (idx * 3) % 24
    from datetime import timedelta
    return now - timedelta(days=days_ago, hours=hours_ago)

def populate():
    if not os.path.exists(CSV_PATH):
        print(f"CSV file not found: {CSV_PATH}")
        return

    with open(CSV_PATH, encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f)
        rows = [r for r in reader if any(r.values())]

    print(f"Read {len(rows)} raw rows from CSV.")

    with write_cursor() as cur:
        # 1. Ensure projects exist
        project_ids = {}
        for p in GAME_PROJECTS:
            cur.execute("SELECT id FROM projects WHERE name = %s LIMIT 1;", (p["name"],))
            res = cur.fetchone()
            if res:
                pid = res["id"]
            else:
                pid = str(uuid.uuid4())
                cur.execute("""
                    INSERT INTO projects (id, name, code, created_by)
                    VALUES (%s, %s, %s, %s);
                """, (pid, p["name"], p["code"], "00000000-0000-0000-0000-000000000001"))
            project_ids[p["name"]] = str(pid)

        print(f"Created/Verified {len(project_ids)} game projects in PostgreSQL.")

        # Delete old mock reports to keep clean dataset
        cur.execute("DELETE FROM bug_reports;")
        print("Cleared previous bug_reports table.")

        # 2. Insert records from CSV for all games
        inserted_count = 0
        game_names = list(project_ids.keys())

        for idx, row in enumerate(rows):
            raw_issue_no = str(row.get("Issue No", "")).strip()
            if not raw_issue_no or raw_issue_no.startswith(","):
                continue

            clean_issue_no = raw_issue_no.strip("#").strip()
            formatted_issue_no = f"{clean_issue_no}#" if not raw_issue_no.endswith("#") else raw_issue_no

            summary = str(row.get("Summary", "")).strip() or "Untitled Bug"
            description = str(row.get("Description", "")).strip() or summary
            steps = str(row.get("Steps", "")).strip()
            actual_res = str(row.get("Actual Result", "")).strip()
            expected_res = str(row.get("Expected Result", "")).strip()
            repro_rate = str(row.get("Repro Rate", "")).strip() or "5/5"
            build_ver = str(row.get("Build & Version", "")).strip() or "v13000"
            issue_type = str(row.get("Issue Type", "")).strip() or "Functionality"
            raw_sev = str(row.get("Severity", "")).strip() or "Minor"
            raw_status = str(row.get("Status", "")).strip() or "Open"
            resolution = str(row.get("Resolution", "")).strip()
            dev_res = str(row.get("Dev Resolution", "")).strip()
            dev_comments = str(row.get("Dev Comments", "")).strip()
            created_dt = parse_csv_date(row.get("Created", ""), idx)

            # Map canonical severity & status
            sev_lower = raw_sev.lower()
            if "blocker" in sev_lower or "critical" in sev_lower or "p1" in sev_lower:
                canonical_sev = "P1"
            elif "major" in sev_lower or "high" in sev_lower or "p2" in sev_lower:
                canonical_sev = "P2"
            elif "minor" in sev_lower or "medium" in sev_lower or "p3" in sev_lower:
                canonical_sev = "P3"
            else:
                canonical_sev = "P4"

            stat_lower = raw_status.lower()
            if "closed" in stat_lower or "resolved" in stat_lower:
                canonical_stat = "closed"
            elif "qa ready" in stat_lower or "fixed" in stat_lower:
                canonical_stat = "fixed"
            elif "progress" in stat_lower or "working" in stat_lower:
                canonical_stat = "in_progress"
            else:
                canonical_stat = "open"

            # Primary game assignment
            primary_game = game_names[idx % len(game_names)]
            primary_pid = project_ids[primary_game]

            dynamic_json = {
                "issue_no": formatted_issue_no,
                "raw_issue_no": raw_issue_no,
                "clean_issue_no": clean_issue_no,
                "source_record_id": formatted_issue_no,
                "source": "excel",
                "game_name": primary_game,
                "created_raw": row.get("Created", ""),
                "repro_rate": repro_rate,
                "severity_raw": raw_sev,
                "issue_type": issue_type,
                "summary": summary,
                "description": description,
                "steps": steps,
                "actual_result": actual_res,
                "expected_result": expected_res,
                "build_version": build_ver,
                "resolution": resolution,
                "dev_resolution": dev_res,
                "dev_comments": dev_comments,
                "status_raw": raw_status,
            }

            cur.execute("""
                INSERT INTO bug_reports (
                    id, project_id, reported_by, title, summary, severity, status, dynamic_fields, created_at, updated_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW()
                );
            """, (
                str(uuid.uuid4()),
                primary_pid,
                "00000000-0000-0000-0000-000000000001",
                summary[:300],
                description,
                canonical_sev,
                canonical_stat,
                json.dumps(dynamic_json),
                created_dt
            ))
            inserted_count += 1

            # Duplicate select critical/major bugs across a second game to simulate cross-game occurrence!
            if idx in (0, 2, 10, 11, 20, 30, 50, 60):
                secondary_game = game_names[(idx + 3) % len(game_names)]
                secondary_pid = project_ids[secondary_game]
                sec_json = dict(dynamic_json)
                sec_json["game_name"] = secondary_game

                cur.execute("""
                    INSERT INTO bug_reports (
                        id, project_id, reported_by, title, summary, severity, status, dynamic_fields, created_at, updated_at
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW()
                    );
                """, (
                    str(uuid.uuid4()),
                    secondary_pid,
                    "00000000-0000-0000-0000-000000000001",
                    summary[:300],
                    description,
                    canonical_sev,
                    canonical_stat,
                    json.dumps(sec_json),
                    created_dt
                ))
                inserted_count += 1

        print(f"Successfully inserted {inserted_count} bug records into PostgreSQL across {len(game_names)} games!")

if __name__ == "__main__":
    populate()

import sys, os
sys.path.insert(0, os.path.abspath("."))
from dashboards import replica_cursor

project_id = '0bb04287-5aa2-4ce1-9c24-0829e0d2f79c'

with replica_cursor() as cur:
    cur.execute("""
        SELECT 
            id,
            COALESCE(dynamic_fields->>'issue_no', dynamic_fields->>'source_record_id', left(id::text, 8)) as issue_no,
            title,
            severity,
            status,
            COALESCE(dynamic_fields->>'feature', 'Uncategorized') as feature,
            dynamic_fields
        FROM bug_reports
        WHERE project_id = %s
    """, (project_id,))
    all_bugs = cur.fetchall()

def extract_occurrences(dynamic_fields):
    if not dynamic_fields:
        return 1
    if "occurrences" in dynamic_fields:
        try:
            return int(dynamic_fields["occurrences"])
        except (ValueError, TypeError):
            pass
    if "repro_rate" in dynamic_fields:
        repro = str(dynamic_fields["repro_rate"])
        if "/" in repro:
            try:
                val = int(repro.split("/")[0].strip())
                if val > 0:
                    return val
            except (ValueError, TypeError):
                pass
    return 1

SEV_SCORE = {"P1": 4, "P2": 3, "P3": 2, "P4": 1, "BLOCKER": 4, "CRITICAL": 4, "MAJOR": 3, "MINOR": 2, "TRIVIAL": 1}
STATUS_SCORE = {"open": 3, "in_progress": 2, "fixed": 1, "closed": 0, "qa_ready": 2}

candidates = []
for b in all_bugs:
    df = b.get("dynamic_fields") or {}
    occ = extract_occurrences(df)
    sev = (b.get("severity") or "P3").upper()
    stat = (b.get("status") or "open").lower()
    
    s_score = SEV_SCORE.get(sev, 1)
    stat_score = STATUS_SCORE.get(stat, 1)
    
    priority_tuple = (
        1 if (s_score >= 4 and stat_score >= 2) else 0,
        s_score,
        stat_score,
        occ
    )
    
    raw_issue = str(b.get("issue_no") or "")
    clean_issue = raw_issue.replace("#", "")
    if clean_issue.isdigit():
        formatted_issue = f"BUG-{clean_issue}"
    elif raw_issue.startswith("#"):
        formatted_issue = f"BUG-{raw_issue[1:]}"
    elif raw_issue.startswith("BUG-"):
        formatted_issue = raw_issue
    else:
        formatted_issue = f"BUG-{raw_issue}" if raw_issue else "BUG"

    status_display = stat.replace("_", " ").title()

    candidates.append({
        "issue_no": formatted_issue,
        "title": b.get("title", "Untitled Bug"),
        "feature": b.get("feature", "Uncategorized"),
        "severity": sev,
        "status": status_display,
        "occurrences": occ,
        "_sort_key": priority_tuple
    })

candidates.sort(key=lambda x: x["_sort_key"], reverse=True)
top_priority_bugs = [dict(c) for c in candidates[:7]]
for t in top_priority_bugs:
    t.pop("_sort_key", None)
    print(t)

import sys, os
sys.path.insert(0, os.path.abspath("."))
import json
from dashboards import replica_cursor
from dashboards.llm_client import call_llm_json

project_id = '0bb04287-5aa2-4ce1-9c24-0829e0d2f79c'

with replica_cursor() as cur:
    cur.execute("""
        SELECT 
            project_id,
            COUNT(*) as total_bugs,
            COUNT(*) FILTER (WHERE status = 'open') as open_bugs,
            COUNT(*) FILTER (WHERE status = 'in_progress') as in_progress_bugs,
            COUNT(*) FILTER (WHERE status = 'closed' OR status = 'fixed') as closed_bugs,
            COUNT(*) FILTER (WHERE severity = 'P1') as critical_bugs,
            COUNT(*) FILTER (WHERE severity = 'P2') as high_bugs,
            COUNT(*) FILTER (WHERE severity = 'P3') as medium_bugs,
            COUNT(*) FILTER (WHERE severity = 'P4') as low_bugs
        FROM bug_reports
        WHERE project_id = %s
        GROUP BY project_id
    """, (project_id,))
    game_stats = dict(cur.fetchone())

    cur.execute("SELECT name FROM projects WHERE id = %s", (project_id,))
    proj_row = cur.fetchone()
    proj_name = proj_row['name'] if proj_row else "Unknown"

    cur.execute("""
        SELECT 
            COALESCE(dynamic_fields->>'feature', 'Uncategorized') as name,
            COUNT(*) as total_bugs,
            COUNT(*) FILTER (WHERE status = 'open') as open_bugs,
            COUNT(*) FILTER (WHERE status = 'in_progress') as in_progress_bugs,
            COUNT(*) FILTER (WHERE status = 'closed' OR status = 'fixed') as closed_bugs,
            COUNT(*) FILTER (WHERE severity = 'P1') as critical_bugs,
            COUNT(*) FILTER (WHERE severity = 'P2') as high_bugs,
            COUNT(*) FILTER (WHERE severity = 'P3') as medium_bugs,
            COUNT(*) FILTER (WHERE severity = 'P4') as low_bugs
        FROM bug_reports
        WHERE project_id = %s
        GROUP BY name
        ORDER BY total_bugs DESC
    """, (project_id,))
    feature_stats = [dict(r) for r in cur.fetchall()]

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

def calc_risk(stats):
    score = 0
    score += stats['critical_bugs'] * 2.0
    score += stats['high_bugs'] * 1.0
    score += stats['open_bugs'] * 0.5
    score = min(10.0, score)
    
    status = "SAFE"
    if score > 7.5 or stats['critical_bugs'] > 0: status = "CRITICAL"
    elif score > 5.0 or stats['high_bugs'] > 0: status = "HIGH"
    elif score > 2.5: status = "MEDIUM"
    
    return {"risk_score": round(score, 1), "health_status": status, "confidence_score": 92}

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

SEV_SCORE = {"P1": 4, "P2": 3, "P3": 2, "P4": 1}
STATUS_SCORE = {"open": 3, "in_progress": 2, "fixed": 1, "closed": 0}

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
top_priority_bugs = []
for c in candidates[:6]:
    item = dict(c)
    item.pop("_sort_key", None)
    top_priority_bugs.append(item)

game_metrics = calc_risk(game_stats)
game_stats.update(game_metrics)
game_stats['name'] = proj_name

features = []
for f in feature_stats:
    f_metrics = calc_risk(f)
    feat = dict(f)
    feat.update(f_metrics)
    features.append(feat)

compact_payload = {
    "game": proj_name,
    "overall": {
        "total_bugs": game_stats["total_bugs"],
        "open_bugs": game_stats["open_bugs"],
        "in_progress_bugs": game_stats["in_progress_bugs"],
        "closed_bugs": game_stats["closed_bugs"],
        "critical_bugs": game_stats["critical_bugs"],
        "high_bugs": game_stats["high_bugs"],
        "medium_bugs": game_stats["medium_bugs"],
        "low_bugs": game_stats["low_bugs"],
        "risk_score": game_stats["risk_score"],
        "confidence_score": game_stats["confidence_score"],
        "health_status": game_stats["health_status"]
    },
    "features": [
        {
            "name": f["name"],
            "total_bugs": f["total_bugs"],
            "open_bugs": f["open_bugs"],
            "critical_bugs": f["critical_bugs"],
            "high_bugs": f["high_bugs"],
            "risk_score": f["risk_score"],
            "confidence_score": f["confidence_score"],
            "health_status": f["health_status"]
        }
        for f in features[:5]
    ],
    "top_priority_bugs": top_priority_bugs
}

print("PAYLOAD TO SEND:")
print(json.dumps(compact_payload, indent=2))

system_prompt = """You are Bugsy, a Gaming QA intelligence assistant.

You are generating an overall QA health report for one game.

The backend has already calculated all metrics and risk scores.
Treat those values as authoritative facts.

Your job is to interpret those facts and create a detailed,
tester-friendly summary.

The report must help a tester quickly understand:

- Overall game health
- Overall risk
- Number and state of bugs
- Critical and high-severity defect concentration
- Highest-risk features
- Most important critical/high-priority bugs
- Recurring issues when occurrence data is available
- QA areas that should receive priority

The supplied top_priority_bugs list contains the most important
bugs selected by the backend. You MUST consider these bugs in
the report and mention the most important ones by issue number
and title.

Do not invent bugs.

Do not invent root causes.

Do not invent numerical values.

Do not modify risk scores.

Do not modify confidence scores.

Do not calculate metrics yourself.

Do not claim information that is not present in the supplied data.

Do not analyze the entire bug dataset because only the most
important bugs are supplied.

When several critical bugs belong to the same feature, identify
that feature as a major QA risk area.

When a bug has a high occurrence count, mention that recurrence
when it is relevant.

Prioritize unresolved critical and high-severity defects.

The report must contain exactly these sections:

OVERALL ASSESSMENT
KEY RISK AREAS
CRITICAL BUGS
FEATURE HEALTH
QA PRIORITIES

Use concise paragraphs and bullet points.

Make the report detailed enough that a tester can understand
the game's current QA situation without opening every feature.

Keep the report approximately 250–450 words when the supplied
data supports that level of detail.

Do not add unnecessary introductory text.

Do not add a conclusion section.

Return only the report."""

prompt = f"""Generate the overall QA health report for the following game data:
{json.dumps(compact_payload, indent=2)}

Return ONLY a JSON object in this format:
{{
  "summary": "OVERALL ASSESSMENT\\n...\\n\\nKEY RISK AREAS\\n...\\n\\nCRITICAL BUGS\\n...\\n\\nFEATURE HEALTH\\n...\\n\\nQA PRIORITIES\\n..."
}}
"""

res = call_llm_json(prompt=prompt, system_prompt=system_prompt)
print("\n" + "="*50)
print("SUMMARY RECEIVED:")
print(res.get("summary", res))
print("="*50)

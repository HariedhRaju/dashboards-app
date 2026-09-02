import sys, os
sys.path.insert(0, os.path.abspath("."))
import json
from dashboards.llm_client import call_llm_json

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

payload = {
    "game": "The Fertile Crescent",
    "overall": {
        "total_bugs": 61,
        "open_bugs": 37,
        "in_progress_bugs": 8,
        "closed_bugs": 16,
        "critical_bugs": 7,
        "high_bugs": 14,
        "medium_bugs": 25,
        "low_bugs": 15,
        "risk_score": 8.3,
        "confidence_score": 94,
        "health_status": "HIGH"
    },
    "features": [
        {
            "name": "Save / Load",
            "total_bugs": 15,
            "open_bugs": 10,
            "critical_bugs": 4,
            "high_bugs": 5,
            "risk_score": 9.2,
            "confidence_score": 91,
            "health_status": "CRITICAL"
        },
        {
            "name": "Combat",
            "total_bugs": 14,
            "open_bugs": 9,
            "critical_bugs": 2,
            "high_bugs": 4,
            "risk_score": 8.1,
            "confidence_score": 93,
            "health_status": "HIGH"
        },
        {
            "name": "Inventory",
            "total_bugs": 12,
            "open_bugs": 8,
            "critical_bugs": 1,
            "high_bugs": 3,
            "risk_score": 6.5,
            "confidence_score": 90,
            "health_status": "MEDIUM"
        },
        {
            "name": "Localization",
            "total_bugs": 2,
            "open_bugs": 0,
            "critical_bugs": 0,
            "high_bugs": 0,
            "risk_score": 2.1,
            "confidence_score": 95,
            "health_status": "SAFE"
        }
    ],
    "top_priority_bugs": [
        {
            "issue_no": "BUG-12",
            "title": "Game crashes when loading saved settlement",
            "feature": "Save / Load",
            "severity": "P1",
            "status": "Open",
            "occurrences": 4
        },
        {
            "issue_no": "BUG-18",
            "title": "Units disappear after loading",
            "feature": "Save / Load",
            "severity": "P1",
            "status": "Open",
            "occurrences": 3
        },
        {
            "issue_no": "BUG-24",
            "title": "Combat freezes during enemy attack",
            "feature": "Combat",
            "severity": "P2",
            "status": "Open",
            "occurrences": 5
        }
    ]
}

prompt = f"""Generate the detailed overall QA health report for the following game data.
Return a JSON object with the format:
{{
  "summary": "OVERALL ASSESSMENT\\n...\\n\\nKEY RISK AREAS\\n...\\n\\nCRITICAL BUGS\\n...\\n\\nFEATURE HEALTH\\n...\\n\\nQA PRIORITIES\\n..."
}}

DATA:
{json.dumps(payload, indent=2)}
"""

res = call_llm_json(prompt=prompt, system_prompt=system_prompt)
print("\n" + "="*50)
print("RESULT:")
print(res.get("summary", res))
print("="*50)

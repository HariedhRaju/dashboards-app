"""
Common Analytics Agent — LLM interpretation layer.

generate_insights() receives ONLY the already-computed dashboard dict from
core.build_common_dashboard(). It never queries the database, never touches
an adapter, and never recomputes a metric — it interprets numbers, it does
not produce them. Reuses this repository's existing dashboards.llm_client
chokepoint (call_llm_json); no new LLM client is introduced, and nothing
here imports from the sibling QA---AI---Assistant repository.
"""
from __future__ import annotations

import json
from typing import Any

from dashboards.llm_client import call_llm_json, check_ollama_status, OllamaUnavailableError

_SYSTEM_PROMPT = (
    "You are the Common Analytics Agent's insight layer for a QA analytics platform.\n"
    "You interpret ALREADY-COMPUTED analytics about bugs (Bugsy) and test cases (TestSmith).\n\n"
    "STRICT CONSTRAINTS:\n"
    "1. Use ONLY the supplied JSON. Never invent metrics, bugs, test cases, mappings, "
    "percentages, or trends not present in the data.\n"
    "2. 'unavailable_metrics' lists information that does not exist in this system — "
    "never estimate a value for it.\n"
    "3. 'module_analytics' is grouping only (module/feature name overlap) — it is NEVER "
    "proof of a real bug-to-test-case relationship.\n"
    "4. Only 'record_level_mapping' and 'coverage_gaps' reflect real, explicit, persisted "
    "relationships — everything else is descriptive juxtaposition.\n"
    "5. If 'project_summary' is present, lead with it — it is a single-project combined "
    "summary of Bugsy's bugs and TestSmith's test cases. Its 'coverage_confidence_pct' "
    "(when present) is a REAL, COMPUTED percentage — mapped bugs divided by total bugs for "
    "this project — never rephrase it as a subjective risk, health, or quality score, and "
    "never invent one if it's absent. 'testsmith.total_test_cases_all_projects' is NOT "
    "scoped to this project (TestSmith has no project field) — say so if you mention it; "
    "only 'testsmith.test_cases_linked_to_this_project' is a real, project-scoped number.\n"
    "6. If the data is insufficient to support a claim, say so explicitly instead of guessing.\n"
    "7. Respond strictly in valid JSON matching the specified schema."
)

_RESPONSE_TEMPLATE = """{
  "status": "ok",
  "summary": "Plain-language summary of the current bug/test-case relationship state",
  "observations": ["Grounded observation 1", "Grounded observation 2"],
  "cautions": ["Explicit caveat about a gap or unavailable metric, if any"]
}"""


def generate_insights(dashboard: dict[str, Any]) -> dict[str, Any]:
    """
    Interpret an already-computed Common Agent dashboard dict via the LLM.

    Raises OllamaUnavailableError / OllamaModelError (from dashboards.llm_client)
    on connectivity/model failures, exactly like the existing Bugsy insight
    agent's error contract, so the route can map them to the same 503/422
    responses. A successfully-parsed but malformed-shape LLM response is
    handled defensively here and returns status: "error" rather than raising.
    """
    is_ready, status_msg = check_ollama_status()
    if not is_ready:
        raise OllamaUnavailableError(f"Common Agent insight AI is currently unavailable. {status_msg}")

    user_prompt = f"""Interpret the following Common Analytics Agent dashboard data.

DASHBOARD DATA:
{json.dumps(dashboard, indent=2, default=str)}

REQUIRED JSON RESPONSE STRUCTURE:
{_RESPONSE_TEMPLATE}

Generate the JSON response now:"""

    raw = call_llm_json(prompt=user_prompt, system_prompt=_SYSTEM_PROMPT, temperature=0.1)

    if not isinstance(raw, dict) or "status" not in raw:
        return {
            "status": "error",
            "summary": None,
            "observations": [],
            "cautions": ["Model response did not match the expected shape."],
        }

    observations = raw.get("observations")
    cautions = raw.get("cautions")
    return {
        "status": raw.get("status", "ok"),
        "summary": raw.get("summary"),
        "observations": observations if isinstance(observations, list) else [],
        "cautions": cautions if isinstance(cautions, list) else [],
    }

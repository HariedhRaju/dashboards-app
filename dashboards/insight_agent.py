"""
Agent-Driven Data Insights & Deep Analysis Engine (Step 2.4).

Receives Step 2.1 Data Profile, Step 2.2 Dashboard Plan, aggregated metric data,
and active drilldown/filter context. Pre-calculates deterministic statistical signals
and uses Qwen (qwen2.5:7b-instruct) to generate data-grounded insights, anomaly alerts,
visualization explanations, bug-level investigation analysis, and actionable recommendations.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field, ValidationError

from .data_profiler import PROTECTED_IDENTIFIER_KEYS, _is_protected_identifier
from .llm_client import call_llm_json, check_ollama_status, OllamaUnavailableError, OllamaModelError
from . import replica_cursor

# In-memory insights cache: sha256_hash -> result_dict
_INSIGHTS_CACHE: Dict[str, Dict[str, Any]] = {}


# ══════════════════════════════════════════════════════════════════════════
#  RECORD-LEVEL BUG RETRIEVAL HELPER
# ══════════════════════════════════════════════════════════════════════════

def get_bug_details(issue_no: str, project_id: str | None = None) -> Dict[str, Any]:
    """
    Safely retrieve bug records matching issue_no (or source_record_id) using parameterized SQL.
    Supports multi-project occurrence analysis if the same issue number appears across multiple games.
    """
    clean_issue = str(issue_no).strip()
    if not clean_issue:
        return {"found": False, "occurrences_count": 0, "records": []}

    alt_issue = f"{clean_issue}#" if not clean_issue.endswith("#") else clean_issue
    raw_num = clean_issue.strip("#").strip()

    with replica_cursor() as cur:
        where_conds = [
            "(dynamic_fields->>'source_record_id' = %s OR dynamic_fields->>'issue_no' = %s OR dynamic_fields->>'clean_issue_no' = %s OR dynamic_fields->>'source_record_id' = %s OR b.title ILIKE %s)"
        ]
        params: List[Any] = [clean_issue, clean_issue, raw_num, alt_issue, f"%{clean_issue}%"]

        if project_id and str(project_id).strip():
            where_conds.append("b.project_id = %s")
            params.append(str(project_id).strip())

        where_clause = "WHERE " + " AND ".join(where_conds)

        sql = f"""
            SELECT 
                b.id::text AS bug_id,
                b.project_id::text AS project_id,
                p.name AS project_name,
                p.code AS project_code,
                b.reported_by::text AS reporter_id,
                u.name AS reporter_name,
                b.title,
                b.summary,
                b.severity,
                b.status,
                b.created_at,
                b.updated_at,
                b.dynamic_fields
            FROM bug_reports b
            LEFT JOIN bug_projects p ON p.id = b.project_id
            LEFT JOIN bug_users u ON u.id = b.reported_by
            {where_clause}
            ORDER BY b.created_at DESC
            LIMIT 50;
        """
        cur.execute(sql, params)
        rows = [dict(r) for r in cur.fetchall()]

        if not rows:
            return {"found": False, "occurrences_count": 0, "records": [], "issue_no": clean_issue}

        # Multi-project occurrence statistics
        affected_projects = list(set(r["project_name"] for r in rows if r.get("project_name")))
        primary_record = rows[0]

        # Extract dynamic fields from primary record
        df = primary_record.get("dynamic_fields") or {}

        return {
            "found": True,
            "issue_no": clean_issue,
            "occurrences_count": len(rows),
            "affected_projects": affected_projects,
            "primary_bug": {
                "bug_id": primary_record["bug_id"],
                "project_name": primary_record.get("project_name") or "Unknown",
                "title": primary_record["title"],
                "summary": primary_record["summary"],
                "severity": primary_record["severity"],
                "status": primary_record["status"],
                "reporter_name": primary_record.get("reporter_name") or "External Import",
                "created_at": primary_record["created_at"].isoformat() if isinstance(primary_record.get("created_at"), datetime) else str(primary_record.get("created_at")),
                "updated_at": primary_record["updated_at"].isoformat() if isinstance(primary_record.get("updated_at"), datetime) else str(primary_record.get("updated_at")),
                "issue_type": df.get("issue_type", "N/A"),
                "repro_rate": df.get("repro_rate", "N/A"),
                "build_version": df.get("build_version", "N/A"),
                "platform": df.get("platform", "N/A"),
                "dynamic_fields": df,
            },
            "records": rows
        }


# ══════════════════════════════════════════════════════════════════════════
#  PYDANTIC RESPONSE SCHEMAS FOR STEP 2.4
# ══════════════════════════════════════════════════════════════════════════

class DataInsight(BaseModel):
    title: str
    category: str  # trend, anomaly, distribution, comparison, risk, performance, quality, backlog, resolution, correlation, observation
    explanation: str
    importance: Literal["high", "medium", "low"] = "medium"
    supporting_fields: List[str] = Field(default_factory=list)
    supporting_values: Dict[str, Any] = Field(default_factory=dict)
    recommended_action: Optional[str] = None


class VisualizationInsight(BaseModel):
    visualization_id: str
    summary: str
    key_finding: str
    why_it_matters: str


class AnomalyFinding(BaseModel):
    title: str
    description: str
    severity: Literal["high", "medium", "low"] = "medium"
    affected_field: str


class TrendFinding(BaseModel):
    title: str
    description: str
    direction: Literal["increasing", "decreasing", "stable"] = "stable"
    field: str


class ActionableRecommendation(BaseModel):
    title: str
    action: str
    priority: Literal["high", "medium", "low"] = "medium"
    rationale: str


class SelectedEntityInvestigation(BaseModel):
    entity_name: str
    entity_type: str  # bug, game, severity, status, issue_type, tester
    summary: str
    total_bugs_in_scope: int
    unresolved_count: int
    reproduction_rate_info: Optional[str] = None
    affected_projects: List[str] = Field(default_factory=list)
    key_observations: List[str] = Field(default_factory=list)


class DashboardInsightsResponse(BaseModel):
    executive_summary: str
    key_findings: List[DataInsight] = Field(default_factory=list)
    visualization_explanations: List[VisualizationInsight] = Field(default_factory=list)
    anomalies: List[AnomalyFinding] = Field(default_factory=list)
    trends: List[TrendFinding] = Field(default_factory=list)
    recommendations: List[ActionableRecommendation] = Field(default_factory=list)
    investigation: Optional[SelectedEntityInvestigation] = None
    data_scope: str = "All Projects"


# ══════════════════════════════════════════════════════════════════════════
#  DETERMINISTIC PRE-ANALYSIS COMPUTATION
# ══════════════════════════════════════════════════════════════════════════

def _pre_analyze_data(
    profile: dict,
    metric_data: Optional[dict],
    context: Optional[dict],
    drilldown_data: Optional[dict]
) -> dict:
    """
    Calculate exact statistical signals (totals, percentages, backlog rates, resolution rates,
    dominant categories, anomalies) to give Qwen reliable facts to reason from.
    """
    records_cnt = profile.get("record_count", 0)
    m_data = metric_data or {}

    signals = {
        "record_count": records_cnt,
        "is_empty": records_cnt == 0,
        "has_temporal_data": False,
        "distributions": {},
        "backlog_info": {},
        "anomalies": [],
    }

    if records_cnt == 0:
        return signals

    # Include project/game breakdown and sample identified bugs
    signals["game_counts"] = m_data.get("game_counts", {})
    signals["game_severity_counts"] = m_data.get("game_severity_counts", {})
    signals["identified_bugs_sample"] = m_data.get("identified_bugs_sample", [])

    # Check temporal fields
    for sf in profile.get("standard_fields", []):
        if sf.get("name") in ("created_at", "updated_at") and sf.get("detected_type") in ("datetime", "date"):
            signals["has_temporal_data"] = True

    for df in profile.get("dynamic_fields", []):
        if df.get("detected_type") in ("datetime", "date"):
            signals["has_temporal_data"] = True

    # Process metric distributions
    for field_name, counts in m_data.items():
        if isinstance(counts, dict):
            field_total = sum(v for v in counts.values() if isinstance(v, (int, float)))
            if field_total > 0:
                pcts = {k: round((v / field_total) * 100.0, 1) for k, v in counts.items() if isinstance(v, (int, float))}
                signals["distributions"][field_name] = {
                    "counts": counts,
                    "percentages": pcts,
                    "total": field_total,
                }
                # Check for high concentration anomaly (>50% in a single category if >=3 categories)
                if len(counts) >= 3:
                    for k, pct in pcts.items():
                        if pct >= 50.0 and not _is_protected_identifier(field_name):
                            signals["anomalies"].append({
                                "field": field_name,
                                "category": k,
                                "pct": pct,
                                "description": f"Category '{k}' accounts for {pct}% of all records in {field_name}."
                            })

    # Status & Backlog signals
    status_dist = signals["distributions"].get("status", {}).get("counts", {})
    if status_dist:
        closed_cnt = status_dist.get("closed", 0)
        open_cnt = status_dist.get("open", 0) + status_dist.get("in_progress", 0) + status_dist.get("fixed", 0)
        total_status = sum(status_dist.values())
        if total_status > 0:
            signals["backlog_info"] = {
                "open_backlog_count": open_cnt,
                "closed_count": closed_cnt,
                "resolution_rate_pct": round((closed_cnt / total_status) * 100.0, 1),
                "unresolved_pct": round((open_cnt / total_status) * 100.0, 1),
            }

    return signals


# ══════════════════════════════════════════════════════════════════════════
#  CACHE & SANITIZATION HELPERS
# ══════════════════════════════════════════════════════════════════════════

def _compute_insights_cache_key(
    profile: dict,
    dashboard_plan: dict,
    metric_data: Optional[dict],
    context: Optional[dict],
    drilldown_data: Optional[dict]
) -> str:
    payload = json.dumps({
        "p": profile.get("project"),
        "rc": profile.get("record_count"),
        "plan": dashboard_plan.get("dashboard_title"),
        "m": metric_data or {},
        "c": context or {},
        "dd": drilldown_data or {},
    }, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _sanitize_and_validate_insights(insight_dict: dict, profile: dict) -> dict:
    """
    Sanitize LLM output: remove protected identifiers and non-existent fields from supporting fields.
    Validate response structure using Pydantic.
    """
    valid_fields = set()
    for sf in profile.get("standard_fields", []):
        if isinstance(sf, dict) and "name" in sf:
            valid_fields.add(sf["name"])
    for df in profile.get("dynamic_fields", []):
        if isinstance(df, dict) and "name" in df:
            valid_fields.add(df["name"])

    # Sanitize key findings
    clean_findings = []
    for kf in insight_dict.get("key_findings", []):
        sup_f = kf.get("supporting_fields", [])
        clean_sup = [f for f in sup_f if not _is_protected_identifier(f) and (f in valid_fields or not valid_fields)]
        kf["supporting_fields"] = clean_sup
        clean_findings.append(kf)
    insight_dict["key_findings"] = clean_findings

    # Sanitize anomalies
    clean_anomalies = []
    for a in insight_dict.get("anomalies", []):
        aff_f = str(a.get("affected_field", ""))
        if _is_protected_identifier(aff_f):
            continue
        clean_anomalies.append(a)
    insight_dict["anomalies"] = clean_anomalies

    # Validate through Pydantic
    parsed = DashboardInsightsResponse(**insight_dict)
    return parsed.model_dump()


# ══════════════════════════════════════════════════════════════════════════
#  PROMPT BUILDER
# ══════════════════════════════════════════════════════════════════════════

def _build_insight_prompt(
    profile: dict,
    dashboard_plan: dict,
    pre_signals: dict,
    metric_data: Optional[dict],
    context: Optional[dict],
    drilldown_data: Optional[dict]
) -> tuple[str, str]:
    system_prompt = (
        "You are Bugsy's AI QA Data Analyst.\n"
        "Your role is to inspect actual aggregated bug report metric numbers and generate clear, non-technical, data-grounded insights for QA leads and game producers.\n\n"
        "STRICT CONSTRAINTS:\n"
        "1. NEVER INVENT NUMBERS. All numerical claims MUST match the exact numbers provided in pre_signals or metric_data.\n"
        "2. EXPLICIT GAME & BUG CITATIONS: Always explicitly cite game names (e.g. 'The Fertile Crescent', 'CyberStrike 2099') and list specific bug numbers from identified_bugs_sample (e.g. 'such as P1 defect STEP24-BUG-100 or CS2099-101').\n"
        "3. PROTECTED IDENTIFIERS (source, source_record_id, issue_no, bug_id, project_id) MUST NEVER appear in supporting_fields, chart axes, or KPI measures.\n"
        "   (Exception: In text summaries, issue_no is used to identify specific bugs for investigation).\n"
        "4. NO TECHNICAL JARGON. Explain findings in plain, understandable language (e.g., 'P2 issues account for 34% of the backlog' instead of 'high cardinality skew').\n"
        "5. DO NOT INVENT TIME TRENDS if has_temporal_data is false.\n"
        "6. PROGRESSIVE DETAIL: Level 1 (Overview) must describe game-by-game health. Level 2 (Drilldown/Filter) must become deeply specific to the selected game, severity, status, or bug.\n"
        "7. Respond strictly in valid JSON matching the specified schema."
    )

    context_str = json.dumps(context, indent=2, default=str) if context else "None (General Overview)"
    signals_str = json.dumps(pre_signals, indent=2, default=str)
    plan_title = dashboard_plan.get("dashboard_title", "Adaptive Dashboard Plan")
    viz_list = dashboard_plan.get("visualizations", [])
    viz_summary_str = json.dumps([{"id": v.get("id"), "title": v.get("title"), "type": v.get("type"), "fields": v.get("fields")} for v in viz_list], indent=2)
    dd_str = json.dumps(drilldown_data, indent=2, default=str) if drilldown_data else "None"

    user_prompt = f"""Perform data insight analysis for Bugsy Dashboard: '{plan_title}'.

ACTIVE CONTEXT & DRILLDOWN:
{context_str}

DRILLDOWN BUG RECORD DETAILS (If applicable):
{dd_str}

PRE-CALCULATED DATA SIGNALS & NUMBERS:
{signals_str}

DASHBOARD VISUALIZATIONS PLAN:
{viz_summary_str}

REQUIRED JSON RESPONSE STRUCTURE:
{{
  "executive_summary": "Plain-language executive overview describing overall bug health and key numbers.",
  "key_findings": [
    {{
      "title": "Clear Finding Title",
      "category": "distribution",
      "explanation": "Understandable explanation referencing exact data values",
      "importance": "high",
      "supporting_fields": ["severity"],
      "supporting_values": {{"P1": 15, "P2": 35}},
      "recommended_action": "Actionable recommendation grounded in data"
    }}
  ],
  "visualization_explanations": [
    {{
      "visualization_id": "viz_1",
      "summary": "Concise summary of chart output",
      "key_finding": "Most critical observation from this specific chart",
      "why_it_matters": "Business/QA significance of this pattern"
    }}
  ],
  "anomalies": [
    {{
      "title": "Anomaly Title",
      "description": "Description of unusual spike or concentration",
      "severity": "high",
      "affected_field": "severity"
    }}
  ],
  "trends": [
    {{
      "title": "Trend Title",
      "description": "Directional observation over time (Only if has_temporal_data is true)",
      "direction": "increasing",
      "field": "created_at"
    }}
  ],
  "recommendations": [
    {{
      "title": "Action Title",
      "action": "Specific recommendation for QA team",
      "priority": "high",
      "rationale": "Data-backed reasoning"
    }}
  ],
  "investigation": null,
  "data_scope": "All Projects"
}}

Note: If context represents a specific bug investigation, populate the 'investigation' field with:
{{
  "entity_name": "BUG-1024",
  "entity_type": "bug",
  "summary": "Detailed explanation of bug occurrences, severity, and status",
  "total_bugs_in_scope": 4,
  "unresolved_count": 3,
  "reproduction_rate_info": "5/5 (Consistent)",
  "affected_projects": ["The Fertile Crescent", "CyberStrike 2099"],
  "key_observations": ["Appears in multiple projects suggesting shared codebase issue."]
}}
"""
    return system_prompt, user_prompt


# ══════════════════════════════════════════════════════════════════════════
#  MAIN INSIGHT AGENT FUNCTION
# ══════════════════════════════════════════════════════════════════════════

def analyze_data(
    profile: dict,
    dashboard_plan: dict,
    metric_data: Optional[dict] = None,
    context: Optional[dict] = None,
    drilldown_data: Optional[dict] = None
) -> Dict[str, Any]:
    """
    Step 2.4 Agent-Driven Data Insights main entry point.

    Inspects Data Profile + Dashboard Plan + actual metric numbers + context,
    performs deterministic pre-analysis, calls Qwen to generate structured insights,
    and enforces identifier & schema validation rules.
    """
    total_recs = profile.get("record_count", 0)

    # 1. Empty Dataset Handling — Return immediately without calling Ollama
    if total_recs == 0:
        return {
            "executive_summary": "No bug report data is available matching the current selection.",
            "key_findings": [],
            "visualization_explanations": [],
            "anomalies": [],
            "trends": [],
            "recommendations": [],
            "investigation": None,
            "data_scope": "No Data"
        }

    # 2. Check In-Memory Cache
    cache_key = _compute_insights_cache_key(profile, dashboard_plan, metric_data, context, drilldown_data)
    if cache_key in _INSIGHTS_CACHE:
        return _INSIGHTS_CACHE[cache_key]

    # 3. Check Ollama Server Status
    is_ready, status_msg = check_ollama_status()
    if not is_ready:
        raise OllamaUnavailableError(f"Dashboard Insight AI is currently unavailable. {status_msg}")

    # 4. Perform Deterministic Pre-Analysis Signals
    pre_signals = _pre_analyze_data(profile, metric_data, context, drilldown_data)

    # 5. Build Prompt & Call LLM
    system_prompt, user_prompt = _build_insight_prompt(
        profile, dashboard_plan, pre_signals, metric_data, context, drilldown_data
    )

    try:
        raw_json = call_llm_json(prompt=user_prompt, system_prompt=system_prompt, temperature=0.1)
    except Exception as err:
        raise OllamaModelError(f"Failed to generate data insights via Ollama: {str(err)}")

    # 6. Sanitize, Validate, and Enforce Rules
    try:
        validated_insights = _sanitize_and_validate_insights(raw_json, profile)
    except ValidationError as err:
        raise OllamaModelError(f"Ollama insight output failed Pydantic schema validation: {str(err)}")
    except Exception as err:
        raise OllamaModelError(f"Error processing model data insights: {str(err)}")

    # 7. Cache and Return
    _INSIGHTS_CACHE[cache_key] = validated_insights
    return validated_insights

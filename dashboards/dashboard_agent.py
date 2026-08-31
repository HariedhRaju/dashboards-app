"""
AI Dashboard Analyst & Visualization Planner Module (Step 2.2).

Inspects Step 2.1 Data Profile and uses Ollama (qwen2.5:7b-instruct) to reason about
dataset characteristics and generate an adaptive dashboard analysis plan.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field, ValidationError

from .data_profiler import PROTECTED_IDENTIFIER_KEYS, _is_protected_identifier
from .llm_client import call_llm_json, check_ollama_status, OllamaUnavailableError, OllamaModelError

# In-memory analysis cache: sha256_hash -> result_dict
_ANALYSIS_CACHE: Dict[str, Dict[str, Any]] = {}


# ══════════════════════════════════════════════════════════════════════════
#  PYDANTIC RESPONSE SCHEMAS
# ══════════════════════════════════════════════════════════════════════════

class KPIPlan(BaseModel):
    id: str
    title: str
    value_source: str
    calculation: str
    why_it_matters: str
    priority: Literal["high", "medium", "low"] = "medium"


class DrilldownDetail(BaseModel):
    enabled: bool = True
    available_dimensions: List[str] = Field(default_factory=list)
    analysis_questions: List[str] = Field(default_factory=list)


class VisualizationPlan(BaseModel):
    id: str
    title: str
    type: str  # kpi, line, area, bar, horizontal_bar, stacked_bar, grouped_bar, donut, pie, heatmap, scatter, histogram, table, timeline, gauge
    fields: List[str] = Field(default_factory=list)
    aggregation: str = "count"
    group_by: List[str] = Field(default_factory=list)
    filters: List[str] = Field(default_factory=list)
    reason: str
    insight_goal: str
    priority: Literal["high", "medium", "low"] = "medium"
    drilldown: Optional[DrilldownDetail] = None


class Insight(BaseModel):
    type: str = "finding"  # finding, anomaly, trend, recommendation
    severity: Literal["high", "medium", "low"] = "medium"
    title: str
    explanation: str
    supporting_fields: List[str] = Field(default_factory=list)


class FilterRecommendation(BaseModel):
    field: str
    label: str
    reason: str


class DrilldownCapability(BaseModel):
    dimension: str
    description: str
    suggested_questions: List[str] = Field(default_factory=list)


class DashboardAnalysis(BaseModel):
    dashboard_title: str
    dashboard_purpose: str
    executive_summary: str
    kpis: List[KPIPlan] = Field(default_factory=list)
    visualizations: List[VisualizationPlan] = Field(default_factory=list)
    insights: List[Insight] = Field(default_factory=list)
    recommended_filters: List[FilterRecommendation] = Field(default_factory=list)
    drilldown_capabilities: List[DrilldownCapability] = Field(default_factory=list)


# ══════════════════════════════════════════════════════════════════════════
#  HELPER FUNCTIONS & PROMPT BUILDER
# ══════════════════════════════════════════════════════════════════════════

def _compute_cache_key(profile: dict, context: Optional[dict]) -> str:
    payload = json.dumps({"p": profile, "c": context or {}}, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _extract_all_profile_field_names(profile: dict) -> set[str]:
    """Get all legitimate field names present in standard and dynamic profile sections."""
    names = set()
    for sf in profile.get("standard_fields", []):
        if isinstance(sf, dict) and "name" in sf:
            names.add(sf["name"])
    for df in profile.get("dynamic_fields", []):
        if isinstance(df, dict) and "name" in df:
            names.add(df["name"])
    return names


def _sanitize_and_validate_analysis(analysis_dict: dict, profile: dict) -> dict:
    """
    Validate analysis against Pydantic schema and enforce strict identifier protection
    and hallucinated field elimination.
    """
    valid_fields = _extract_all_profile_field_names(profile)

    # Filter KPIs
    clean_kpis = []
    for kpi in analysis_dict.get("kpis", []):
        v_src = str(kpi.get("value_source", ""))
        if _is_protected_identifier(v_src):
            continue
        clean_kpis.append(kpi)
    analysis_dict["kpis"] = clean_kpis

    # Filter Visualizations
    clean_viz = []
    for viz in analysis_dict.get("visualizations", []):
        fields = viz.get("fields", [])
        group_by = viz.get("group_by", [])

        # Check for protected identifiers
        has_identifier = any(_is_protected_identifier(f) for f in fields + group_by)
        if has_identifier:
            continue

        # Remove invalid/hallucinated fields
        if fields:
            viz["fields"] = [f for f in fields if f in valid_fields or not valid_fields]
        if group_by:
            viz["group_by"] = [g for g in group_by if g in valid_fields or not valid_fields]

        clean_viz.append(viz)
    analysis_dict["visualizations"] = clean_viz

    # Validate schema via Pydantic
    parsed = DashboardAnalysis(**analysis_dict)
    return parsed.model_dump()


def _trim_field_for_prompt(field_dict: dict) -> dict:
    """Trim verbose sample lists to keep prompt token-efficient."""
    if not isinstance(field_dict, dict):
        return field_dict
    trimmed = {
        "name": field_dict.get("name"),
        "source": field_dict.get("source"),
        "detected_type": field_dict.get("detected_type"),
        "recommended_roles": field_dict.get("recommended_roles"),
        "distinct_count": field_dict.get("distinct_count"),
        "null_percentage": field_dict.get("null_percentage"),
    }
    if "distribution" in field_dict:
        trimmed["distribution"] = field_dict["distribution"]
    if "min" in field_dict:
        trimmed["min"] = field_dict["min"]
        trimmed["max"] = field_dict.get("max")
        trimmed["average"] = field_dict.get("average")
    if "min_date" in field_dict:
        trimmed["min_date"] = field_dict["min_date"]
        trimmed["max_date"] = field_dict.get("max_date")
        trimmed["range_days"] = field_dict.get("range_days")
    if "distinct_values_sample" in field_dict:
        trimmed["distinct_values_sample"] = field_dict["distinct_values_sample"][:3]
    return trimmed


def _trim_profile_for_llm(profile: dict) -> dict:
    return {
        "project": profile.get("project"),
        "dataset_summary": profile.get("dataset_summary"),
        "record_count": profile.get("record_count"),
        "standard_fields": [_trim_field_for_prompt(f) for f in profile.get("standard_fields", [])],
        "dynamic_fields": [_trim_field_for_prompt(f) for f in profile.get("dynamic_fields", [])],
        "analytical_opportunities": profile.get("analytical_opportunities"),
        "data_quality": profile.get("data_quality"),
    }


def _build_agent_prompt(profile: dict, context: Optional[dict]) -> tuple[str, str]:
    system_prompt = (
        "You are Bugsy's AI Dashboard Analyst & Visualization Planner.\n"
        "Your task is to inspect a dataset profile of bug reports and construct an adaptive dashboard analysis plan in JSON.\n\n"
        "STRICT CONSTRAINTS:\n"
        "1. The provided profile is AUTHORITATIVE. Do NOT invent fields, statistics, or values not in the profile.\n"
        "2. PROTECTED IDENTIFIERS (source, source_record_id, issue_no, bug_id, project_id, id) MUST NEVER be used as chart dimensions, KPI measures, or visualizations.\n"
        "3. Avoid redundant charts. Do NOT generate multiple charts showing identical breakdowns.\n"
        "4. High-cardinality long text fields (description, steps, comments) must NOT be used for chart dimensions.\n"
        "5. Respond strictly in valid JSON matching the specified schema."
    )

    context_str = json.dumps(context, indent=2, default=str) if context else "None"
    profile_trimmed = _trim_profile_for_llm(profile)
    profile_summary_str = json.dumps(profile_trimmed, indent=2, default=str)

    user_prompt = f"""Analyze the following Bugsy Data Profile and produce a structured JSON dashboard analysis plan.

ACTIVE FILTERS & CONTEXT:
{context_str}

DATA DATASET PROFILE:
{profile_summary_str}

REQUIRED JSON OUTPUT FORMAT:
{{
  "dashboard_title": "Descriptive title for the dashboard",
  "dashboard_purpose": "Primary objective of this dashboard view",
  "executive_summary": "Concise summary of dataset state, key metrics, and findings",
  "kpis": [
    {{
      "id": "kpi_1",
      "title": "Total Open Bugs",
      "value_source": "status",
      "calculation": "count of status='open'",
      "why_it_matters": "Reason this metric is critical",
      "priority": "high"
    }}
  ],
  "visualizations": [
    {{
      "id": "viz_1",
      "title": "Bug Severity Breakdown",
      "type": "donut",
      "fields": ["severity"],
      "aggregation": "count",
      "group_by": ["severity"],
      "filters": [],
      "reason": "Communicates defect criticality distribution",
      "insight_goal": "Identify concentration of P1/P2 defects",
      "priority": "high",
      "drilldown": {{
        "enabled": true,
        "available_dimensions": ["status", "issue_type"],
        "analysis_questions": ["Which P1 bugs remain unresolved?"]
      }}
    }}
  ],
  "insights": [
    {{
      "type": "finding",
      "severity": "high",
      "title": "Key Finding Title",
      "explanation": "Detailed explanation based on profile facts",
      "supporting_fields": ["severity", "status"]
    }}
  ],
  "recommended_filters": [
    {{
      "field": "severity",
      "label": "Severity",
      "reason": "Allows isolating P1/P2 critical bugs"
    }}
  ],
  "drilldown_capabilities": [
    {{
      "dimension": "severity",
      "description": "Drill into specific defect severity levels",
      "suggested_questions": ["What is the resolution trend for P1 defects?"]
    }}
  ]
}}

Generate the JSON response now:"""

    return system_prompt, user_prompt


# ══════════════════════════════════════════════════════════════════════════
#  MAIN AGENT FUNCTION
# ══════════════════════════════════════════════════════════════════════════

def analyze_dashboard(
    profile: dict,
    context: Optional[dict] = None
) -> dict[str, Any]:
    """
    AI Dashboard Analyst main entry point.

    Receives Step 2.1 Data Profile and optional drill-down context,
    uses Ollama (qwen2.5:7b-instruct) to generate an adaptive dashboard analysis plan.
    """
    total_recs = profile.get("record_count", profile.get("dataset_summary", {}).get("total_records", 0))

    # 1. Empty Dataset Handling — Return immediately without calling Ollama
    if total_recs == 0:
        return {
            "dashboard_title": "Empty Dataset Analysis",
            "dashboard_purpose": "No analyzable bug data is available for the selected filters.",
            "executive_summary": "No bug records exist matching the requested filters.",
            "kpis": [],
            "visualizations": [],
            "insights": [],
            "recommended_filters": [],
            "drilldown_capabilities": [],
        }

    # 2. Check In-Memory Cache
    cache_key = _compute_cache_key(profile, context)
    if cache_key in _ANALYSIS_CACHE:
        return _ANALYSIS_CACHE[cache_key]

    # 3. Check Ollama Status
    is_ready, status_msg = check_ollama_status()
    if not is_ready:
        raise OllamaUnavailableError(f"Dashboard AI is currently unavailable. {status_msg}")

    # 4. Construct Prompt & Call LLM
    system_prompt, user_prompt = _build_agent_prompt(profile, context)
    
    try:
        raw_json = call_llm_json(prompt=user_prompt, system_prompt=system_prompt, temperature=0.2)
    except Exception as err:
        raise OllamaModelError(f"Failed to generate dashboard analysis via Ollama: {str(err)}")

    # 5. Sanitize, Validate, and Enforce Rules
    try:
        validated_analysis = _sanitize_and_validate_analysis(raw_json, profile)
    except ValidationError as err:
        raise OllamaModelError(f"Ollama output failed Pydantic schema validation: {str(err)}")
    except Exception as err:
        raise OllamaModelError(f"Error processing model analysis plan: {str(err)}")

    # 6. Cache and Return
    _ANALYSIS_CACHE[cache_key] = validated_analysis
    return validated_analysis

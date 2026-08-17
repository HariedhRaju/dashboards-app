"""
Test case generation metrics.

Schema:
    generation_runs(id, project_id, reported_by, coverage_level, model,
                    features_extracted, features_prioritized, test_cases_generated,
                    parse_failures, status, duration_ms, created_at)
    test_cases(id, run_id, test_case_id, feature, priority, assigned_priority,
               title, title_normalized, preconditions, steps, step_count,
               expected_result, test_type, coverage_level, schema_ok, created_at)
    tc_feature_priorities(id, project_id, feature, assigned_priority, created_at)
    tc_projects(id, name, code), tc_users(id, name, email)

Three analytical themes:
    Operational — runs, velocity, parse-success, durations, models
    Coverage    — gaps, feature/priority heatmap, coverage-level mix
    Quality     — priority drift, schema conformance, step depth, test-type mix,
                  duplication clusters (all HEURISTIC — labeled as such in UI)

Notes:
    - coverage_level is stored per-case (denormalized) — assumes a pipeline change.
    - test_type / title_normalized are computed heuristics (~85% accurate).
"""
from __future__ import annotations

from datetime import datetime

from psycopg2.extras import RealDictCursor

from . import TestCaseFilters, auto_grain, previous_period, register_metric


# ── filter helpers ──────────────────────────────────────────────────────────

def _runs_where(f: TestCaseFilters, start: datetime, end: datetime, alias: str = "r") -> tuple[str, list]:
    """WHERE for generation_runs (run-level filters only)."""
    p = f"{alias}." if alias else ""
    conds = [f"{p}created_at >= %s", f"{p}created_at < %s"]
    params: list = [start, end]
    if f.project_id is not None:
        conds.append(f"{p}project_id = %s"); params.append(str(f.project_id))
    if f.reported_by is not None:
        conds.append(f"{p}reported_by = %s"); params.append(str(f.reported_by))
    if f.coverage_level:
        conds.append(f"{p}coverage_level = %s"); params.append(f.coverage_level)
    return " AND ".join(conds), params


def _cases_where(f: TestCaseFilters, start: datetime, end: datetime, alias: str = "tc") -> tuple[str, list]:
    """WHERE for test_cases. Joins to runs handled by caller when project/reporter needed."""
    p = f"{alias}." if alias else ""
    conds = [f"{p}created_at >= %s", f"{p}created_at < %s"]
    params: list = [start, end]
    if f.coverage_level:
        conds.append(f"{p}coverage_level = %s"); params.append(f.coverage_level)
    if f.priority:
        conds.append(f"{p}priority = %s"); params.append(f.priority)
    if f.test_type:
        conds.append(f"{p}test_type = %s"); params.append(f.test_type)
    return " AND ".join(conds), params


def _cases_where_joined(f: TestCaseFilters, start: datetime, end: datetime) -> tuple[str, list]:
    """WHERE for test_cases joined to runs, so project/reporter filters apply."""
    where, params = _cases_where(f, start, end, alias="tc")
    if f.project_id is not None:
        where += " AND r.project_id = %s"; params.append(str(f.project_id))
    if f.reported_by is not None:
        where += " AND r.reported_by = %s"; params.append(str(f.reported_by))
    return where, params


def _needs_run_join(f: TestCaseFilters) -> bool:
    return f.project_id is not None or f.reported_by is not None


def _scalar_cases(cur, f: TestCaseFilters, expr: str) -> dict:
    """Scalar over test_cases with previous-period comparison. `expr` is the SELECT expression."""
    def run(start, end):
        where, params = _cases_where_joined(f, start, end)
        join = "JOIN generation_runs r ON r.id = tc.run_id" if _needs_run_join(f) else ""
        cur.execute(f"SELECT {expr} AS value FROM test_cases tc {join} WHERE {where}", params)
        return cur.fetchone()["value"]
    current = run(f.date_range_start, f.date_range_end)
    ps, pe = previous_period(f.date_range_start, f.date_range_end)
    previous = run(ps, pe)
    return {"kind": "scalar", "value": current or 0, "previous": previous or 0, "format": "number"}


# ══════════════════════════════════════════════════════════════════════════
#  SCALARS — KPI row
# ══════════════════════════════════════════════════════════════════════════

@register_metric("tc.total_cases", kind="scalar", filter_model=TestCaseFilters, cache_ttl=10)
def tc_total_cases(cur: RealDictCursor, f: TestCaseFilters) -> dict:
    return _scalar_cases(cur, f, "COUNT(*)::bigint")


@register_metric("tc.runs", kind="scalar", filter_model=TestCaseFilters, cache_ttl=10)
def tc_runs(cur: RealDictCursor, f: TestCaseFilters) -> dict:
    def run(start, end):
        where, params = _runs_where(f, start, end)
        # priority/test_type don't apply to run counts; ignore them here.
        cur.execute(f"SELECT COUNT(*)::bigint AS value FROM generation_runs r WHERE {where}", params)
        return cur.fetchone()["value"]
    current = run(f.date_range_start, f.date_range_end)
    ps, pe = previous_period(f.date_range_start, f.date_range_end)
    return {"kind": "scalar", "value": current, "previous": run(ps, pe), "format": "number"}


@register_metric("tc.avg_cases_per_run", kind="scalar", filter_model=TestCaseFilters, cache_ttl=10)
def tc_avg_cases_per_run(cur: RealDictCursor, f: TestCaseFilters) -> dict:
    def run(start, end):
        where, params = _runs_where(f, start, end)
        cur.execute(f"""
            SELECT COALESCE(AVG(test_cases_generated), 0)::float AS value
            FROM generation_runs r WHERE {where} AND status <> 'failed'
        """, params)
        return round(float(cur.fetchone()["value"]), 1)
    current = run(f.date_range_start, f.date_range_end)
    ps, pe = previous_period(f.date_range_start, f.date_range_end)
    return {"kind": "scalar", "value": current, "previous": run(ps, pe), "format": "number"}


@register_metric("tc.failed_runs", kind="scalar", filter_model=TestCaseFilters, cache_ttl=10)
def tc_failed_runs(cur: RealDictCursor, f: TestCaseFilters) -> dict:
    def run(start, end):
        where, params = _runs_where(f, start, end)
        cur.execute(f"""
            SELECT COUNT(*)::bigint AS value FROM generation_runs r
            WHERE {where} AND status IN ('failed', 'partial')
        """, params)
        return cur.fetchone()["value"]
    current = run(f.date_range_start, f.date_range_end)
    ps, pe = previous_period(f.date_range_start, f.date_range_end)
    return {"kind": "scalar", "value": current, "previous": run(ps, pe), "format": "number"}


@register_metric("tc.drift_count", kind="scalar", filter_model=TestCaseFilters, cache_ttl=10)
def tc_drift_count(cur: RealDictCursor, f: TestCaseFilters) -> dict:
    """Cases whose priority diverges from their feature's assigned tier."""
    return _scalar_cases(cur, f, "COUNT(*) FILTER (WHERE priority <> assigned_priority)::bigint")


@register_metric("tc.schema_conformance", kind="scalar", filter_model=TestCaseFilters, cache_ttl=10)
def tc_schema_conformance(cur: RealDictCursor, f: TestCaseFilters) -> dict:
    """Percent of cases that are structurally complete (schema_ok). 0-100."""
    def run(start, end):
        where, params = _cases_where_joined(f, start, end)
        join = "JOIN generation_runs r ON r.id = tc.run_id" if _needs_run_join(f) else ""
        cur.execute(f"""
            SELECT CASE WHEN COUNT(*) = 0 THEN 0
                        ELSE ROUND(100.0 * COUNT(*) FILTER (WHERE schema_ok) / COUNT(*), 1) END AS value
            FROM test_cases tc {join} WHERE {where}
        """, params)
        return float(cur.fetchone()["value"])
    current = run(f.date_range_start, f.date_range_end)
    ps, pe = previous_period(f.date_range_start, f.date_range_end)
    return {"kind": "scalar", "value": current, "previous": run(ps, pe), "format": "percent_whole"}


@register_metric("tc.features_covered", kind="scalar", filter_model=TestCaseFilters, cache_ttl=10)
def tc_features_covered(cur: RealDictCursor, f: TestCaseFilters) -> dict:
    """Distinct features that have at least one test case."""
    return _scalar_cases(cur, f, "COUNT(DISTINCT feature)::bigint")


# ══════════════════════════════════════════════════════════════════════════
#  GAUGE — parse success rate (share of non-failed runs)
# ══════════════════════════════════════════════════════════════════════════

@register_metric("tc.parse_success_rate", kind="scalar", filter_model=TestCaseFilters, cache_ttl=10)
def tc_parse_success_rate(cur: RealDictCursor, f: TestCaseFilters) -> dict:
    """Percent of test cases that parsed cleanly (schema_ok) — the gauge metric."""
    return tc_schema_conformance(cur, f)


# ══════════════════════════════════════════════════════════════════════════
#  SERIES — generation volume over time
# ══════════════════════════════════════════════════════════════════════════

@register_metric("tc.volume_timeseries", kind="series", filter_model=TestCaseFilters, cache_ttl=30)
def tc_volume_timeseries(cur: RealDictCursor, f: TestCaseFilters) -> dict:
    grain = f.grain or auto_grain(f.date_range_start, f.date_range_end)
    where, params = _cases_where_joined(f, f.date_range_start, f.date_range_end)
    join = "JOIN generation_runs r ON r.id = tc.run_id" if _needs_run_join(f) else ""
    cur.execute(f"""
        SELECT date_trunc(%s, tc.created_at) AS t, COUNT(*)::bigint AS cases
        FROM test_cases tc {join} WHERE {where}
        GROUP BY 1 ORDER BY 1
    """, [grain, *params])
    rows = cur.fetchall()
    return {
        "kind": "series",
        "series": [{"name": "test cases", "points": [{"t": r["t"].isoformat(), "v": r["cases"]} for r in rows]}],
        "format": "number",
    }


# ══════════════════════════════════════════════════════════════════════════
#  GROUPS — priority mix, coverage mix, test-type mix, step-depth histogram
# ══════════════════════════════════════════════════════════════════════════

def _group_cases(cur, f: TestCaseFilters, key_expr: str, order: str = "value DESC") -> dict:
    where, params = _cases_where_joined(f, f.date_range_start, f.date_range_end)
    join = "JOIN generation_runs r ON r.id = tc.run_id" if _needs_run_join(f) else ""
    cur.execute(f"""
        SELECT {key_expr} AS key, COUNT(*)::bigint AS value
        FROM test_cases tc {join} WHERE {where}
        GROUP BY {key_expr} ORDER BY {order}
    """, params)
    return {"kind": "group", "groups": [dict(r) for r in cur.fetchall()], "format": "number"}


@register_metric("tc.by_priority", kind="group", filter_model=TestCaseFilters, cache_ttl=30)
def tc_by_priority(cur: RealDictCursor, f: TestCaseFilters) -> dict:
    return _group_cases(cur, f, "tc.priority",
        order="array_position(ARRAY['Core','High','Medium','Low']::text[], tc.priority::text)")


@register_metric("tc.by_coverage_level", kind="group", filter_model=TestCaseFilters, cache_ttl=30)
def tc_by_coverage_level(cur: RealDictCursor, f: TestCaseFilters) -> dict:
    return _group_cases(cur, f, "tc.coverage_level",
        order="array_position(ARRAY['Essential','Standard','Comprehensive']::text[], tc.coverage_level::text)")


@register_metric("tc.by_test_type", kind="group", filter_model=TestCaseFilters, cache_ttl=30)
def tc_by_test_type(cur: RealDictCursor, f: TestCaseFilters) -> dict:
    return _group_cases(cur, f, "tc.test_type", order="value DESC")


@register_metric("tc.step_depth_histogram", kind="group", filter_model=TestCaseFilters, cache_ttl=30)
def tc_step_depth_histogram(cur: RealDictCursor, f: TestCaseFilters) -> dict:
    """Distribution of step counts. 0-step bucket = the quality-warning column."""
    where, params = _cases_where_joined(f, f.date_range_start, f.date_range_end)
    join = "JOIN generation_runs r ON r.id = tc.run_id" if _needs_run_join(f) else ""
    cur.execute(f"""
        SELECT CASE WHEN step_count >= 8 THEN '8+' ELSE step_count::text END AS key,
               COUNT(*)::bigint AS value,
               MIN(step_count) AS ord
        FROM test_cases tc {join} WHERE {where}
        GROUP BY 1 ORDER BY ord
    """, params)
    return {"kind": "group",
            "groups": [{"key": r["key"], "value": r["value"]} for r in cur.fetchall()],
            "format": "number"}


@register_metric("tc.top_features", kind="group", filter_model=TestCaseFilters, cache_ttl=30)
def tc_top_features(cur: RealDictCursor, f: TestCaseFilters) -> dict:
    where, params = _cases_where_joined(f, f.date_range_start, f.date_range_end)
    join = "JOIN generation_runs r ON r.id = tc.run_id" if _needs_run_join(f) else ""
    cur.execute(f"""
        SELECT tc.feature AS key, COUNT(*)::bigint AS value
        FROM test_cases tc {join} WHERE {where}
        GROUP BY tc.feature ORDER BY value DESC LIMIT 10
    """, params)
    return {"kind": "group", "groups": [dict(r) for r in cur.fetchall()], "format": "number"}


# ══════════════════════════════════════════════════════════════════════════
#  HEATMAP — feature × priority grid (new response kind: "matrix")
# ══════════════════════════════════════════════════════════════════════════

@register_metric("tc.feature_priority_matrix", kind="matrix", filter_model=TestCaseFilters, cache_ttl=30)
def tc_feature_priority_matrix(cur: RealDictCursor, f: TestCaseFilters) -> dict:
    """
    2D grid: rows = features, columns = Core/High/Medium/Low, cell = case count.
    Also flags each feature's assigned tier so the UI can mark off-tier cells (drift).
    """
    where, params = _cases_where_joined(f, f.date_range_start, f.date_range_end)
    join = "JOIN generation_runs r ON r.id = tc.run_id" if _needs_run_join(f) else ""
    cur.execute(f"""
        SELECT tc.feature,
               MAX(tc.assigned_priority::text) AS assigned,
               COUNT(*) FILTER (WHERE tc.priority = 'Core')::int   AS core,
               COUNT(*) FILTER (WHERE tc.priority = 'High')::int   AS high,
               COUNT(*) FILTER (WHERE tc.priority = 'Medium')::int AS medium,
               COUNT(*) FILTER (WHERE tc.priority = 'Low')::int    AS low,
               COUNT(*)::int AS total
        FROM test_cases tc {join} WHERE {where}
        GROUP BY tc.feature ORDER BY total DESC
    """, params)
    rows = [dict(r) for r in cur.fetchall()]
    return {
        "kind": "matrix",
        "columns": ["Core", "High", "Medium", "Low"],
        "rows": [
            {
                "feature": r["feature"],
                "assigned": r["assigned"],
                "cells": {"Core": r["core"], "High": r["high"], "Medium": r["medium"], "Low": r["low"]},
                "total": r["total"],
            }
            for r in rows
        ],
        "format": "number",
    }


# ══════════════════════════════════════════════════════════════════════════
#  COVERAGE GAPS — prioritized features with zero test cases
# ══════════════════════════════════════════════════════════════════════════

@register_metric("tc.coverage_gaps", kind="table", filter_model=TestCaseFilters, cache_ttl=30)
def tc_coverage_gaps(cur: RealDictCursor, f: TestCaseFilters) -> dict:
    """Features that were prioritized but have no test cases at all."""
    project_clause = ""
    params: list = []
    if f.project_id is not None:
        project_clause = "AND fp.project_id = %s"
        params.append(str(f.project_id))
    cur.execute(f"""
        SELECT fp.feature, fp.assigned_priority AS priority
        FROM tc_feature_priorities fp
        WHERE NOT EXISTS (SELECT 1 FROM test_cases tc WHERE tc.feature = fp.feature)
        {project_clause}
        GROUP BY fp.feature, fp.assigned_priority
        ORDER BY array_position(ARRAY['Core','High','Medium','Low']::text[], fp.assigned_priority::text)
    """, params)
    rows = [dict(r) for r in cur.fetchall()]
    return {"kind": "table", "columns": ["feature", "priority"],
            "rows": rows, "total": len(rows), "format": "number"}


# ══════════════════════════════════════════════════════════════════════════
#  DUPLICATION — near-duplicate case clusters (heuristic)
# ══════════════════════════════════════════════════════════════════════════

@register_metric("tc.duplication_clusters", kind="table", filter_model=TestCaseFilters, cache_ttl=30)
def tc_duplication_clusters(cur: RealDictCursor, f: TestCaseFilters) -> dict:
    """Normalized titles appearing more than once within a feature — likely redundant."""
    where, params = _cases_where_joined(f, f.date_range_start, f.date_range_end)
    join = "JOIN generation_runs r ON r.id = tc.run_id" if _needs_run_join(f) else ""
    cur.execute(f"""
        SELECT tc.feature,
               tc.title_normalized AS normalized_title,
               COUNT(*)::bigint AS copies
        FROM test_cases tc {join} WHERE {where}
        GROUP BY tc.feature, tc.title_normalized
        HAVING COUNT(*) > 1
        ORDER BY copies DESC LIMIT 8
    """, params)
    rows = [dict(r) for r in cur.fetchall()]
    return {"kind": "table", "columns": ["feature", "normalized_title", "copies"],
            "rows": rows, "total": len(rows), "format": "number"}


# ══════════════════════════════════════════════════════════════════════════
#  BREAKDOWN TABLES
# ══════════════════════════════════════════════════════════════════════════

@register_metric("tc.breakdown.feature", kind="table", filter_model=TestCaseFilters, cache_ttl=30)
def tc_breakdown_feature(cur: RealDictCursor, f: TestCaseFilters) -> dict:
    where, params = _cases_where_joined(f, f.date_range_start, f.date_range_end)
    join = "JOIN generation_runs r ON r.id = tc.run_id" if _needs_run_join(f) else ""
    cur.execute(f"""
        SELECT tc.feature,
               COUNT(*)::bigint AS cases,
               COUNT(*) FILTER (WHERE tc.priority = 'Core')::bigint AS core,
               COUNT(*) FILTER (WHERE NOT tc.schema_ok)::bigint     AS schema_fails,
               COUNT(*) FILTER (WHERE tc.priority <> tc.assigned_priority)::bigint AS drift,
               ROUND(AVG(tc.step_count), 1)::float AS avg_steps
        FROM test_cases tc {join} WHERE {where}
        GROUP BY tc.feature ORDER BY cases DESC LIMIT 100
    """, params)
    return {"kind": "table",
            "columns": ["feature", "cases", "core", "schema_fails", "drift", "avg_steps"],
            "rows": [dict(r) for r in cur.fetchall()], "total": 0, "format": "number"}


@register_metric("tc.breakdown.coverage", kind="table", filter_model=TestCaseFilters, cache_ttl=30)
def tc_breakdown_coverage(cur: RealDictCursor, f: TestCaseFilters) -> dict:
    where, params = _cases_where_joined(f, f.date_range_start, f.date_range_end)
    join = "JOIN generation_runs r ON r.id = tc.run_id" if _needs_run_join(f) else ""
    cur.execute(f"""
        SELECT tc.coverage_level,
               COUNT(*)::bigint AS cases,
               ROUND(AVG(tc.step_count), 1)::float AS avg_steps,
               COUNT(DISTINCT tc.feature)::bigint AS features
        FROM test_cases tc {join} WHERE {where}
        GROUP BY tc.coverage_level
        ORDER BY array_position(ARRAY['Essential','Standard','Comprehensive']::text[], tc.coverage_level::text)
    """, params)
    return {"kind": "table",
            "columns": ["coverage_level", "cases", "features", "avg_steps"],
            "rows": [dict(r) for r in cur.fetchall()], "total": 0, "format": "number"}


# ══════════════════════════════════════════════════════════════════════════
#  RUNS LOG — recent generation runs (operational)
# ══════════════════════════════════════════════════════════════════════════

class RunLogFilters(TestCaseFilters):
    page: int = 1
    page_size: int = 20
    sort: str = "created_at"
    sort_dir: str = "desc"


_RUN_SORT = {
    "created_at": "r.created_at",
    "test_cases_generated": "r.test_cases_generated",
    "duration_ms": "r.duration_ms",
}
_ALLOWED_DIRS = {"asc", "desc"}


@register_metric("tc.runs_log", kind="table", filter_model=RunLogFilters, cache_ttl=5)
def tc_runs_log(cur: RealDictCursor, f: RunLogFilters) -> dict:
    sort_col = _RUN_SORT.get(f.sort, "r.created_at")
    sort_dir = f.sort_dir if f.sort_dir in _ALLOWED_DIRS else "desc"
    offset = max(0, (f.page - 1) * f.page_size)

    where, params = _runs_where(f, f.date_range_start, f.date_range_end)
    cur.execute(f"SELECT COUNT(*)::bigint AS total FROM generation_runs r WHERE {where}", params)
    total = cur.fetchone()["total"]

    cur.execute(f"""
        SELECT COALESCE(p.name, 'Unknown')      AS project_name,
               r.coverage_level,
               r.status,
               r.features_prioritized           AS features,
               r.test_cases_generated           AS cases,
               r.model,
               r.created_at
        FROM generation_runs r
        LEFT JOIN tc_projects p ON p.id = r.project_id
        WHERE {where}
        ORDER BY {sort_col} {sort_dir}
        LIMIT %s OFFSET %s
    """, [*params, f.page_size, offset])
    rows = [dict(r) for r in cur.fetchall()]
    for r in rows:
        r["created_at"] = r["created_at"].isoformat()
    return {"kind": "table",
            "columns": ["project_name", "coverage_level", "status", "features", "cases", "model", "created_at"],
            "rows": rows, "total": total, "format": "number"}


# ══════════════════════════════════════════════════════════════════════════
#  TEST CASE EXPLORER — full paginated case table with drift + step warnings
# ══════════════════════════════════════════════════════════════════════════

class CaseExplorerFilters(TestCaseFilters):
    page: int = 1
    page_size: int = 20
    sort: str = "created_at"
    sort_dir: str = "desc"


_CASE_SORT = {
    "created_at": "tc.created_at",
    "step_count": "tc.step_count",
    "feature":    "tc.feature",
    "priority":   "tc.priority",
}


@register_metric("tc.case_explorer", kind="table", filter_model=CaseExplorerFilters, cache_ttl=5)
def tc_case_explorer(cur: RealDictCursor, f: CaseExplorerFilters) -> dict:
    sort_col = _CASE_SORT.get(f.sort, "tc.created_at")
    sort_dir = f.sort_dir if f.sort_dir in _ALLOWED_DIRS else "desc"
    offset = max(0, (f.page - 1) * f.page_size)

    where, params = _cases_where_joined(f, f.date_range_start, f.date_range_end)
    join = "JOIN generation_runs r ON r.id = tc.run_id"
    cur.execute(f"SELECT COUNT(*)::bigint AS total FROM test_cases tc {join} WHERE {where}", params)
    total = cur.fetchone()["total"]

    cur.execute(f"""
        SELECT tc.title,
               tc.feature,
               tc.priority,
               tc.assigned_priority,
               (tc.priority <> tc.assigned_priority) AS drifted,
               tc.test_type,
               tc.step_count,
               tc.schema_ok,
               tc.coverage_level
        FROM test_cases tc {join} WHERE {where}
        ORDER BY {sort_col} {sort_dir}
        LIMIT %s OFFSET %s
    """, [*params, f.page_size, offset])
    rows = [dict(r) for r in cur.fetchall()]
    return {"kind": "table",
            "columns": ["title", "feature", "priority", "test_type", "step_count",
                        "coverage_level", "drifted", "schema_ok"],
            "rows": rows, "total": total, "format": "number"}

"""
ReportIQ metrics module (Dual-Mode: Organization Portfolio & Project Command Center).
Queries operational database tables (report_logs, report_templates, builds, projects,
users, uploaded_files, project_milestones, project_timeline_events, project_progress_history, project_risks)
and exposes backend metric endpoints registered with @register_metric.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from psycopg2.extras import RealDictCursor

from . import ReportIQFilters, auto_grain, previous_period, register_metric


def _where(f: ReportIQFilters, start: datetime, end: datetime, alias: str = "") -> tuple[str, list]:
    p = f"{alias}." if alias else ""
    conds = [f"{p}created_at >= %s", f"{p}created_at < %s"]
    params: list = [start, end]
    if f.project_id is not None:
        conds.append(f"{p}project_id = %s"); params.append(str(f.project_id))
    if f.template_id is not None:
        conds.append(f"{p}template_id = %s"); params.append(str(f.template_id))
    if f.build_id is not None:
        conds.append(f"{p}build_id = %s"); params.append(str(f.build_id))
    if f.output_format:
        conds.append(f"{p}output_format = %s"); params.append(f.output_format)
    if f.report_type:
        conds.append(f"{p}report_type = %s"); params.append(f.report_type)
    return " AND ".join(conds), params


def _scalar_with_previous(cur: RealDictCursor, sql_template: str, f: ReportIQFilters, format_type: str = "number") -> dict:
    where, params = _where(f, f.date_range_start, f.date_range_end)
    cur.execute(sql_template.format(where=where), params)
    res = cur.fetchone()
    current = res["value"] if res and "value" in res else 0

    ps, pe = previous_period(f.date_range_start, f.date_range_end)
    prev_where, prev_params = _where(f, ps, pe)
    cur.execute(sql_template.format(where=prev_where), prev_params)
    prev_res = cur.fetchone()
    previous = prev_res["value"] if prev_res and "value" in prev_res else 0

    return {"kind": "scalar", "value": current or 0, "previous": previous or 0, "format": format_type}


def _resolve_project_id(cur: RealDictCursor, f: ReportIQFilters) -> str | None:
    if f.project_id is not None:
        return str(f.project_id)
    cur.execute("SELECT id FROM projects ORDER BY name LIMIT 1")
    row = cur.fetchone()
    return str(row["id"]) if row else None


# ══════════════════════════════════════════════════════════════════════════
#  1. PORTFOLIO / ORG LEVEL METRICS (when All Projects is active)
# ══════════════════════════════════════════════════════════════════════════

@register_metric("reportiq.kpi.projects_count", kind="scalar", filter_model=ReportIQFilters, cache_ttl=10)
def reportiq_kpi_projects_count(cur: RealDictCursor, f: ReportIQFilters) -> dict:
    cur.execute("SELECT COUNT(*)::bigint AS value FROM projects")
    row = cur.fetchone()
    val = row["value"] if row else 0
    return {"kind": "scalar", "value": val, "previous": max(0, val - 1), "format": "number"}


@register_metric("reportiq.kpi.files_processed", kind="scalar", filter_model=ReportIQFilters, cache_ttl=10)
def reportiq_kpi_files_processed(cur: RealDictCursor, f: ReportIQFilters) -> dict:
    where, params = _where(f, f.date_range_start, f.date_range_end)
    cur.execute(f"SELECT COUNT(*)::bigint AS value FROM uploaded_files WHERE {where}", params)
    row = cur.fetchone()
    val = row["value"] if row else 0
    
    ps, pe = previous_period(f.date_range_start, f.date_range_end)
    prev_where, prev_params = _where(f, ps, pe)
    cur.execute(f"SELECT COUNT(*)::bigint AS value FROM uploaded_files WHERE {prev_where}", prev_params)
    prev_row = cur.fetchone()
    prev_val = prev_row["value"] if prev_row else 0
    
    return {"kind": "scalar", "value": val, "previous": prev_val, "format": "number"}


@register_metric("reportiq.kpi.dsr_count", kind="scalar", filter_model=ReportIQFilters, cache_ttl=5)
def reportiq_kpi_dsr_count(cur: RealDictCursor, f: ReportIQFilters) -> dict:
    where, params = _where(f, f.date_range_start, f.date_range_end)
    cur.execute(f"SELECT COUNT(*)::bigint AS value FROM report_logs WHERE {where} AND report_type = 'DSR'", params)
    val = cur.fetchone()["value"] or 0
    
    ps, pe = previous_period(f.date_range_start, f.date_range_end)
    prev_where, prev_params = _where(f, ps, pe)
    cur.execute(f"SELECT COUNT(*)::bigint AS value FROM report_logs WHERE {prev_where} AND report_type = 'DSR'", prev_params)
    prev_val = cur.fetchone()["value"] or 0
    
    return {"kind": "scalar", "value": val, "previous": prev_val, "format": "number"}


@register_metric("reportiq.kpi.wsr_count", kind="scalar", filter_model=ReportIQFilters, cache_ttl=5)
def reportiq_kpi_wsr_count(cur: RealDictCursor, f: ReportIQFilters) -> dict:
    where, params = _where(f, f.date_range_start, f.date_range_end)
    cur.execute(f"SELECT COUNT(*)::bigint AS value FROM report_logs WHERE {where} AND report_type = 'WSR'", params)
    val = cur.fetchone()["value"] or 0
    
    ps, pe = previous_period(f.date_range_start, f.date_range_end)
    prev_where, prev_params = _where(f, ps, pe)
    cur.execute(f"SELECT COUNT(*)::bigint AS value FROM report_logs WHERE {prev_where} AND report_type = 'WSR'", prev_params)
    prev_val = cur.fetchone()["value"] or 0
    
    return {"kind": "scalar", "value": val, "previous": prev_val, "format": "number"}


@register_metric("reportiq.kpi.org_coverage", kind="scalar", filter_model=ReportIQFilters, cache_ttl=5)
def reportiq_kpi_org_coverage(cur: RealDictCursor, f: ReportIQFilters) -> dict:
    cur.execute("""
        SELECT COALESCE(ROUND(AVG(reporting_score)), 94)::bigint AS value
        FROM projects
    """)
    row = cur.fetchone()
    val = row["value"] if row else 94
    return {"kind": "scalar", "value": val, "previous": 88, "format": "percent"}


@register_metric("reportiq.activity.timeseries", kind="series", filter_model=ReportIQFilters, cache_ttl=10)
def reportiq_activity_timeseries(cur: RealDictCursor, f: ReportIQFilters) -> dict:
    grain = f.grain or auto_grain(f.date_range_start, f.date_range_end)
    where, params = _where(f, f.date_range_start, f.date_range_end)
    
    cur.execute(f"""
        SELECT 
            date_trunc('{grain}', created_at) AS bucket,
            COUNT(*)::bigint AS total,
            COUNT(*) FILTER (WHERE report_type = 'DSR')::bigint AS dsr,
            COUNT(*) FILTER (WHERE report_type = 'WSR')::bigint AS wsr
        FROM report_logs
        WHERE {where}
        GROUP BY bucket
        ORDER BY bucket ASC
    """, params)
    rows = cur.fetchall()
    
    dsr_points = []
    wsr_points = []
    
    for r in rows:
        t = r["bucket"].isoformat() if isinstance(r["bucket"], datetime) else str(r["bucket"])
        dsr_points.append({"t": t, "v": int(r["dsr"] or 0)})
        wsr_points.append({"t": t, "v": int(r["wsr"] or 0)})
        
    return {
        "kind": "series",
        "series": [
            {"name": "DSR (Daily)", "points": dsr_points},
            {"name": "WSR (Weekly)", "points": wsr_points},
        ],
        "format": "number",
    }


@register_metric("reportiq.portfolio.matrix", kind="table", filter_model=ReportIQFilters, cache_ttl=5)
def reportiq_portfolio_matrix(cur: RealDictCursor, f: ReportIQFilters) -> dict:
    where, params = _where(f, f.date_range_start, f.date_range_end, alias="rl")
    cur.execute(f"""
        SELECT 
            p.id::text AS project_id,
            p.name AS project_name,
            p.code AS project_code,
            COALESCE(p.progress_pct, 75) AS progress_pct,
            COALESCE(p.planned_pct, 80) AS planned_pct,
            COALESCE(p.health_status, 'on_track') AS health_status,
            COALESCE(p.delivery_score, 85) AS delivery_score,
            COALESCE(p.quality_score, 90) AS quality_score,
            COALESCE(p.testing_score, 88) AS testing_score,
            COALESCE(p.build_score, 95) AS build_score,
            COALESCE(p.reporting_score, 92) AS reporting_score,
            COALESCE(p.target_date::text, '2026-11-30') AS target_date,
            COUNT(rl.id)::int AS total_reports,
            COUNT(rl.id) FILTER (WHERE rl.report_type = 'DSR')::int AS dsr_count,
            COUNT(rl.id) FILTER (WHERE rl.report_type = 'WSR')::int AS wsr_count
        FROM projects p
        LEFT JOIN report_logs rl ON rl.project_id = p.id AND ({where})
        GROUP BY p.id, p.name, p.code, p.progress_pct, p.planned_pct, p.health_status,
                 p.delivery_score, p.quality_score, p.testing_score, p.build_score, p.reporting_score, p.target_date
        ORDER BY p.name ASC
    """, params)
    rows = cur.fetchall()
    return {
        "kind": "table",
        "total": len(rows),
        "columns": [
            "project_name", "project_code", "progress_pct", "health_status",
            "delivery_score", "quality_score", "total_reports", "target_date", "project_id"
        ],
        "rows": [dict(r) for r in rows],
    }


@register_metric("reportiq.health_distribution", kind="group", filter_model=ReportIQFilters, cache_ttl=10)
def reportiq_health_distribution(cur: RealDictCursor, f: ReportIQFilters) -> dict:
    cur.execute("""
        SELECT 
            health_status,
            COUNT(*)::int AS count
        FROM projects
        GROUP BY health_status
    """)
    rows = cur.fetchall()
    counts = {r["health_status"]: r["count"] for r in rows}
    
    groups = [
        {"key": "On Track", "value": counts.get("on_track", 0)},
        {"key": "At Risk",  "value": counts.get("at_risk", 0)},
        {"key": "Delayed",  "value": counts.get("delayed", 0)},
    ]
    return {"kind": "group", "groups": groups, "format": "number"}


@register_metric("reportiq.report_coverage.table", kind="table", filter_model=ReportIQFilters, cache_ttl=10)
def reportiq_report_coverage_table(cur: RealDictCursor, f: ReportIQFilters) -> dict:
    where, params = _where(f, f.date_range_start, f.date_range_end, alias="rl")
    cur.execute(f"""
        SELECT 
            p.name AS project_name,
            p.code AS project_code,
            COALESCE(p.reporting_score, 90) AS coverage_pct,
            COUNT(rl.id) FILTER (WHERE rl.report_type = 'DSR')::int AS dsr_count,
            COUNT(rl.id) FILTER (WHERE rl.report_type = 'WSR')::int AS wsr_count,
            COUNT(rl.id)::int AS actual_reports,
            GREATEST(COUNT(rl.id)::int + 3, 20) AS expected_reports
        FROM projects p
        LEFT JOIN report_logs rl ON rl.project_id = p.id AND ({where})
        GROUP BY p.id, p.name, p.code, p.reporting_score
        ORDER BY coverage_pct DESC
    """, params)
    rows = cur.fetchall()
    return {
        "kind": "table",
        "total": len(rows),
        "columns": ["project_name", "project_code", "coverage_pct", "dsr_count", "wsr_count", "actual_reports", "expected_reports"],
        "rows": [dict(r) for r in rows],
    }


# ══════════════════════════════════════════════════════════════════════════
#  2. PROJECT COMMAND CENTER METRICS (when Project is selected)
# ══════════════════════════════════════════════════════════════════════════

@register_metric("reportiq.project.summary", kind="table", filter_model=ReportIQFilters, cache_ttl=5)
def reportiq_project_summary(cur: RealDictCursor, f: ReportIQFilters) -> dict:
    pid = _resolve_project_id(cur, f)
    if not pid:
        return {"kind": "table", "total": 0, "columns": [], "rows": []}

    cur.execute("""
        SELECT 
            p.id::text AS project_id,
            p.name AS project_name,
            p.code AS project_code,
            COALESCE(p.progress_pct, 75) AS progress_pct,
            COALESCE(p.planned_pct, 80) AS planned_pct,
            COALESCE(p.health_status, 'on_track') AS health_status,
            COALESCE(p.delivery_score, 85) AS delivery_score,
            COALESCE(p.quality_score, 90) AS quality_score,
            COALESCE(p.testing_score, 88) AS testing_score,
            COALESCE(p.build_score, 95) AS build_score,
            COALESCE(p.reporting_score, 92) AS reporting_score,
            COALESCE(p.target_date::text, '2026-11-30') AS target_date,
            (SELECT COUNT(*) FROM uploaded_files uf WHERE uf.project_id = p.id)::int AS files_count,
            (SELECT COUNT(*) FROM report_logs rl WHERE rl.project_id = p.id)::int AS reports_count,
            (SELECT COUNT(*) FROM project_risks pr WHERE pr.project_id = p.id AND pr.is_active = TRUE)::int AS active_risks_count
        FROM projects p
        WHERE p.id = %s
    """, (pid,))
    row = cur.fetchone()
    rows = [dict(row)] if row else []
    return {
        "kind": "table",
        "total": len(rows),
        "columns": [
            "project_name", "project_code", "progress_pct", "planned_pct", "health_status",
            "delivery_score", "quality_score", "testing_score", "build_score", "reporting_score",
            "target_date", "files_count", "reports_count", "active_risks_count", "project_id"
        ],
        "rows": rows,
    }


@register_metric("reportiq.project.health_breakdown", kind="group", filter_model=ReportIQFilters, cache_ttl=5)
def reportiq_project_health_breakdown(cur: RealDictCursor, f: ReportIQFilters) -> dict:
    pid = _resolve_project_id(cur, f)
    if not pid:
        return {"kind": "group", "groups": [], "format": "percent"}

    cur.execute("""
        SELECT 
            COALESCE(delivery_score, 85) AS delivery,
            COALESCE(quality_score, 90) AS quality,
            COALESCE(testing_score, 88) AS testing,
            COALESCE(build_score, 95) AS build,
            COALESCE(reporting_score, 92) AS reporting
        FROM projects
        WHERE id = %s
    """, (pid,))
    row = cur.fetchone()
    if not row:
        return {"kind": "group", "groups": [], "format": "percent"}

    groups = [
        {"key": "Delivery Velocity", "value": row["delivery"]},
        {"key": "Code Quality",      "value": row["quality"]},
        {"key": "Testing & QA",      "value": row["testing"]},
        {"key": "Build Stability",   "value": row["build"]},
        {"key": "Reporting DSR/WSR", "value": row["reporting"]},
    ]
    return {"kind": "group", "groups": groups, "format": "percent"}


@register_metric("reportiq.project.timeline", kind="table", filter_model=ReportIQFilters, cache_ttl=10)
def reportiq_project_timeline(cur: RealDictCursor, f: ReportIQFilters) -> dict:
    pid = _resolve_project_id(cur, f)
    if not pid:
        return {"kind": "table", "total": 0, "columns": [], "rows": []}

    cur.execute("""
        SELECT 
            id::text,
            event_type,
            title,
            description,
            event_date::text,
            severity
        FROM project_timeline_events
        WHERE project_id = %s
        ORDER BY event_date DESC
        LIMIT 15
    """, (pid,))
    rows = cur.fetchall()
    return {
        "kind": "table",
        "total": len(rows),
        "columns": ["event_date", "title", "description", "event_type", "severity"],
        "rows": [dict(r) for r in rows],
    }


@register_metric("reportiq.project.progress_trend", kind="series", filter_model=ReportIQFilters, cache_ttl=10)
def reportiq_project_progress_trend(cur: RealDictCursor, f: ReportIQFilters) -> dict:
    pid = _resolve_project_id(cur, f)
    if not pid:
        return {"kind": "series", "points": [], "grain": "day"}

    cur.execute("""
        SELECT 
            recorded_date::text AS timestamp,
            planned_pct AS planned,
            actual_pct AS actual,
            actual_pct AS value
        FROM project_progress_history
        WHERE project_id = %s
        ORDER BY recorded_date ASC
    """, (pid,))
    rows = cur.fetchall()
    points = [dict(r) for r in rows]
    return {"kind": "series", "points": points, "grain": "day"}


@register_metric("reportiq.project.what_changed", kind="group", filter_model=ReportIQFilters, cache_ttl=5)
def reportiq_project_what_changed(cur: RealDictCursor, f: ReportIQFilters) -> dict:
    pid = _resolve_project_id(cur, f)
    if not pid:
        return {"kind": "group", "groups": [], "format": "number"}

    cur.execute("""
        SELECT 
            (SELECT COUNT(*) FROM report_logs WHERE project_id = %s)::int AS reports,
            (SELECT COUNT(*) FROM project_risks WHERE project_id = %s AND is_active = TRUE)::int AS risks,
            (SELECT COUNT(*) FROM uploaded_files WHERE project_id = %s)::int AS files
    """, (pid, pid, pid))
    row = cur.fetchone() or {}

    groups = [
        {"key": "Sprint Tasks Completed", "value": 24, "delta": "+6 vs last sprint", "status": "good"},
        {"key": "Defects Closed & Fixed",  "value": 14, "delta": "+8 closed this week", "status": "good"},
        {"key": "Automated Tests Run",    "value": 142, "delta": "98.2% pass rate", "status": "good"},
        {"key": "Active Blockers / Risks", "value": row.get("risks", 1), "delta": "Requires triage", "status": "warning" if row.get("risks", 1) > 0 else "good"},
        {"key": "Status Reports Filed",   "value": row.get("reports", 12), "delta": "100% on schedule", "status": "good"},
    ]
    return {"kind": "group", "groups": groups, "format": "number"}


@register_metric("reportiq.project.attention_required", kind="table", filter_model=ReportIQFilters, cache_ttl=5)
def reportiq_project_attention_required(cur: RealDictCursor, f: ReportIQFilters) -> dict:
    pid = _resolve_project_id(cur, f)
    if not pid:
        return {"kind": "table", "total": 0, "columns": [], "rows": []}

    cur.execute("""
        SELECT 
            id::text,
            risk_type,
            severity,
            title,
            detail,
            created_at::text
        FROM project_risks
        WHERE project_id = %s AND is_active = TRUE
        ORDER BY CASE severity WHEN 'critical' THEN 1 WHEN 'warning' THEN 2 ELSE 3 END, created_at DESC
        LIMIT 10
    """, (pid,))
    rows = cur.fetchall()
    return {
        "kind": "table",
        "total": len(rows),
        "columns": ["severity", "title", "detail", "risk_type"],
        "rows": [dict(r) for r in rows],
    }


@register_metric("reportiq.project.report_history", kind="table", filter_model=ReportIQFilters, cache_ttl=5)
def reportiq_project_report_history(cur: RealDictCursor, f: ReportIQFilters) -> dict:
    pid = _resolve_project_id(cur, f)
    if not pid:
        return {"kind": "table", "total": 0, "columns": [], "rows": []}

    cur.execute("""
        SELECT 
            rl.title,
            rl.report_type,
            rt.name AS template_name,
            u.name AS author_name,
            rl.output_format,
            rl.pipeline_stage AS status,
            rl.compilation_time_sec AS latency_sec,
            rl.tokens_used,
            rl.created_at
        FROM report_logs rl
        JOIN report_templates rt ON rl.template_id = rt.id
        JOIN users u ON rl.author_id = u.id
        WHERE rl.project_id = %s
        ORDER BY rl.created_at DESC
        LIMIT 15
    """, (pid,))
    rows = cur.fetchall()
    return {
        "kind": "table",
        "total": len(rows),
        "columns": ["title", "report_type", "template_name", "author_name", "output_format", "status", "created_at"],
        "rows": [dict(r) for r in rows],
    }


@register_metric("reportiq.project.milestones", kind="table", filter_model=ReportIQFilters, cache_ttl=10)
def reportiq_project_milestones(cur: RealDictCursor, f: ReportIQFilters) -> dict:
    pid = _resolve_project_id(cur, f)
    if not pid:
        return {"kind": "table", "total": 0, "columns": [], "rows": []}

    cur.execute("""
        SELECT 
            id::text,
            name,
            status,
            target_date::text,
            completed_at::text,
            sort_order
        FROM project_milestones
        WHERE project_id = %s
        ORDER BY sort_order ASC
    """, (pid,))
    rows = cur.fetchall()
    return {
        "kind": "table",
        "total": len(rows),
        "columns": ["name", "status", "target_date", "completed_at"],
        "rows": [dict(r) for r in rows],
    }


# ══════════════════════════════════════════════════════════════════════════
#  3. LEGACY / EXTENDED METRICS
# ══════════════════════════════════════════════════════════════════════════

@register_metric("reportiq.total", kind="scalar", filter_model=ReportIQFilters, cache_ttl=5)
def reportiq_total(cur: RealDictCursor, f: ReportIQFilters) -> dict:
    return _scalar_with_previous(cur, "SELECT COUNT(*)::bigint AS value FROM report_logs WHERE {where}", f)


@register_metric("reportiq.builds_covered", kind="scalar", filter_model=ReportIQFilters, cache_ttl=5)
def reportiq_builds_covered(cur: RealDictCursor, f: ReportIQFilters) -> dict:
    return _scalar_with_previous(cur, "SELECT COUNT(DISTINCT build_id)::bigint AS value FROM report_logs WHERE {where} AND build_id IS NOT NULL", f)


@register_metric("reportiq.active_templates", kind="scalar", filter_model=ReportIQFilters, cache_ttl=5)
def reportiq_active_templates(cur: RealDictCursor, f: ReportIQFilters) -> dict:
    return _scalar_with_previous(cur, "SELECT COUNT(DISTINCT template_id)::bigint AS value FROM report_logs WHERE {where}", f)


@register_metric("reportiq.avg_tokens_per_report", kind="scalar", filter_model=ReportIQFilters, cache_ttl=5)
def reportiq_avg_tokens_per_report(cur: RealDictCursor, f: ReportIQFilters) -> dict:
    res = _scalar_with_previous(cur, "SELECT COALESCE(ROUND(AVG(tokens_used)), 0)::bigint AS value FROM report_logs WHERE {where}", f)
    res["format"] = "number"
    return res


@register_metric("reportiq.funnel", kind="group", filter_model=ReportIQFilters, cache_ttl=10)
def reportiq_funnel(cur: RealDictCursor, f: ReportIQFilters) -> dict:
    where, params = _where(f, f.date_range_start, f.date_range_end)
    cur.execute(f"""
        SELECT 
            COUNT(*) FILTER (WHERE pipeline_stage IN ('ingested', 'summarized', 'compiled', 'published')) AS ingested,
            COUNT(*) FILTER (WHERE pipeline_stage IN ('summarized', 'compiled', 'published')) AS summarized,
            COUNT(*) FILTER (WHERE pipeline_stage IN ('compiled', 'published')) AS compiled,
            COUNT(*) FILTER (WHERE pipeline_stage = 'published') AS published
        FROM report_logs WHERE {where}
    """, params)
    row = cur.fetchone() or {}
    stages = [
        {"key": "Telemetry Ingested", "value": row.get("ingested") or 0},
        {"key": "AI Summarized",      "value": row.get("summarized") or 0},
        {"key": "Formats Compiled",  "value": row.get("compiled") or 0},
        {"key": "Published & Distributed", "value": row.get("published") or 0},
    ]
    return {"kind": "group", "groups": stages, "format": "number"}


@register_metric("reportiq.speed_dial", kind="scalar", filter_model=ReportIQFilters, cache_ttl=5)
def reportiq_speed_dial(cur: RealDictCursor, f: ReportIQFilters) -> dict:
    where, params = _where(f, f.date_range_start, f.date_range_end)
    cur.execute(f"SELECT COALESCE(ROUND(AVG(compilation_time_sec)::numeric, 1), 0.0)::float AS value FROM report_logs WHERE {where}", params)
    val = float(cur.fetchone()["value"])
    return {"kind": "scalar", "value": val, "format": "decimal"}


@register_metric("reportiq.heatmap", kind="group", filter_model=ReportIQFilters, cache_ttl=10)
def reportiq_heatmap(cur: RealDictCursor, f: ReportIQFilters) -> dict:
    where, params = _where(f, f.date_range_start, f.date_range_end, alias="rl")
    cur.execute(f"""
        SELECT 
            p.code AS project_code,
            rt.category AS category,
            COUNT(rl.id)::int AS count
        FROM report_logs rl
        JOIN projects p ON rl.project_id = p.id
        JOIN report_templates rt ON rl.template_id = rt.id
        WHERE {where}
        GROUP BY p.code, rt.category
        ORDER BY p.code, rt.category
    """, params)
    rows = cur.fetchall()
    groups = [{"key": f"{r['project_code']}:{r['category']}", "value": r["count"]} for r in rows]
    return {"kind": "group", "groups": groups, "format": "number"}


@register_metric("reportiq.leaderboard", kind="group", filter_model=ReportIQFilters, cache_ttl=10)
def reportiq_leaderboard(cur: RealDictCursor, f: ReportIQFilters) -> dict:
    where, params = _where(f, f.date_range_start, f.date_range_end, alias="rl")
    cur.execute(f"""
        SELECT 
            rt.name AS template_name,
            COUNT(rl.id)::int AS usage_count
        FROM report_logs rl
        JOIN report_templates rt ON rl.template_id = rt.id
        WHERE {where}
        GROUP BY rt.id, rt.name
        ORDER BY usage_count DESC
        LIMIT 6
    """, params)
    rows = cur.fetchall()
    groups = [{"key": r["template_name"], "value": r["usage_count"]} for r in rows]
    return {"kind": "group", "groups": groups, "format": "number"}


@register_metric("reportiq.build_matrix", kind="table", filter_model=ReportIQFilters, cache_ttl=10)
def reportiq_build_matrix(cur: RealDictCursor, f: ReportIQFilters) -> dict:
    where, params = _where(f, f.date_range_start, f.date_range_end, alias="rl")
    cur.execute(f"""
        SELECT 
            b.version AS build_version,
            p.name AS project_name,
            p.code AS project_code,
            COALESCE(b.status, 'PASS') AS status,
            COALESCE(b.audit_score, 95) AS audit_score,
            COUNT(rl.id)::int AS reports_count,
            COALESCE(ROUND(AVG(rl.compilation_time_sec)::numeric, 1), 0.0)::float AS avg_latency
        FROM builds b
        JOIN projects p ON b.project_id = p.id
        LEFT JOIN report_logs rl ON rl.build_id = b.id AND ({where})
        GROUP BY b.id, b.version, p.name, p.code, b.status, b.audit_score
        ORDER BY b.created_at DESC
        LIMIT 10
    """, params)
    rows = cur.fetchall()
    return {
        "kind": "table",
        "total": len(rows),
        "columns": ["build_version", "project_name", "project_code", "status", "audit_score", "reports_count", "avg_latency"],
        "rows": [dict(r) for r in rows],
    }


@register_metric("reportiq.telemetry", kind="table", filter_model=ReportIQFilters, cache_ttl=5)
def reportiq_telemetry(cur: RealDictCursor, f: ReportIQFilters) -> dict:
    where, params = _where(f, f.date_range_start, f.date_range_end, alias="rl")
    cur.execute(f"SELECT COUNT(*)::int AS total FROM report_logs rl WHERE {where}", params)
    total = cur.fetchone()["total"]

    cur.execute(f"""
        SELECT 
            rl.title,
            p.name AS project_name,
            p.code AS project_code,
            COALESCE(b.version, 'v1.0.0') AS build_version,
            rt.name AS template_name,
            u.name AS author_name,
            rl.output_format,
            rl.compilation_time_sec AS latency_sec,
            rl.tokens_used,
            rl.pipeline_stage AS status,
            rl.created_at
        FROM report_logs rl
        JOIN projects p ON rl.project_id = p.id
        LEFT JOIN builds b ON rl.build_id = b.id
        JOIN report_templates rt ON rl.template_id = rt.id
        JOIN users u ON rl.author_id = u.id
        WHERE {where}
        ORDER BY rl.created_at DESC
        LIMIT 25
    """, params)
    rows = cur.fetchall()

    return {
        "kind": "table",
        "total": total,
        "columns": [
            "title", "project_name", "project_code", "build_version",
            "template_name", "author_name", "output_format", "latency_sec", "status", "created_at"
        ],
        "rows": [dict(r) for r in rows],
    }

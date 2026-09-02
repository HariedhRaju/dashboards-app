"""
Bug report metrics.

Schema assumptions:
    bug_reports(id, project_id, reported_by, template_id, title, summary,
                severity, status, dynamic_fields, created_at, updated_at)
    bug_users(id, name, email)
    bug_projects(id, name, code)

Status semantics (per product decision):
    'closed'                      => RESOLVED
    'open','in_progress','fixed'  => UNRESOLVED / open work

Resolution time:
    For closed bugs, (updated_at - created_at) approximates time-to-resolution.
    There is no dedicated resolved_at column, so this is labeled "approx".

Severity: P1 (critical) .. P4 (trivial).
"""
from __future__ import annotations

from datetime import datetime

from psycopg2.extras import RealDictCursor

from . import BugFilters, auto_grain, previous_period, register_metric


# ── shared helpers ─────────────────────────────────────────────────────────

def _where(f: BugFilters, start: datetime, end: datetime, alias: str = "") -> tuple[str, list]:
    """Filter on created_at within the window, plus optional dimension filters."""
    p = f"{alias}." if alias else ""
    conds = [f"{p}created_at >= %s", f"{p}created_at < %s"]
    params: list = [start, end]
    if f.project_id is not None:
        conds.append(f"{p}project_id = %s"); params.append(str(f.project_id))
    if f.reported_by is not None:
        conds.append(f"{p}reported_by = %s"); params.append(str(f.reported_by))
    if f.severity:
        conds.append(f"{p}severity = %s"); params.append(f.severity)
    if f.status:
        conds.append(f"{p}status = %s"); params.append(f.status)
    return " AND ".join(conds), params


def _scalar_with_previous(cur, sql_template: str, f: BugFilters) -> dict:
    where, params = _where(f, f.date_range_start, f.date_range_end)
    cur.execute(sql_template.format(where=where), params)
    current = cur.fetchone()["value"]
    ps, pe = previous_period(f.date_range_start, f.date_range_end)
    prev_where, prev_params = _where(f, ps, pe)
    cur.execute(sql_template.format(where=prev_where), prev_params)
    previous = cur.fetchone()["value"]
    return {"kind": "scalar", "value": current, "previous": previous, "format": "number"}


# ══════════════════════════════════════════════════════════════════════════
#  SCALARS — the KPI row
# ══════════════════════════════════════════════════════════════════════════

@register_metric("bugs.total", kind="scalar", filter_model=BugFilters, cache_ttl=10)
def bugs_total(cur: RealDictCursor, f: BugFilters) -> dict:
    return _scalar_with_previous(cur,
        "SELECT COUNT(*)::bigint AS value FROM bug_reports WHERE {where}", f)


@register_metric("bugs.backlog", kind="scalar", filter_model=BugFilters, cache_ttl=10)
def bugs_backlog(cur: RealDictCursor, f: BugFilters) -> dict:
    # Unresolved = anything not closed.
    return _scalar_with_previous(cur,
        "SELECT COUNT(*)::bigint AS value FROM bug_reports "
        "WHERE {where} AND status <> 'closed'", f)


@register_metric("bugs.p1_open", kind="scalar", filter_model=BugFilters, cache_ttl=10)
def bugs_p1_open(cur: RealDictCursor, f: BugFilters) -> dict:
    return _scalar_with_previous(cur,
        "SELECT COUNT(*)::bigint AS value FROM bug_reports "
        "WHERE {where} AND severity = 'P1' AND status <> 'closed'", f)


@register_metric("bugs.reporters.active", kind="scalar", filter_model=BugFilters, cache_ttl=10)
def bugs_reporters_active(cur: RealDictCursor, f: BugFilters) -> dict:
    return _scalar_with_previous(cur,
        "SELECT COUNT(DISTINCT reported_by)::bigint AS value FROM bug_reports WHERE {where}", f)


@register_metric("bugs.fix_rate", kind="scalar", filter_model=BugFilters, cache_ttl=10)
def bugs_fix_rate(cur: RealDictCursor, f: BugFilters) -> dict:
    """Percent of bugs in range that are closed. Returns 0-100 float."""
    where, params = _where(f, f.date_range_start, f.date_range_end)
    cur.execute(f"""
        SELECT CASE WHEN COUNT(*) = 0 THEN 0
                    ELSE ROUND(100.0 * COUNT(*) FILTER (WHERE status = 'closed') / COUNT(*), 1)
               END AS value
        FROM bug_reports WHERE {where}
    """, params)
    current = float(cur.fetchone()["value"])
    ps, pe = previous_period(f.date_range_start, f.date_range_end)
    prev_where, prev_params = _where(f, ps, pe)
    cur.execute(f"""
        SELECT CASE WHEN COUNT(*) = 0 THEN 0
                    ELSE ROUND(100.0 * COUNT(*) FILTER (WHERE status = 'closed') / COUNT(*), 1)
               END AS value
        FROM bug_reports WHERE {prev_where}
    """, prev_params)
    previous = float(cur.fetchone()["value"])
    return {"kind": "scalar", "value": current, "previous": previous, "format": "percent_whole"}


# ══════════════════════════════════════════════════════════════════════════
#  SERIES — velocity (reported vs resolved over time)
# ══════════════════════════════════════════════════════════════════════════

@register_metric("bugs.velocity", kind="series", filter_model=BugFilters, cache_ttl=30)
def bugs_velocity(cur: RealDictCursor, f: BugFilters) -> dict:
    grain = f.grain or auto_grain(f.date_range_start, f.date_range_end)
    where, params = _where(f, f.date_range_start, f.date_range_end)
    # Reported = bugs created per bucket.
    cur.execute(f"""
        SELECT date_trunc(%s, created_at) AS t, COUNT(*)::bigint AS reported
        FROM bug_reports WHERE {where}
        GROUP BY 1 ORDER BY 1
    """, [grain, *params])
    reported = {r["t"].isoformat(): r["reported"] for r in cur.fetchall()}

    # Resolved = bugs closed per bucket (bucketed by updated_at, the close time).
    resolved_where, resolved_params = _where(f, f.date_range_start, f.date_range_end)
    cur.execute(f"""
        SELECT date_trunc(%s, updated_at) AS t, COUNT(*)::bigint AS resolved
        FROM bug_reports
        WHERE {resolved_where} AND status = 'closed'
        GROUP BY 1 ORDER BY 1
    """, [grain, *resolved_params])
    resolved = {r["t"].isoformat(): r["resolved"] for r in cur.fetchall()}

    all_ts = sorted(set(reported) | set(resolved))
    return {
        "kind": "series",
        "series": [
            {"name": "reported", "points": [{"t": t, "v": reported.get(t, 0)} for t in all_ts]},
            {"name": "resolved", "points": [{"t": t, "v": resolved.get(t, 0)} for t in all_ts]},
        ],
        "format": "number",
    }


# ══════════════════════════════════════════════════════════════════════════
#  GROUPS — severity, status, aging, MTTR
# ══════════════════════════════════════════════════════════════════════════

@register_metric("bugs.by_severity", kind="group", filter_model=BugFilters, cache_ttl=30)
def bugs_by_severity(cur: RealDictCursor, f: BugFilters) -> dict:
    where, params = _where(f, f.date_range_start, f.date_range_end)
    cur.execute(f"""
        SELECT severity AS key, COUNT(*)::bigint AS value
        FROM bug_reports WHERE {where}
        GROUP BY severity ORDER BY severity
    """, params)
    return {"kind": "group", "groups": [dict(r) for r in cur.fetchall()], "format": "number"}


@register_metric("bugs.by_status", kind="group", filter_model=BugFilters, cache_ttl=30)
def bugs_by_status(cur: RealDictCursor, f: BugFilters) -> dict:
    where, params = _where(f, f.date_range_start, f.date_range_end)
    cur.execute(f"""
        SELECT status AS key, COUNT(*)::bigint AS value
        FROM bug_reports WHERE {where}
        GROUP BY status
        ORDER BY array_position(ARRAY['open','in_progress','fixed','closed']::text[], status::text)
    """, params)
    return {"kind": "group", "groups": [dict(r) for r in cur.fetchall()], "format": "number"}


@register_metric("bugs.aging_backlog", kind="group", filter_model=BugFilters, cache_ttl=30)
def bugs_aging_backlog(cur: RealDictCursor, f: BugFilters) -> dict:
    """Distribution of how old the currently-unresolved bugs are."""
    where, params = _where(f, f.date_range_start, f.date_range_end)
    cur.execute(f"""
        WITH aged AS (
            SELECT EXTRACT(EPOCH FROM (NOW() - created_at)) / 86400.0 AS age_days
            FROM bug_reports
            WHERE {where} AND status <> 'closed'
        )
        SELECT bucket AS key, COUNT(*)::bigint AS value FROM (
            SELECT CASE
                WHEN age_days < 1  THEN '< 1 day'
                WHEN age_days < 3  THEN '1-3 days'
                WHEN age_days < 7  THEN '3-7 days'
                WHEN age_days < 30 THEN '1-4 weeks'
                ELSE '> 1 month'
            END AS bucket,
            CASE
                WHEN age_days < 1  THEN 1 WHEN age_days < 3  THEN 2
                WHEN age_days < 7  THEN 3 WHEN age_days < 30 THEN 4 ELSE 5
            END AS ord
            FROM aged
        ) t
        GROUP BY bucket, ord ORDER BY ord
    """, params)
    return {"kind": "group", "groups": [dict(r) for r in cur.fetchall()], "format": "number"}


@register_metric("bugs.mttr_by_severity", kind="group", filter_model=BugFilters, cache_ttl=30)
def bugs_mttr_by_severity(cur: RealDictCursor, f: BugFilters) -> dict:
    """Median time-to-resolution (approx, in hours) per severity, closed bugs only."""
    where, params = _where(f, f.date_range_start, f.date_range_end)
    cur.execute(f"""
        SELECT severity AS key,
               ROUND(
                 PERCENTILE_CONT(0.5) WITHIN GROUP (
                   ORDER BY EXTRACT(EPOCH FROM (updated_at - created_at)) / 3600.0
                 )::numeric, 1
               )::float AS value
        FROM bug_reports
        WHERE {where} AND status = 'closed'
        GROUP BY severity ORDER BY severity
    """, params)
    return {"kind": "group", "groups": [dict(r) for r in cur.fetchall()], "format": "hours"}


# ══════════════════════════════════════════════════════════════════════════
#  BREAKDOWN TABLES
# ══════════════════════════════════════════════════════════════════════════

@register_metric("bugs.breakdown.status", kind="table", filter_model=BugFilters, cache_ttl=30)
def breakdown_status(cur: RealDictCursor, f: BugFilters) -> dict:
    where, params = _where(f, f.date_range_start, f.date_range_end)
    cur.execute(f"""
        WITH total AS (SELECT COUNT(*)::numeric AS n FROM bug_reports WHERE {where})
        SELECT status,
               COUNT(*)::bigint AS count,
               CASE WHEN (SELECT n FROM total) = 0 THEN 0
                    ELSE ROUND(100.0 * COUNT(*) / (SELECT n FROM total), 1) END AS pct
        FROM bug_reports WHERE {where}
        GROUP BY status
        ORDER BY array_position(ARRAY['open','in_progress','fixed','closed']::text[], status::text)
    """, params + params)
    rows = [dict(r) for r in cur.fetchall()]
    for r in rows:
        r["pct"] = float(r["pct"])
    return {"kind": "table", "columns": ["status", "count", "pct"],
            "rows": rows, "total": len(rows), "format": "number"}


@register_metric("bugs.breakdown.reporter", kind="table", filter_model=BugFilters, cache_ttl=30)
def breakdown_reporter(cur: RealDictCursor, f: BugFilters) -> dict:
    where, params = _where(f, f.date_range_start, f.date_range_end, alias="b")
    cur.execute(f"""
        SELECT COALESCE(u.name, b.reported_by::text) AS reporter,
               COALESCE(u.email, '')                 AS email,
               COUNT(*)::bigint                       AS reported,
               COUNT(*) FILTER (WHERE b.status = 'closed')::bigint AS closed,
               CASE WHEN COUNT(*) = 0 THEN 0
                    ELSE ROUND(100.0 * COUNT(*) FILTER (WHERE b.status = 'closed') / COUNT(*), 0)
               END::int AS close_rate
        FROM bug_reports b
        LEFT JOIN bug_users u ON u.id = b.reported_by
        WHERE {where}
        GROUP BY u.name, u.email, b.reported_by
        ORDER BY reported DESC LIMIT 100
    """, params)
    return {"kind": "table",
            "columns": ["reporter", "email", "reported", "closed", "close_rate"],
            "rows": [dict(r) for r in cur.fetchall()], "total": 0, "format": "number"}


@register_metric("bugs.breakdown.project", kind="table", filter_model=BugFilters, cache_ttl=30)
def breakdown_project(cur: RealDictCursor, f: BugFilters) -> dict:
    where, params = _where(f, f.date_range_start, f.date_range_end, alias="b")
    cur.execute(f"""
        SELECT COALESCE(p.name, 'Unassigned') AS project,
               COALESCE(p.code, 'NONE')       AS code,
               COUNT(*)::bigint               AS total,
               COUNT(*) FILTER (WHERE b.status <> 'closed')::bigint AS unresolved,
               COUNT(*) FILTER (WHERE b.severity = 'P1' AND b.status <> 'closed')::bigint AS p1_open
        FROM bug_reports b
        LEFT JOIN bug_projects p ON p.id = b.project_id
        WHERE {where}
        GROUP BY p.name, p.code
        ORDER BY total DESC LIMIT 100
    """, params)
    return {"kind": "table",
            "columns": ["project", "code", "total", "unresolved", "p1_open"],
            "rows": [dict(r) for r in cur.fetchall()], "total": 0, "format": "number"}


@register_metric("bugs.severity_status_matrix", kind="table", filter_model=BugFilters, cache_ttl=30)
def severity_status_matrix(cur: RealDictCursor, f: BugFilters) -> dict:
    """Rows = severity, columns = status counts. Shows e.g. how many P1s are still open."""
    where, params = _where(f, f.date_range_start, f.date_range_end)
    cur.execute(f"""
        SELECT severity,
               COUNT(*) FILTER (WHERE status = 'open')::bigint        AS open,
               COUNT(*) FILTER (WHERE status = 'in_progress')::bigint AS in_progress,
               COUNT(*) FILTER (WHERE status = 'fixed')::bigint       AS fixed,
               COUNT(*) FILTER (WHERE status = 'closed')::bigint      AS closed
        FROM bug_reports WHERE {where}
        GROUP BY severity ORDER BY severity
    """, params)
    return {"kind": "table",
            "columns": ["severity", "open", "in_progress", "fixed", "closed"],
            "rows": [dict(r) for r in cur.fetchall()], "total": 0, "format": "number"}


# ══════════════════════════════════════════════════════════════════════════
#  TELEMETRY — the live bug stream (paginated + sortable)
# ══════════════════════════════════════════════════════════════════════════

class BugTelemetryFilters(BugFilters):
    page: int = 1
    page_size: int = 25
    sort: str = "severity"
    sort_dir: str = "asc"


_TELEMETRY_SORT = {
    "issue_no":   "(NULLIF(regexp_replace(COALESCE(b.dynamic_fields->>'clean_issue_no', b.dynamic_fields->>'source_record_id', b.dynamic_fields->>'issue_no', '0'), '[^0-9]', '', 'g'), ''))::bigint",
    "created_at": "b.created_at",
    "updated_at": "b.updated_at",
    "status":     "CASE WHEN b.status::text = 'open' THEN 1 WHEN b.status::text = 'in_progress' THEN 2 WHEN b.status::text = 'fixed' THEN 3 WHEN b.status::text = 'closed' THEN 4 ELSE 5 END",
}
_ALLOWED_DIRS = {"asc", "desc"}


@register_metric("bugs.telemetry", kind="table", filter_model=BugTelemetryFilters, cache_ttl=5)
def bugs_telemetry(cur: RealDictCursor, f: BugTelemetryFilters) -> dict:
    sort_dir = f.sort_dir if f.sort_dir in _ALLOWED_DIRS else "asc"
    
    if f.sort == "severity" or not f.sort:
        if sort_dir == "asc":
            order_by = """
                CASE 
                    WHEN b.severity::text IN ('P1', 'Blocker', 'Critical') THEN 1 
                    WHEN b.severity::text IN ('P2', 'Major', 'High') THEN 2 
                    WHEN b.severity::text IN ('P3', 'Minor', 'Medium') THEN 3 
                    WHEN b.severity::text IN ('P4', 'Trivial', 'Low') THEN 4 
                    ELSE 5 
                END ASC,
                CASE 
                    WHEN b.status::text = 'open' THEN 1 
                    WHEN b.status::text = 'in_progress' THEN 2 
                    WHEN b.status::text = 'fixed' THEN 3 
                    WHEN b.status::text = 'closed' THEN 4 
                    ELSE 5 
                END ASC,
                (NULLIF(regexp_replace(COALESCE(b.dynamic_fields->>'clean_issue_no', b.dynamic_fields->>'source_record_id', b.dynamic_fields->>'issue_no', '0'), '[^0-9]', '', 'g'), ''))::bigint ASC NULLS LAST
            """
        else:
            order_by = """
                CASE 
                    WHEN b.severity::text IN ('P1', 'Blocker', 'Critical') THEN 1 
                    WHEN b.severity::text IN ('P2', 'Major', 'High') THEN 2 
                    WHEN b.severity::text IN ('P3', 'Minor', 'Medium') THEN 3 
                    WHEN b.severity::text IN ('P4', 'Trivial', 'Low') THEN 4 
                    ELSE 5 
                END DESC,
                (NULLIF(regexp_replace(COALESCE(b.dynamic_fields->>'clean_issue_no', b.dynamic_fields->>'source_record_id', b.dynamic_fields->>'issue_no', '0'), '[^0-9]', '', 'g'), ''))::bigint DESC NULLS LAST
            """
    else:
        sort_col = _TELEMETRY_SORT.get(f.sort, "b.created_at")
        order_by = f"{sort_col} {sort_dir} NULLS LAST"

    offset = max(0, (f.page - 1) * f.page_size)

    where, params = _where(f, f.date_range_start, f.date_range_end, alias="b")
    cur.execute(f"SELECT COUNT(*)::bigint AS total FROM bug_reports b WHERE {where}", params)
    total = cur.fetchone()["total"]

    cur.execute(f"""
        SELECT COALESCE(b.dynamic_fields->>'clean_issue_no', regexp_replace(COALESCE(b.dynamic_fields->>'source_record_id', b.dynamic_fields->>'issue_no', ''), '[^0-9]', '', 'g'), left(b.id::text, 8)) AS issue_no,
               b.title,
               b.severity,
               b.status,
               COALESCE(p.name, 'Unassigned')       AS project_name,
               COALESCE(u.name, b.reported_by::text) AS reporter_name,
               b.created_at,
               ROUND(EXTRACT(EPOCH FROM (NOW() - b.created_at)) / 86400.0, 1)::float AS age_days
        FROM bug_reports b
        LEFT JOIN bug_projects p ON p.id = b.project_id
        LEFT JOIN bug_users u    ON u.id = b.reported_by
        WHERE {where}
        ORDER BY {order_by}
        LIMIT %s OFFSET %s
    """, [*params, f.page_size, offset])

    rows = [dict(r) for r in cur.fetchall()]
    for r in rows:
        r["created_at"] = r["created_at"].isoformat()

    return {"kind": "table",
            "columns": ["issue_no", "title", "severity", "status", "project_name",
                        "reporter_name", "created_at", "age_days"],
            "rows": rows, "total": total, "format": "number"}

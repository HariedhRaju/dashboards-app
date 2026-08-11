"""
Metric definitions.

Schema assumptions:
    token_usage(id, timestamp, user_id, project_id, feature, model_name,
                prompt_tokens, completion_tokens, total_tokens)
    users(id, name, email)
    projects(id, name, code)
"""
from __future__ import annotations

from datetime import datetime
from typing import Iterable

from psycopg2.extras import RealDictCursor

from . import TokenFilters, auto_grain, previous_period, register_metric


# ── shared helpers ─────────────────────────────────────────────────────────

def _where(f: TokenFilters, start: datetime, end: datetime, alias: str = "") -> tuple[str, list]:
    p = f"{alias}." if alias else ""
    conds = [f"{p}timestamp >= %s", f"{p}timestamp < %s"]
    params: list = [start, end]
    if f.user_id is not None:
        conds.append(f"{p}user_id = %s"); params.append(str(f.user_id))
    if f.project_id is not None:
        conds.append(f"{p}project_id = %s"); params.append(str(f.project_id))
    if f.model_name:
        conds.append(f"{p}model_name = %s"); params.append(f.model_name)
    if f.feature:
        conds.append(f"{p}feature = %s"); params.append(f.feature)
    return " AND ".join(conds), params


def _top_n_with_other(rows: Iterable[dict], n: int = 10) -> list[dict]:
    rows = list(rows)
    if len(rows) <= n:
        return rows
    top = rows[:n]
    other_total = sum(r["value"] for r in rows[n:])
    if other_total > 0:
        top.append({"key": "Other", "value": other_total})
    return top


def _scalar_with_previous(cur, sql_template: str, f: TokenFilters) -> dict:
    """Run the same aggregation for current + previous period; return a scalar response."""
    where, params = _where(f, f.date_range_start, f.date_range_end)
    cur.execute(sql_template.format(where=where), params)
    current = cur.fetchone()["value"]

    ps, pe = previous_period(f.date_range_start, f.date_range_end)
    prev_where, prev_params = _where(f, ps, pe)
    cur.execute(sql_template.format(where=prev_where), prev_params)
    previous = cur.fetchone()["value"]

    return {"kind": "scalar", "value": current, "previous": previous, "format": "number"}


# ══════════════════════════════════════════════════════════════════════════
#  SCALARS — the 4 headline KPIs + backups
# ══════════════════════════════════════════════════════════════════════════

@register_metric("tokens.total", kind="scalar", filter_model=TokenFilters, cache_ttl=5)
def tokens_total(cur: RealDictCursor, f: TokenFilters) -> dict:
    return _scalar_with_previous(cur,
        "SELECT COALESCE(SUM(total_tokens), 0)::bigint AS value FROM token_usage WHERE {where}", f)


@register_metric("tokens.prompt", kind="scalar", filter_model=TokenFilters, cache_ttl=5)
def tokens_prompt(cur: RealDictCursor, f: TokenFilters) -> dict:
    return _scalar_with_previous(cur,
        "SELECT COALESCE(SUM(prompt_tokens), 0)::bigint AS value FROM token_usage WHERE {where}", f)


@register_metric("tokens.completion", kind="scalar", filter_model=TokenFilters, cache_ttl=5)
def tokens_completion(cur: RealDictCursor, f: TokenFilters) -> dict:
    return _scalar_with_previous(cur,
        "SELECT COALESCE(SUM(completion_tokens), 0)::bigint AS value FROM token_usage WHERE {where}", f)


@register_metric("tokens.requests", kind="scalar", filter_model=TokenFilters, cache_ttl=5)
def tokens_requests(cur: RealDictCursor, f: TokenFilters) -> dict:
    return _scalar_with_previous(cur,
        "SELECT COUNT(*)::bigint AS value FROM token_usage WHERE {where}", f)


@register_metric("tokens.avg_per_call", kind="scalar", filter_model=TokenFilters, cache_ttl=5)
def tokens_avg_per_call(cur: RealDictCursor, f: TokenFilters) -> dict:
    result = _scalar_with_previous(cur,
        "SELECT COALESCE(AVG(total_tokens), 0)::float AS value FROM token_usage WHERE {where}", f)
    result["value"] = round(float(result["value"]), 2)
    result["previous"] = round(float(result["previous"]), 2) if result["previous"] is not None else None
    return result


@register_metric("tokens.users.active", kind="scalar", filter_model=TokenFilters, cache_ttl=5)
def tokens_users_active(cur: RealDictCursor, f: TokenFilters) -> dict:
    return _scalar_with_previous(cur,
        "SELECT COUNT(DISTINCT user_id)::bigint AS value FROM token_usage WHERE {where}", f)


# ══════════════════════════════════════════════════════════════════════════
#  SERIES — usage over time (prompt + completion, stacked)
# ══════════════════════════════════════════════════════════════════════════

@register_metric("tokens.timeseries", kind="series", filter_model=TokenFilters, cache_ttl=15)
def tokens_timeseries(cur: RealDictCursor, f: TokenFilters) -> dict:
    grain = f.grain or auto_grain(f.date_range_start, f.date_range_end)
    where, params = _where(f, f.date_range_start, f.date_range_end)
    cur.execute(f"""
        SELECT date_trunc(%s, timestamp) AS t,
               COALESCE(SUM(prompt_tokens), 0)::bigint AS prompt,
               COALESCE(SUM(completion_tokens), 0)::bigint AS completion
        FROM token_usage WHERE {where}
        GROUP BY 1 ORDER BY 1
    """, [grain, *params])
    rows = cur.fetchall()
    return {
        "kind": "series",
        "series": [
            {"name": "prompt",     "points": [{"t": r["t"].isoformat(), "v": r["prompt"]}     for r in rows]},
            {"name": "completion", "points": [{"t": r["t"].isoformat(), "v": r["completion"]} for r in rows]},
        ],
        "format": "number",
    }


# ══════════════════════════════════════════════════════════════════════════
#  GROUPS — kept for donut/bar variants if you want them later
# ══════════════════════════════════════════════════════════════════════════

def _group_query(cur, f: TokenFilters, sql: str, alias: str = "") -> dict:
    where, params = _where(f, f.date_range_start, f.date_range_end, alias=alias)
    cur.execute(sql.format(where=where), params)
    rows = [dict(r) for r in cur.fetchall()]
    return {"kind": "group", "groups": _top_n_with_other(rows), "format": "number"}


@register_metric("tokens.by_model", kind="group", filter_model=TokenFilters, cache_ttl=15)
def tokens_by_model(cur: RealDictCursor, f: TokenFilters) -> dict:
    return _group_query(cur, f, """
        SELECT COALESCE(model_name, 'unknown') AS key,
               COALESCE(SUM(total_tokens), 0)::bigint AS value
        FROM token_usage WHERE {where}
        GROUP BY model_name ORDER BY value DESC
    """)


@register_metric("tokens.by_feature", kind="group", filter_model=TokenFilters, cache_ttl=15)
def tokens_by_feature(cur: RealDictCursor, f: TokenFilters) -> dict:
    return _group_query(cur, f, """
        SELECT COALESCE(feature, 'unknown') AS key,
               COALESCE(SUM(total_tokens), 0)::bigint AS value
        FROM token_usage WHERE {where}
        GROUP BY feature ORDER BY value DESC
    """)


@register_metric("tokens.by_project", kind="group", filter_model=TokenFilters, cache_ttl=15)
def tokens_by_project(cur: RealDictCursor, f: TokenFilters) -> dict:
    return _group_query(cur, f, """
        SELECT COALESCE(p.name, tu.project_id::text) AS key,
               COALESCE(SUM(tu.total_tokens), 0)::bigint AS value
        FROM token_usage tu
        LEFT JOIN projects p ON p.id = tu.project_id
        WHERE {where}
        GROUP BY tu.project_id, p.name ORDER BY value DESC LIMIT 20
    """, alias="tu")


# ══════════════════════════════════════════════════════════════════════════
#  BREAKDOWN TABLES — the primary content of the new dashboard
# ══════════════════════════════════════════════════════════════════════════

@register_metric("tokens.breakdown.feature", kind="table", filter_model=TokenFilters, cache_ttl=15)
def breakdown_feature(cur: RealDictCursor, f: TokenFilters) -> dict:
    where, params = _where(f, f.date_range_start, f.date_range_end)
    cur.execute(f"""
        SELECT COALESCE(feature, 'unknown') AS feature,
               COUNT(*)::bigint AS requests,
               COALESCE(SUM(prompt_tokens), 0)::bigint AS prompt_tokens,
               COALESCE(SUM(completion_tokens), 0)::bigint AS completion_tokens,
               COALESCE(SUM(total_tokens), 0)::bigint AS total_tokens
        FROM token_usage WHERE {where}
        GROUP BY feature ORDER BY total_tokens DESC
    """, params)
    rows = [dict(r) for r in cur.fetchall()]
    return {
        "kind": "table",
        "columns": ["feature", "requests", "prompt_tokens", "completion_tokens", "total_tokens"],
        "rows": rows,
        "total": len(rows),
        "format": "number",
    }


@register_metric("tokens.breakdown.model", kind="table", filter_model=TokenFilters, cache_ttl=15)
def breakdown_model(cur: RealDictCursor, f: TokenFilters) -> dict:
    where, params = _where(f, f.date_range_start, f.date_range_end)
    cur.execute(f"""
        SELECT COALESCE(model_name, 'unknown') AS model_name,
               COUNT(*)::bigint AS requests,
               COALESCE(SUM(prompt_tokens), 0)::bigint AS prompt_tokens,
               COALESCE(SUM(completion_tokens), 0)::bigint AS completion_tokens,
               COALESCE(SUM(total_tokens), 0)::bigint AS total_tokens
        FROM token_usage WHERE {where}
        GROUP BY model_name ORDER BY total_tokens DESC
    """, params)
    rows = [dict(r) for r in cur.fetchall()]
    return {
        "kind": "table",
        "columns": ["model_name", "requests", "prompt_tokens", "completion_tokens", "total_tokens"],
        "rows": rows,
        "total": len(rows),
        "format": "number",
    }


@register_metric("tokens.breakdown.project", kind="table", filter_model=TokenFilters, cache_ttl=15)
def breakdown_project(cur: RealDictCursor, f: TokenFilters) -> dict:
    where, params = _where(f, f.date_range_start, f.date_range_end, alias="tu")
    cur.execute(f"""
        SELECT COALESCE(p.name, 'Unassigned')       AS project_name,
               COALESCE(p.code, 'NONE')             AS project_code,
               COUNT(*)::bigint                     AS requests,
               COALESCE(SUM(tu.prompt_tokens), 0)::bigint     AS prompt_tokens,
               COALESCE(SUM(tu.completion_tokens), 0)::bigint AS completion_tokens,
               COALESCE(SUM(tu.total_tokens), 0)::bigint      AS total_tokens
        FROM token_usage tu
        LEFT JOIN projects p ON p.id = tu.project_id
        WHERE {where}
        GROUP BY p.name, p.code ORDER BY total_tokens DESC
    """, params)
    rows = [dict(r) for r in cur.fetchall()]
    return {
        "kind": "table",
        "columns": ["project_name", "project_code", "requests", "prompt_tokens", "completion_tokens", "total_tokens"],
        "rows": rows,
        "total": len(rows),
        "format": "number",
    }


@register_metric("tokens.breakdown.user", kind="table", filter_model=TokenFilters, cache_ttl=15)
def breakdown_user(cur: RealDictCursor, f: TokenFilters) -> dict:
    where, params = _where(f, f.date_range_start, f.date_range_end, alias="tu")
    cur.execute(f"""
        SELECT COALESCE(u.name, tu.user_id::text)   AS user_name,
               COALESCE(u.email, '')                AS user_email,
               COUNT(*)::bigint                     AS requests,
               COALESCE(SUM(tu.prompt_tokens), 0)::bigint     AS prompt_tokens,
               COALESCE(SUM(tu.completion_tokens), 0)::bigint AS completion_tokens,
               COALESCE(SUM(tu.total_tokens), 0)::bigint      AS total_tokens
        FROM token_usage tu
        LEFT JOIN users u ON u.id = tu.user_id
        WHERE {where}
        GROUP BY u.name, u.email, tu.user_id ORDER BY total_tokens DESC LIMIT 100
    """, params)
    rows = [dict(r) for r in cur.fetchall()]
    return {
        "kind": "table",
        "columns": ["user_name", "user_email", "requests", "prompt_tokens", "completion_tokens", "total_tokens"],
        "rows": rows,
        "total": len(rows),
        "format": "number",
    }


# ══════════════════════════════════════════════════════════════════════════
#  INVOCATIONS — recent feed (compact) + full paginated log
# ══════════════════════════════════════════════════════════════════════════

def _invocations_query(cur, f: TokenFilters, limit: int, offset: int,
                       sort_col: str, sort_dir: str) -> list[dict]:
    where, params = _where(f, f.date_range_start, f.date_range_end, alias="tu")
    cur.execute(f"""
        SELECT tu.timestamp,
               COALESCE(tu.feature, 'unknown')      AS feature,
               COALESCE(tu.model_name, 'unknown')   AS model_name,
               COALESCE(u.name, tu.user_id::text)   AS user_name,
               COALESCE(p.name, 'Unassigned')       AS project_name,
               tu.prompt_tokens,
               tu.completion_tokens,
               tu.total_tokens
        FROM token_usage tu
        LEFT JOIN users u    ON u.id = tu.user_id
        LEFT JOIN projects p ON p.id = tu.project_id
        WHERE {where}
        ORDER BY {sort_col} {sort_dir}
        LIMIT %s OFFSET %s
    """, [*params, limit, offset])
    rows = [dict(r) for r in cur.fetchall()]
    for r in rows:
        r["timestamp"] = r["timestamp"].isoformat()
    return rows


@register_metric("tokens.recent", kind="table", filter_model=TokenFilters, cache_ttl=5)
def tokens_recent(cur: RealDictCursor, f: TokenFilters) -> dict:
    """Compact live feed — 8 most recent rows, no pagination."""
    rows = _invocations_query(cur, f, limit=8, offset=0, sort_col="tu.timestamp", sort_dir="desc")
    return {
        "kind": "table",
        "columns": ["timestamp", "feature", "user_name", "total_tokens"],
        "rows": [{k: r[k] for k in ["timestamp", "feature", "user_name", "total_tokens"]} for r in rows],
        "total": len(rows),
        "format": "number",
    }


class InvocationsFilters(TokenFilters):
    page: int = 1
    page_size: int = 25
    sort: str = "timestamp"
    sort_dir: str = "desc"


_INVOCATIONS_SORT_COLS = {
    "timestamp":         "tu.timestamp",
    "prompt_tokens":     "tu.prompt_tokens",
    "completion_tokens": "tu.completion_tokens",
    "total_tokens":      "tu.total_tokens",
}
_ALLOWED_DIRS = {"asc", "desc"}


@register_metric("tokens.invocations", kind="table", filter_model=InvocationsFilters, cache_ttl=5)
def tokens_invocations(cur: RealDictCursor, f: InvocationsFilters) -> dict:
    """Full paginated + sortable invocations log — replaces top_consumers."""
    sort_col = _INVOCATIONS_SORT_COLS.get(f.sort, "tu.timestamp")
    sort_dir = f.sort_dir if f.sort_dir in _ALLOWED_DIRS else "desc"
    offset = max(0, (f.page - 1) * f.page_size)

    where, params = _where(f, f.date_range_start, f.date_range_end, alias="tu")
    cur.execute(f"SELECT COUNT(*)::bigint AS total FROM token_usage tu WHERE {where}", params)
    total = cur.fetchone()["total"]

    rows = _invocations_query(cur, f, limit=f.page_size, offset=offset,
                              sort_col=sort_col, sort_dir=sort_dir)
    return {
        "kind": "table",
        "columns": ["timestamp", "feature", "model_name", "user_name", "project_name",
                    "prompt_tokens", "completion_tokens", "total_tokens"],
        "rows": rows,
        "total": total,
        "format": "number",
    }

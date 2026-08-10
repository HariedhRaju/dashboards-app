"""
Metric definitions.

Every metric is a self-contained function decorated with @register_metric.
Adding a metric is one function; adding a domain (e.g. "billing") is a
comment section below the existing ones — no separate file needed unless
this file grows past ~500 lines.

Schema assumptions:
    token_usage(id, timestamp, user_id, project_id, feature, model_name,
                prompt_tokens, completion_tokens, total_tokens)
    users(id, name)      -- adjust `u.name` below if your column differs
    projects(id, name)   -- same for `p.name`
"""
from __future__ import annotations

from datetime import datetime
from typing import Iterable

from psycopg2.extras import RealDictCursor

from . import TokenFilters, auto_grain, previous_period, register_metric


# ── shared helpers ─────────────────────────────────────────────────────────

def _where(f: TokenFilters, start: datetime, end: datetime, alias: str = "") -> tuple[str, list]:
    """Build WHERE + params. Pass alias='tu' when joining."""
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


def _scalar_with_previous(cur, sql: str, f: TokenFilters) -> dict:
    """Run the same aggregation for current + previous period; return a scalar response."""
    where, params = _where(f, f.date_range_start, f.date_range_end)
    cur.execute(sql.format(where=where), params)
    current = cur.fetchone()["value"]

    ps, pe = previous_period(f.date_range_start, f.date_range_end)
    prev_where, prev_params = _where(f, ps, pe)
    cur.execute(sql.format(where=prev_where), prev_params)
    previous = cur.fetchone()["value"]

    return {"kind": "scalar", "value": current, "previous": previous, "format": "number"}


# ══════════════════════════════════════════════════════════════════════════
#  SCALARS — headline KPIs
# ══════════════════════════════════════════════════════════════════════════

@register_metric("tokens.total", kind="scalar", filter_model=TokenFilters, cache_ttl=5)
def tokens_total(cur: RealDictCursor, f: TokenFilters) -> dict:
    return _scalar_with_previous(cur, """
        SELECT COALESCE(SUM(total_tokens), 0)::bigint AS value
        FROM token_usage WHERE {where}
    """, f)


@register_metric("tokens.calls.count", kind="scalar", filter_model=TokenFilters, cache_ttl=5)
def tokens_calls_count(cur: RealDictCursor, f: TokenFilters) -> dict:
    return _scalar_with_previous(cur, "SELECT COUNT(*)::bigint AS value FROM token_usage WHERE {where}", f)


@register_metric("tokens.avg_per_call", kind="scalar", filter_model=TokenFilters, cache_ttl=5)
def tokens_avg_per_call(cur: RealDictCursor, f: TokenFilters) -> dict:
    result = _scalar_with_previous(cur, """
        SELECT COALESCE(AVG(total_tokens), 0)::float AS value
        FROM token_usage WHERE {where}
    """, f)
    result["value"] = round(float(result["value"]), 2)
    result["previous"] = round(float(result["previous"]), 2) if result["previous"] is not None else None
    return result


@register_metric("tokens.users.active", kind="scalar", filter_model=TokenFilters, cache_ttl=5)
def tokens_users_active(cur: RealDictCursor, f: TokenFilters) -> dict:
    return _scalar_with_previous(cur, """
        SELECT COUNT(DISTINCT user_id)::bigint AS value
        FROM token_usage WHERE {where}
    """, f)


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
            {"name": "prompt", "points": [{"t": r["t"].isoformat(), "v": r["prompt"]} for r in rows]},
            {"name": "completion", "points": [{"t": r["t"].isoformat(), "v": r["completion"]} for r in rows]},
        ],
        "format": "number",
    }


# ══════════════════════════════════════════════════════════════════════════
#  GROUPS — breakdowns by dimension
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
#  TABLE — paginated detail
# ══════════════════════════════════════════════════════════════════════════

class TableFilters(TokenFilters):
    page: int = 1
    page_size: int = 20
    sort: str = "total_tokens"    # total_tokens | calls | avg_per_call
    sort_dir: str = "desc"


_ALLOWED_SORTS = {"total_tokens", "calls", "avg_per_call"}
_ALLOWED_DIRS = {"asc", "desc"}


@register_metric("tokens.top_consumers", kind="table", filter_model=TableFilters, cache_ttl=15)
def tokens_top_consumers(cur: RealDictCursor, f: TableFilters) -> dict:
    sort_col = f.sort if f.sort in _ALLOWED_SORTS else "total_tokens"
    sort_dir = f.sort_dir if f.sort_dir in _ALLOWED_DIRS else "desc"
    offset = max(0, (f.page - 1) * f.page_size)

    where, params = _where(f, f.date_range_start, f.date_range_end, alias="tu")

    # Total count for pagination — one row per unique (user, project, model) combo
    cur.execute(f"""
        SELECT COUNT(*)::bigint AS total FROM (
            SELECT tu.user_id, tu.project_id, tu.model_name
            FROM token_usage tu WHERE {where}
            GROUP BY tu.user_id, tu.project_id, tu.model_name
        ) sub
    """, params)
    total = cur.fetchone()["total"]

    # Page of rows — sort_col / sort_dir are allowlisted, safe to interpolate
    cur.execute(f"""
        SELECT tu.user_id,
               COALESCE(u.name, tu.user_id::text) AS user_name,
               tu.project_id,
               COALESCE(p.name, tu.project_id::text) AS project_name,
               COALESCE(tu.model_name, 'unknown') AS model_name,
               COUNT(*)::bigint AS calls,
               SUM(tu.total_tokens)::bigint AS total_tokens,
               ROUND(AVG(tu.total_tokens))::bigint AS avg_per_call
        FROM token_usage tu
        LEFT JOIN users u ON u.id = tu.user_id
        LEFT JOIN projects p ON p.id = tu.project_id
        WHERE {where}
        GROUP BY tu.user_id, u.name, tu.project_id, p.name, tu.model_name
        ORDER BY {sort_col} {sort_dir}
        LIMIT %s OFFSET %s
    """, [*params, f.page_size, offset])

    rows = [dict(r) for r in cur.fetchall()]
    for r in rows:
        r["user_id"] = str(r["user_id"])
        r["project_id"] = str(r["project_id"])

    return {
        "kind": "table",
        "columns": ["user_name", "project_name", "model_name", "calls", "total_tokens", "avg_per_call"],
        "rows": rows,
        "total": total,
        "format": "number",
    }

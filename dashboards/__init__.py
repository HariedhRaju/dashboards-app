"""
Dashboards module — analytics for the main FastAPI app.

Wire in:
    from dashboards import router as dashboards_router
    app.include_router(dashboards_router, prefix="/api")

Everything here is infrastructure — write once, forget. Metrics themselves
live in dashboards/metrics.py; adding a dashboard is just appending metric
definitions there.

Env vars:
    DASHBOARDS_REPLICA_DSN   Postgres DSN for the read replica
                             (falls back to DATABASE_URL)
    REDIS_URL                Cache location (default redis://localhost:6379/0)
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable, Iterator, Literal, Type
from uuid import UUID

import redis
from fastapi import APIRouter, HTTPException, Request
from psycopg2.extras import RealDictCursor
from psycopg2.pool import ThreadedConnectionPool
from pydantic import BaseModel, ValidationError


# ══════════════════════════════════════════════════════════════════════════
#  DB — read-replica connection pool
# ══════════════════════════════════════════════════════════════════════════

_REPLICA_DSN = os.getenv("DASHBOARDS_REPLICA_DSN", os.getenv("DATABASE_URL"))
if not _REPLICA_DSN:
    raise RuntimeError("DASHBOARDS_REPLICA_DSN (or DATABASE_URL) must be set")

_replica_pool = ThreadedConnectionPool(
    minconn=int(os.getenv("DASHBOARDS_REPLICA_MIN_CONN", "2")),
    maxconn=int(os.getenv("DASHBOARDS_REPLICA_MAX_CONN", "20")),
    dsn=_REPLICA_DSN,
)


@contextmanager
def replica_cursor() -> Iterator[RealDictCursor]:
    """Yield a read-only cursor to the replica with a 5s statement timeout."""
    conn = _replica_pool.getconn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SET LOCAL statement_timeout = '5s'")
            cur.execute("SET LOCAL default_transaction_read_only = ON")
            yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        _replica_pool.putconn(conn)


# ══════════════════════════════════════════════════════════════════════════
#  CACHE — Redis
# ══════════════════════════════════════════════════════════════════════════

_redis = redis.Redis.from_url(
    os.getenv("REDIS_URL", "redis://localhost:6379/0"), decode_responses=True
)


def _cache_key(metric_id: str, filters: dict, ttl: int) -> str:
    bucket = int(time.time() // ttl)
    payload = json.dumps({"m": metric_id, "f": filters, "b": bucket}, sort_keys=True, default=str)
    return f"metric:{hashlib.sha256(payload.encode()).hexdigest()}"


def cache_get(metric_id: str, filters: dict, ttl: int) -> Any | None:
    try:
        hit = _redis.get(_cache_key(metric_id, filters, ttl))
    except redis.RedisError:
        return None  # Degrade gracefully on cache failure
    return json.loads(hit) if hit else None


def cache_set(metric_id: str, filters: dict, ttl: int, value: Any) -> None:
    try:
        _redis.setex(_cache_key(metric_id, filters, ttl), ttl, json.dumps(value, default=str))
    except redis.RedisError:
        pass  # Never break the API on cache write failure


# ══════════════════════════════════════════════════════════════════════════
#  FILTERS — shared filter model + helpers
# ══════════════════════════════════════════════════════════════════════════

Grain = Literal["hour", "day", "week", "month"]


class TokenFilters(BaseModel):
    """Filters accepted by every token_usage metric."""
    date_range_start: datetime
    date_range_end: datetime
    user_id: UUID | None = None
    project_id: UUID | None = None
    model_name: str | None = None
    feature: str | None = None
    grain: Grain | None = None  # Only used by series metrics


class BugFilters(BaseModel):
    """Filters accepted by every bug_reports metric."""
    date_range_start: datetime
    date_range_end: datetime
    project_id: UUID | None = None
    reported_by: UUID | None = None
    severity: str | None = None
    status: str | None = None
    grain: Grain | None = None  # Only used by series metrics


class TestCaseFilters(BaseModel):
    """Filters accepted by every test-case-generation metric."""
    date_range_start: datetime
    date_range_end: datetime
    project_id: UUID | None = None
    reported_by: UUID | None = None
    coverage_level: str | None = None
    priority: str | None = None
    test_type: str | None = None
    grain: Grain | None = None  # Only used by series metrics


class QaFilters(BaseModel):
    """Filters accepted by every qa_insights metric.

    `snapshot_id` pins the metric to one ingested workbook. Left out, metrics
    resolve to the newest snapshot ingested on or before `date_range_end`.
    That is what makes the shared date range meaningful for data that has no
    per-row date of its own: bugs are filtered by their `created` date, while
    test cases and localization cells are the *state* of a snapshot, so the
    range selects which snapshot is being looked at rather than which rows.
    """
    date_range_start: datetime
    date_range_end: datetime
    snapshot_id: UUID | None = None
    severity: str | None = None
    status: str | None = None
    issue_type: str | None = None
    module: str | None = None
    dimension: str | None = None
    # Test-case-side filters. `status`/`issue_type` above are bug fields;
    # test cases carry their own status vocabulary (Pass/Fail/Not Run) and
    # priority scale, so they get their own params rather than overloading
    # the bug ones. `reporter` matches BOTH bugs and test cases — the same
    # canonical field on each — since "show me Priya's work" spans both.
    test_status: str | None = None
    test_priority: str | None = None
    reporter: str | None = None
    grain: Grain | None = None  # Only used by series metrics


def auto_grain(start: datetime, end: datetime) -> Grain:
    """Pick a sensible grain based on range span."""
    delta = end - start
    if delta <= timedelta(hours=25): return "hour"
    if delta <= timedelta(days=45): return "day"
    if delta <= timedelta(days=180): return "week"
    return "month"


def previous_period(start: datetime, end: datetime) -> tuple[datetime, datetime]:
    """Same-length window immediately preceding `start`."""
    span = end - start
    return (start - span, start)


# ══════════════════════════════════════════════════════════════════════════
#  REGISTRY — @register_metric decorator + storage
# ══════════════════════════════════════════════════════════════════════════

@dataclass
class Metric:
    id: str
    kind: str                     # 'scalar' | 'series' | 'group' | 'table'
    filter_model: Type[BaseModel]
    query: Callable               # (cursor, filters) -> response dict
    cache_ttl: int = 5
    tenant_scoped: bool = False


registry: dict[str, Metric] = {}


def register_metric(
    id: str,
    kind: str,
    filter_model: Type[BaseModel],
    cache_ttl: int = 5,
    tenant_scoped: bool = False,
):
    """Decorator that registers a metric function.

        @register_metric("tokens.total", kind="scalar", filter_model=TokenFilters)
        def tokens_total(cur, filters):
            ...
    """
    if kind not in {"scalar", "series", "group", "table", "matrix",
                    "status_matrix", "findings", "narrative"}:
        raise ValueError(f"Unknown metric kind: {kind!r}")

    def decorator(fn: Callable) -> Callable:
        if id in registry:
            raise ValueError(f"Metric {id!r} already registered")
        registry[id] = Metric(
            id=id, kind=kind, filter_model=filter_model,
            query=fn, cache_ttl=cache_ttl, tenant_scoped=tenant_scoped,
        )
        return fn
    return decorator


# ══════════════════════════════════════════════════════════════════════════
#  ROUTER — one generic endpoint, one discovery endpoint
# ══════════════════════════════════════════════════════════════════════════

router = APIRouter(tags=["dashboards"])


@router.get("/metrics/{metric_id}")
def get_metric(metric_id: str, request: Request) -> Any:
    """Serve any registered metric."""
    metric = registry.get(metric_id)
    if metric is None:
        raise HTTPException(404, {"error": "unknown_metric", "id": metric_id})

    try:
        filters = metric.filter_model(**dict(request.query_params))
    except ValidationError as e:
        raise HTTPException(400, {"error": "invalid_filters", "issues": e.errors()})

    filter_dict = filters.model_dump(mode="json", exclude_none=True)

    cached = cache_get(metric.id, filter_dict, metric.cache_ttl)
    if cached is not None:
        return cached

    with replica_cursor() as cur:
        result = metric.query(cur, filters)

    cache_set(metric.id, filter_dict, metric.cache_ttl, result)
    return result


@router.get("/metrics")
def list_metrics() -> dict:
    """Discovery endpoint — every registered metric with its metadata."""
    return {
        "metrics": [
            {"id": m.id, "kind": m.kind, "cache_ttl": m.cache_ttl,
             "tenant_scoped": m.tenant_scoped}
            for m in registry.values()
        ]
    }


# ══════════════════════════════════════════════════════════════════════════
#  DIMENSIONS — distinct values that populate frontend filter dropdowns
# ══════════════════════════════════════════════════════════════════════════

_DIMENSION_QUERIES: dict[str, str] = {
    "users":
        "SELECT id::text AS value, name AS label FROM users ORDER BY name",
    "projects":
        "SELECT id::text AS value, name AS label FROM projects ORDER BY name",
    "models":
        "SELECT DISTINCT model_name AS value, model_name AS label "
        "FROM token_usage WHERE model_name IS NOT NULL ORDER BY value",
    "features":
        "SELECT DISTINCT feature AS value, feature AS label "
        "FROM token_usage WHERE feature IS NOT NULL ORDER BY value",
    # Bug dashboard dimensions
    "bug_projects":
        "SELECT id::text AS value, name AS label FROM bug_projects ORDER BY name",
    "bug_reporters":
        "SELECT id::text AS value, name AS label FROM bug_users ORDER BY name",
    "bug_severities":
        "SELECT DISTINCT severity AS value, severity AS label "
        "FROM bug_reports WHERE severity IS NOT NULL ORDER BY value",
    "bug_statuses":
        "SELECT unnest(ARRAY['open','in_progress','fixed','closed']) AS value, "
        "unnest(ARRAY['open','in_progress','fixed','closed']) AS label",
    # Test-case generation dimensions
    "tc_projects":
        "SELECT id::text AS value, name AS label FROM tc_projects ORDER BY name",
    "tc_reporters":
        "SELECT id::text AS value, name AS label FROM tc_users ORDER BY name",
    "tc_coverage_levels":
        "SELECT unnest(ARRAY['Essential','Standard','Comprehensive']) AS value, "
        "unnest(ARRAY['Essential','Standard','Comprehensive']) AS label",
    "tc_priorities":
        "SELECT unnest(ARRAY['Core','High','Medium','Low']) AS value, "
        "unnest(ARRAY['Core','High','Medium','Low']) AS label",
    "tc_test_types":
        "SELECT unnest(ARRAY['happy_path','negative','boundary','error_handling']) AS value, "
        "unnest(ARRAY['happy path','negative','boundary','error handling']) AS label",
    # QA insights dimensions — all drawn from the newest snapshot, since a
    # dropdown offering values from a workbook nobody is looking at is noise.
    "qa_snapshots":
        "SELECT id::text AS value, "
        "       source_label || ' — ' || to_char(ingested_at, 'DD Mon HH24:MI') AS label "
        "FROM qa_snapshots ORDER BY ingested_at DESC LIMIT 50",
    "qa_severities":
        "SELECT DISTINCT severity AS value, severity AS label FROM qa_bugs "
        "WHERE snapshot_id = (SELECT id FROM qa_snapshots ORDER BY ingested_at DESC LIMIT 1) "
        "ORDER BY value",
    "qa_statuses":
        "SELECT DISTINCT status AS value, status AS label FROM qa_bugs "
        "WHERE snapshot_id = (SELECT id FROM qa_snapshots ORDER BY ingested_at DESC LIMIT 1) "
        "ORDER BY value",
    "qa_issue_types":
        "SELECT DISTINCT issue_type AS value, issue_type AS label FROM qa_bugs "
        "WHERE issue_type IS NOT NULL "
        "AND snapshot_id = (SELECT id FROM qa_snapshots ORDER BY ingested_at DESC LIMIT 1) "
        "ORDER BY value",
    "qa_modules":
        # 'Unassigned' fallback matches _case_where/case_scope so a value
        # picked from this dropdown narrows the same rows the tiles counted
        # it from — a bare COALESCE without it would offer 'Unassigned' as
        # an option and then match zero rows when selected.
        "SELECT DISTINCT COALESCE(module, section, 'Unassigned') AS value, "
        "       COALESCE(module, section, 'Unassigned') AS label FROM qa_test_cases "
        "WHERE snapshot_id = (SELECT id FROM qa_snapshots ORDER BY ingested_at DESC LIMIT 1) "
        "ORDER BY value",
    "qa_dimensions":
        "SELECT DISTINCT dimension AS value, dimension AS label FROM qa_matrix_results "
        "WHERE snapshot_id = (SELECT id FROM qa_snapshots ORDER BY ingested_at DESC LIMIT 1) "
        "ORDER BY value",
    "qa_test_statuses":
        "SELECT DISTINCT status AS value, status AS label FROM qa_test_cases "
        "WHERE status IS NOT NULL "
        "AND snapshot_id = (SELECT id FROM qa_snapshots ORDER BY ingested_at DESC LIMIT 1) "
        "ORDER BY value",
    "qa_test_priorities":
        "SELECT DISTINCT priority AS value, priority AS label FROM qa_test_cases "
        "WHERE priority IS NOT NULL "
        "AND snapshot_id = (SELECT id FROM qa_snapshots ORDER BY ingested_at DESC LIMIT 1) "
        "ORDER BY value",
    # Reporters span both bugs and test cases — one dropdown, one field name,
    # matching the same `reporter` param on both sides of QaFilters.
    "qa_reporters":
        "SELECT DISTINCT reporter AS value, reporter AS label FROM ("
        "  SELECT reporter FROM qa_bugs WHERE reporter IS NOT NULL "
        "    AND snapshot_id = (SELECT id FROM qa_snapshots ORDER BY ingested_at DESC LIMIT 1) "
        "  UNION "
        "  SELECT reporter FROM qa_test_cases WHERE reporter IS NOT NULL "
        "    AND snapshot_id = (SELECT id FROM qa_snapshots ORDER BY ingested_at DESC LIMIT 1) "
        ") r ORDER BY value",
}


@router.get("/dimensions/{name}")
def get_dimension(name: str) -> Any:
    """Return distinct values for a filter dropdown."""
    if name not in _DIMENSION_QUERIES:
        raise HTTPException(404, {"error": "unknown_dimension", "name": name})

    # Cache for 60s — dimensions change slowly.
    cache_id = f"dim:{name}"
    cached = cache_get(cache_id, {}, 60)
    if cached is not None:
        return cached

    with replica_cursor() as cur:
        cur.execute(_DIMENSION_QUERIES[name])
        rows = [dict(r) for r in cur.fetchall()]

    result = {"name": name, "options": rows}
    cache_set(cache_id, {}, 60, result)
    return result


# ══════════════════════════════════════════════════════════════════════════
#  IMPORT METRICS — triggers @register_metric decorators at package load
# ══════════════════════════════════════════════════════════════════════════

from . import metrics as _metrics  # noqa: E402, F401
from . import bug_metrics as _bug_metrics  # noqa: E402, F401
from . import testcase_metrics as _testcase_metrics  # noqa: E402, F401
from . import qa_metrics as _qa_metrics  # noqa: E402, F401

"""
ReportIQ Dashboards Module — Backend Engine & Metrics Registry.

Wiring into an existing FastAPI application:
    from dashboards import router as dashboards_router
    app.include_router(dashboards_router, prefix="/api")

Environment variables:
    DASHBOARDS_REPLICA_DSN   Postgres DSN (falls back to DATABASE_URL)
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

if os.path.exists(".env"):
    with open(".env") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ[k.strip()] = v.strip().strip("'\"")

_REPLICA_DSN = os.getenv("DASHBOARDS_REPLICA_DSN", os.getenv("DATABASE_URL"))
if not _REPLICA_DSN:
    raise RuntimeError("DASHBOARDS_REPLICA_DSN (or DATABASE_URL) must be set in environment or .env file")

_replica_pool = ThreadedConnectionPool(
    minconn=int(os.getenv("DASHBOARDS_REPLICA_MIN_CONN", "2")),
    maxconn=int(os.getenv("DASHBOARDS_REPLICA_MAX_CONN", "20")),
    dsn=_REPLICA_DSN,
)

def _ensure_views():
    """Auto-migrate required tables and columns for ReportIQ if needed."""
    try:
        conn = _replica_pool.getconn()
        try:
            with conn.cursor() as cur:
                # 1. Base entities
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS users (
                        id    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                        name  TEXT NOT NULL,
                        email TEXT
                    );

                    CREATE TABLE IF NOT EXISTS projects (
                        id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                        name            TEXT NOT NULL,
                        code            VARCHAR(16),
                        progress_pct    INTEGER NOT NULL DEFAULT 0,
                        health_status   VARCHAR(20) NOT NULL DEFAULT 'on_track',
                        delivery_score  INTEGER NOT NULL DEFAULT 0,
                        quality_score   INTEGER NOT NULL DEFAULT 0,
                        testing_score   INTEGER NOT NULL DEFAULT 0,
                        build_score     INTEGER NOT NULL DEFAULT 0,
                        reporting_score INTEGER NOT NULL DEFAULT 0,
                        target_date     DATE,
                        planned_pct     INTEGER NOT NULL DEFAULT 0
                    );

                    CREATE TABLE IF NOT EXISTS report_templates (
                        id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                        name                 TEXT NOT NULL,
                        category             VARCHAR(50) NOT NULL,
                        avg_compile_time_sec FLOAT NOT NULL DEFAULT 3.5,
                        default_format       VARCHAR(20) NOT NULL DEFAULT 'pdf',
                        created_at           TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
                    );

                    CREATE TABLE IF NOT EXISTS builds (
                        id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                        project_id   UUID NOT NULL REFERENCES projects(id),
                        build_tag    VARCHAR(50),
                        version      VARCHAR(50),
                        status       VARCHAR(20) NOT NULL DEFAULT 'PASS',
                        audit_score  INTEGER NOT NULL DEFAULT 95,
                        created_at   TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
                    );

                    CREATE TABLE IF NOT EXISTS report_logs (
                        id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                        project_id           UUID NOT NULL REFERENCES projects(id),
                        build_id             UUID REFERENCES builds(id),
                        template_id          UUID NOT NULL REFERENCES report_templates(id),
                        title                VARCHAR(250) NOT NULL,
                        author_id            UUID NOT NULL REFERENCES users(id),
                        output_format        VARCHAR(20) NOT NULL DEFAULT 'pdf',
                        report_type          VARCHAR(10) NOT NULL DEFAULT 'DSR',
                        compilation_time_sec FLOAT NOT NULL DEFAULT 3.2,
                        tokens_used          INTEGER NOT NULL DEFAULT 1200,
                        pipeline_stage       VARCHAR(20) NOT NULL DEFAULT 'published',
                        created_at           TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
                    );

                    CREATE TABLE IF NOT EXISTS project_milestones (
                        id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                        project_id   UUID NOT NULL REFERENCES projects(id),
                        name         VARCHAR(120) NOT NULL,
                        status       VARCHAR(20)  NOT NULL DEFAULT 'upcoming',
                        target_date  DATE,
                        completed_at DATE,
                        sort_order   INTEGER NOT NULL DEFAULT 0
                    );

                    CREATE TABLE IF NOT EXISTS project_timeline_events (
                        id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                        project_id  UUID NOT NULL REFERENCES projects(id),
                        event_type  VARCHAR(40) NOT NULL,
                        title       VARCHAR(200) NOT NULL,
                        description TEXT,
                        event_date  DATE NOT NULL,
                        severity    VARCHAR(20) NOT NULL DEFAULT 'info'
                    );

                    CREATE TABLE IF NOT EXISTS project_progress_history (
                        id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                        project_id   UUID NOT NULL REFERENCES projects(id),
                        recorded_date DATE NOT NULL,
                        planned_pct  INTEGER NOT NULL DEFAULT 0,
                        actual_pct   INTEGER NOT NULL DEFAULT 0,
                        UNIQUE (project_id, recorded_date)
                    );

                    CREATE TABLE IF NOT EXISTS project_risks (
                        id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                        project_id  UUID NOT NULL REFERENCES projects(id),
                        risk_type   VARCHAR(40) NOT NULL,
                        severity    VARCHAR(20) NOT NULL DEFAULT 'warning',
                        title       VARCHAR(200) NOT NULL,
                        detail      TEXT,
                        is_active   BOOLEAN NOT NULL DEFAULT TRUE,
                        created_at  TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
                    );

                    CREATE TABLE IF NOT EXISTS uploaded_files (
                        id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                        project_id       UUID REFERENCES projects(id),
                        filename         VARCHAR(255) NOT NULL,
                        file_type        VARCHAR(50) NOT NULL DEFAULT 'document',
                        file_size        BIGINT DEFAULT 102400,
                        file_size_bytes  BIGINT NOT NULL DEFAULT 102400,
                        uploaded_by      UUID REFERENCES users(id),
                        created_at       TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
                    );
                """)
            conn.commit()
        finally:
            _replica_pool.putconn(conn)
    except Exception:
        pass

_ensure_views()


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
#  CACHE — Redis (non-blocking fallback when offline)
# ══════════════════════════════════════════════════════════════════════════

_REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
_redis: redis.Redis | None = None
_redis_available = False

try:
    _redis_client = redis.Redis.from_url(
        _REDIS_URL,
        socket_connect_timeout=0.2,
        socket_timeout=0.2,
        decode_responses=True,
    )
    _redis_client.ping()
    _redis = _redis_client
    _redis_available = True
except Exception:
    _redis = None
    _redis_available = False


def _cache_key(metric_id: str, filters: dict, ttl: int) -> str:
    bucket = int(time.time() // ttl)
    payload = json.dumps({"m": metric_id, "f": filters, "b": bucket}, sort_keys=True, default=str)
    return f"metric:{hashlib.sha256(payload.encode()).hexdigest()}"


def cache_get(metric_id: str, filters: dict, ttl: int) -> Any | None:
    if not _redis_available or _redis is None:
        return None
    try:
        hit = _redis.get(_cache_key(metric_id, filters, ttl))
        return json.loads(hit) if hit else None
    except Exception:
        return None


def cache_set(metric_id: str, filters: dict, ttl: int, value: Any) -> None:
    if not _redis_available or _redis is None:
        return
    try:
        _redis.setex(_cache_key(metric_id, filters, ttl), ttl, json.dumps(value, default=str))
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════════
#  FILTERS — ReportIQ filter model + helpers
# ══════════════════════════════════════════════════════════════════════════

Grain = Literal["hour", "day", "week", "month"]


class ReportIQFilters(BaseModel):
    """Filters accepted by ReportIQ metrics."""
    date_range_start: datetime
    date_range_end: datetime
    project_id: UUID | None = None
    template_id: UUID | None = None
    build_id: UUID | None = None
    output_format: str | None = None
    report_type: str | None = None
    health_status: str | None = None
    grain: Grain | None = None


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
    """Decorator that registers a metric function."""
    if kind not in {"scalar", "series", "group", "table"}:
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

    # Strip empty string query params so UUID and optional filters don't trigger validation errors
    clean_params = {k: v for k, v in request.query_params.items() if v.strip() != ""}

    try:
        filters = metric.filter_model(**clean_params)
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
    "projects":
        "SELECT id::text AS value, name AS label FROM projects ORDER BY name",
    "report_templates":
        "SELECT id::text AS value, name AS label FROM report_templates ORDER BY name",
    "report_builds":
        "SELECT id::text AS value, COALESCE(version, build_tag, id::text) AS label FROM builds ORDER BY label",
    "report_formats":
        "SELECT unnest(ARRAY['pdf','xlsx','md']) AS value, "
        "unnest(ARRAY['pdf','xlsx','md']) AS label",
    "report_types":
        "SELECT unnest(ARRAY['DSR','WSR']) AS value, "
        "unnest(ARRAY['DSR (Daily Status)','WSR (Weekly Status)']) AS label",
    "project_statuses":
        "SELECT unnest(ARRAY['on_track','at_risk','delayed']) AS value, "
        "unnest(ARRAY['On Track','At Risk','Delayed']) AS label",
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

from . import reportiq_metrics as _reportiq_metrics  # noqa: E402, F401

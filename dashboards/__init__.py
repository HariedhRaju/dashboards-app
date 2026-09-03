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

import asyncio
import hashlib
import json
import os
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import partial
from typing import Any, Callable, Iterator, Literal, Type
from uuid import UUID

import redis
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
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
    try:
        conn = _replica_pool.getconn()
        try:
            with conn.cursor() as cur:
                # Bug views
                cur.execute("""
                    DO $$ 
                    BEGIN 
                        IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'bug_users') 
                           AND EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'users') THEN
                            CREATE VIEW bug_users AS SELECT id, name, email FROM users;
                        END IF;
                        IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'bug_projects') 
                           AND EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'projects') THEN
                            CREATE VIEW bug_projects AS SELECT id, name, code FROM projects;
                        END IF;
                    END $$;
                """)
                # ReportIQ schema
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

                    ALTER TABLE projects ADD COLUMN IF NOT EXISTS progress_pct    INTEGER NOT NULL DEFAULT 0;
                    ALTER TABLE projects ADD COLUMN IF NOT EXISTS health_status   VARCHAR(20) NOT NULL DEFAULT 'on_track';
                    ALTER TABLE projects ADD COLUMN IF NOT EXISTS delivery_score  INTEGER NOT NULL DEFAULT 0;
                    ALTER TABLE projects ADD COLUMN IF NOT EXISTS quality_score   INTEGER NOT NULL DEFAULT 0;
                    ALTER TABLE projects ADD COLUMN IF NOT EXISTS testing_score   INTEGER NOT NULL DEFAULT 0;
                    ALTER TABLE projects ADD COLUMN IF NOT EXISTS build_score     INTEGER NOT NULL DEFAULT 0;
                    ALTER TABLE projects ADD COLUMN IF NOT EXISTS reporting_score INTEGER NOT NULL DEFAULT 0;
                    ALTER TABLE projects ADD COLUMN IF NOT EXISTS target_date     DATE;
                    ALTER TABLE projects ADD COLUMN IF NOT EXISTS planned_pct     INTEGER NOT NULL DEFAULT 0;

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


@contextmanager
def write_cursor() -> Iterator[RealDictCursor]:
    """Yield a read-write cursor connected to the database pool."""
    conn = _replica_pool.getconn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SET LOCAL statement_timeout = '5s'")
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
    """Decorator that registers a metric function.

        @register_metric("tokens.total", kind="scalar", filter_model=TokenFilters)
        def tokens_total(cur, filters):
            ...
    """
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


MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB limit


@router.post(
    "/bugs/import",
    summary="Import bugs from an Excel or CSV file into Bugsy.",
    description="Import bugs from an uploaded Excel (.xlsx/.xls) or CSV file into PostgreSQL."
)
async def import_bugs_endpoint(
    file: UploadFile = File(...),
    default_project: str | None = Form(None)
) -> dict[str, Any]:
    """FastAPI endpoint to ingest Excel/CSV bug files."""
    filename = file.filename or ""
    ext = os.path.splitext(filename)[1].lower()

    if ext not in (".xlsx", ".xls", ".csv"):
        raise HTTPException(
            status_code=400,
            detail="Unsupported file type. Only .xlsx, .xls and .csv files are allowed."
        )

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(
            status_code=400,
            detail="Uploaded file is empty."
        )

    if len(file_bytes) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(
            status_code=413,
            detail="File too large. Maximum allowed size is 10 MB."
        )

    try:
        from .importer import import_bugs
        source_name = "csv" if ext == ".csv" else "excel"
        result = import_bugs(
            file_bytes=file_bytes,
            filename=filename,
            default_project=default_project,
            source_name=source_name
        )
        return result
    except Exception as err:
        raise HTTPException(
            status_code=400,
            detail=f"Error processing bug import file: {str(err)}"
        )


@router.get(
    "/bugs/data-profile",
    summary="Get structured data profile for bug reports dataset.",
    description="Inspects standard and dynamic fields to return field types, distributions, and analytical recommendations."
)
async def data_profile_endpoint(
    request: Request,
    project_id: str | None = None
) -> dict[str, Any]:
    """FastAPI read-only endpoint for data profiling."""
    try:
        from .data_profiler import profile_project_data
        qp = dict(request.query_params)
        qp.pop("project_id", None)
        return profile_project_data(project_id=project_id, filters=qp if qp else None)
    except ValueError as err:
        raise HTTPException(
            status_code=404 if "not found" in str(err).lower() else 400,
            detail=str(err)
        )
    except Exception as err:
        raise HTTPException(
            status_code=500,
            detail=f"Error profiling dataset: {str(err)}"
        )


class AnalyzeRequest(BaseModel):
    project_id: str | None = None
    filters: dict[str, Any] | None = None
    context: dict[str, Any] | None = None


@router.post(
    "/bugs/analyze",
    summary="Analyze bug dataset and produce an adaptive dashboard plan.",
    description="Invokes AI Dashboard Analyst using Ollama to reason over Step 2.1 profile and return JSON dashboard plan."
)
async def analyze_bugs_endpoint(req: AnalyzeRequest) -> dict[str, Any]:
    """FastAPI endpoint to generate AI adaptive dashboard analysis plan.
    
    Runs the synchronous LLM call in a thread pool executor so it never
    blocks the async event loop (which would freeze all other API requests).
    """
    try:
        from .data_profiler import profile_project_data
        from .dashboard_agent import analyze_dashboard
        from .llm_client import OllamaUnavailableError, OllamaModelError

        profile = profile_project_data(project_id=req.project_id, filters=req.filters)

        # Run blocking LLM call in thread pool — never blocks event loop
        loop = asyncio.get_event_loop()
        fn = partial(analyze_dashboard, profile=profile, context=req.context or req.filters)
        analysis = await loop.run_in_executor(None, fn)
        return {"success": True, "analysis": analysis}
    except OllamaUnavailableError as err:
        raise HTTPException(
            status_code=503,
            detail=str(err)
        )
    except OllamaModelError as err:
        raise HTTPException(
            status_code=422,
            detail=str(err)
        )
    except ValueError as err:
        raise HTTPException(
            status_code=404 if "not found" in str(err).lower() else 400,
            detail=str(err)
        )
    except Exception as err:
        raise HTTPException(
            status_code=500,
            detail=f"Error generating AI dashboard analysis: {str(err)}"
        )


@router.get(
    "/bugs/quick-stats",
    summary="Instant deterministic bug stats (no LLM, no wait).",
    description="Returns key counts from DB immediately for fast overview display."
)
async def bugs_quick_stats(project_id: str | None = None) -> dict[str, Any]:
    """Return fast deterministic stats without any LLM call."""
    try:
        with replica_cursor() as cur:
            # Project filter condition
            proj_cond = "AND project_id = %s" if project_id else ""
            proj_params = [project_id] if project_id else []

            cur.execute(f"""
                SELECT 
                    COUNT(*)::int AS total,
                    COUNT(*) FILTER (WHERE status <> 'closed')::int AS backlog,
                    COUNT(*) FILTER (WHERE severity IN ('P1','Blocker','Critical') AND status <> 'closed')::int AS critical_open,
                    COUNT(DISTINCT reported_by)::int AS active_reporters
                FROM bug_reports
                WHERE 1=1 {proj_cond}
            """, proj_params)
            totals = dict(cur.fetchone())

            cur.execute(f"""
                SELECT severity, COUNT(*)::int AS cnt
                FROM bug_reports WHERE severity IS NOT NULL {proj_cond}
                GROUP BY severity ORDER BY severity
            """, proj_params)
            by_severity = {r["severity"]: r["cnt"] for r in cur.fetchall()}

            cur.execute(f"""
                SELECT status, COUNT(*)::int AS cnt
                FROM bug_reports WHERE status IS NOT NULL {proj_cond}
                GROUP BY status
            """, proj_params)
            by_status = {r["status"]: r["cnt"] for r in cur.fetchall()}

            cur.execute(f"""
                SELECT COALESCE(p.name, 'Unknown') AS name, COUNT(*)::int AS total,
                       COUNT(*) FILTER (WHERE b.status <> 'closed')::int AS open
                FROM bug_reports b
                LEFT JOIN bug_projects p ON p.id = b.project_id
                WHERE 1=1 {proj_cond}
                GROUP BY p.name ORDER BY total DESC LIMIT 10
            """, proj_params)
            by_game = [dict(r) for r in cur.fetchall()]

        total = totals["total"] or 0
        backlog = totals["backlog"] or 0
        critical = totals["critical_open"] or 0
        reporters = totals["active_reporters"] or 0
        fix_rate = round((total - backlog) / total * 100, 1) if total > 0 else 0

        # Build a simple, clear executive summary from real numbers
        top_severity = max(by_severity, key=lambda k: by_severity[k]) if by_severity else "N/A"
        summary_parts = [
            f"There are {total} total bug reports across {len(by_game)} game project(s).",
            f"{backlog} bugs remain unresolved ({round(backlog/total*100, 0):.0f}% backlog rate)." if total > 0 else "",
            f"{critical} P1/Critical/Blocker bugs are currently open and need immediate attention." if critical > 0 else "No critical bugs are currently open.",
            f"The team has resolved {fix_rate:.0f}% of all reported bugs.",
        ]
        summary = " ".join(p for p in summary_parts if p)

        return {
            "success": True,
            "stats": {
                "total": total,
                "backlog": backlog,
                "critical_open": critical,
                "active_reporters": reporters,
                "fix_rate": fix_rate,
                "by_severity": by_severity,
                "by_status": by_status,
                "by_game": by_game,
                "executive_summary": summary,
                "game_count": len(by_game),
            }
        }
    except Exception as err:
        raise HTTPException(status_code=500, detail=f"Error fetching quick stats: {str(err)}")


class InsightsEndpointRequest(BaseModel):
    project_id: str | None = None
    filters: dict[str, Any] | None = None
    context: dict[str, Any] | None = None
    dashboard_plan: dict[str, Any] | None = None
    drilldown_data: dict[str, Any] | None = None


@router.post(
    "/bugs/insights",
    summary="Generate data-grounded insights, explanations, and recommendations.",
    description="Invokes Step 2.4 Insight Agent to reason over actual aggregated metrics and context."
)
async def bugs_insights_endpoint(req: InsightsEndpointRequest) -> dict[str, Any]:
    """FastAPI endpoint to generate deep AI data insights.
    
    All synchronous LLM calls run in a thread pool executor so they never
    block the async event loop.
    """
    try:
        from .data_profiler import profile_project_data
        from .insight_agent import analyze_data, get_bug_details
        from .llm_client import OllamaUnavailableError, OllamaModelError
        from .dashboard_agent import analyze_dashboard

        # Fast DB operations first (non-blocking)
        profile = profile_project_data(project_id=req.project_id, filters=req.filters)

        metric_data = {}
        with replica_cursor() as cur:
            cur.execute("""
                SELECT severity, COUNT(*)::int AS cnt 
                FROM bug_reports 
                WHERE severity IS NOT NULL 
                GROUP BY severity
            """)
            metric_data["severity"] = {r["severity"]: r["cnt"] for r in cur.fetchall()}

            cur.execute("""
                SELECT status, COUNT(*)::int AS cnt 
                FROM bug_reports 
                WHERE status IS NOT NULL 
                GROUP BY status
            """)
            metric_data["status"] = {r["status"]: r["cnt"] for r in cur.fetchall()}

            cur.execute("""
                SELECT COALESCE(p.name, 'Unassigned Project') AS game_name, COUNT(*)::int AS cnt
                FROM bug_reports b
                LEFT JOIN bug_projects p ON p.id = b.project_id
                GROUP BY 1 ORDER BY 2 DESC
            """)
            metric_data["game_counts"] = {r["game_name"]: r["cnt"] for r in cur.fetchall()}

            cur.execute("""
                SELECT COALESCE(p.name, 'Unassigned Project') AS game_name, b.severity, COUNT(*)::int AS cnt
                FROM bug_reports b
                LEFT JOIN bug_projects p ON p.id = b.project_id
                WHERE b.severity IS NOT NULL
                GROUP BY 1, 2
            """)
            game_sev: dict = {}
            for r in cur.fetchall():
                g = r["game_name"]
                if g not in game_sev:
                    game_sev[g] = {}
                game_sev[g][r["severity"]] = r["cnt"]
            metric_data["game_severity_counts"] = game_sev

            cur.execute("""
                SELECT 
                    COALESCE(b.dynamic_fields->>'source_record_id', b.dynamic_fields->>'issue_no', b.id::text) AS issue_no,
                    b.title,
                    COALESCE(p.name, 'Unassigned Project') AS game_name,
                    b.severity,
                    b.status
                FROM bug_reports b
                LEFT JOIN bug_projects p ON p.id = b.project_id
                ORDER BY CASE WHEN b.severity = 'P1' THEN 1 WHEN b.severity = 'P2' THEN 2 ELSE 3 END, b.created_at DESC
                LIMIT 15
            """)
            metric_data["identified_bugs_sample"] = [dict(r) for r in cur.fetchall()]

            for df in profile.get("dynamic_fields", []):
                key = df.get("name")
                if key and not key.endswith("_id") and key not in ("source_record_id", "source"):
                    cur.execute("""
                        SELECT dynamic_fields->>%s AS val, COUNT(*)::int AS cnt
                        FROM bug_reports
                        WHERE dynamic_fields->>%s IS NOT NULL
                        GROUP BY 1 LIMIT 10
                    """, (key, key))
                    counts = {r["val"]: r["cnt"] for r in cur.fetchall() if r["val"]}
                    if counts:
                        metric_data[key] = counts

        drilldown_info = req.drilldown_data
        if req.context and req.context.get("field") in ("issue_no", "source_record_id", "bug"):
            bug_val = req.context.get("value")
            if bug_val:
                drilldown_info = get_bug_details(bug_val, req.project_id)

        plan = req.dashboard_plan or {"dashboard_title": "Bug Bot Dashboard"}

        # Run the slow LLM analysis in a thread pool — does not block event loop
        loop = asyncio.get_event_loop()
        fn = partial(
            analyze_data,
            profile=profile,
            dashboard_plan=plan,
            metric_data=metric_data,
            context=req.context or req.filters,
            drilldown_data=drilldown_info,
        )
        insights = await loop.run_in_executor(None, fn)
        return {"success": True, "insights": insights}
    except OllamaUnavailableError as err:
        raise HTTPException(status_code=503, detail=str(err))
    except OllamaModelError as err:
        raise HTTPException(status_code=422, detail=str(err))
    except ValueError as err:
        raise HTTPException(status_code=404 if "not found" in str(err).lower() else 400, detail=str(err))
    except Exception as err:
        raise HTTPException(status_code=500, detail=f"Error generating data insights: {str(err)}")


@router.get(
    "/bugs/details",
    summary="Get record-level bug details for bug investigation drilldown.",
    description="Safely queries bug record details and multi-project occurrences by issue_no / source_record_id."
)
async def bug_details_endpoint(issue_no: str, project_id: str | None = None) -> dict[str, Any]:
    """FastAPI endpoint to retrieve bug record investigation details."""
    try:
        from .insight_agent import get_bug_details
        details = get_bug_details(issue_no=issue_no, project_id=project_id)
        if not details.get("found"):
            raise HTTPException(status_code=404, detail=f"Bug record '{issue_no}' not found.")
        return {"success": True, "details": details}
    except HTTPException:
        raise
    except Exception as err:
        raise HTTPException(status_code=500, detail=f"Error retrieving bug details: {str(err)}")


@router.get(
    "/bugs/dynamic-metric",
    summary="Query standard or dynamic JSONB metric aggregations.",
    description="Safely aggregates field values by metric for agent-driven dynamic charts."
)
async def dynamic_metric_endpoint(
    request: Request,
    field_name: str,
    project_id: str | None = None,
    metric: str = "count"
) -> dict[str, Any]:
    """FastAPI endpoint to fetch aggregated values for dynamic chart rendering."""
    try:
        from .data_profiler import query_dynamic_metric
        qp = dict(request.query_params)
        qp.pop("field_name", None)
        qp.pop("project_id", None)
        qp.pop("metric", None)
        return query_dynamic_metric(field_name=field_name, project_id=project_id, metric=metric, filters=qp if qp else None)
    except ValueError as err:
        raise HTTPException(
            status_code=400,
            detail=str(err)
        )
    except Exception as err:
        raise HTTPException(
            status_code=500,
            detail=f"Error querying dynamic metric: {str(err)}"
        )


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
        "SELECT DISTINCT p.id::text AS value, p.name AS label "
        "FROM bug_projects p JOIN bug_reports b ON b.project_id = p.id ORDER BY p.name",
    "bug_issues":
        "SELECT value, label FROM ("
        "  SELECT DISTINCT"
        "    COALESCE(b.dynamic_fields->>'source_record_id', b.dynamic_fields->>'issue_no', b.id::text) AS value,"
        "    COALESCE(b.dynamic_fields->>'source_record_id', b.dynamic_fields->>'issue_no', b.id::text) AS label"
        "  FROM bug_reports b"
        "  WHERE b.dynamic_fields->>'source_record_id' IS NOT NULL OR b.dynamic_fields->>'issue_no' IS NOT NULL"
        ") sub"
        " ORDER BY (NULLIF(regexp_replace(value, '[^0-9]', '', 'g'), ''))::int NULLS LAST, value",
    "bug_reporters":
        "SELECT id::text AS value, name AS label FROM bug_users ORDER BY name",
    "bug_severities":
        "SELECT DISTINCT severity AS value, severity AS label "
        "FROM bug_reports WHERE severity IS NOT NULL ORDER BY value",
    "bug_statuses":
        "SELECT DISTINCT status AS value, status AS label "
        "FROM bug_reports WHERE status IS NOT NULL ORDER BY value",
    # ReportIQ dashboard dimensions
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
#  COMMON ANALYTICS AGENT — cross-feature Bugsy/TestSmith analytics.
#  Deterministic aggregation lives in common_agent/core.py (top-level
#  package, sibling to this one — see common_agent/__init__.py for why).
#  This route only wires real Postgres adapters into it; it contains no
#  aggregation logic of its own.
# ══════════════════════════════════════════════════════════════════════════

@router.get(
    "/common-agent/dashboard",
    summary="Cross-feature analytics between Bugsy and TestSmith.",
    description="Deterministic, read-only aggregation over bug_reports, generated_test_cases, "
                "bug_test_case_mappings, and token_usage. Optional LLM interpretation via "
                "include_insights=true."
)
async def common_agent_dashboard(project_id: str | None = None, include_insights: bool = False) -> dict[str, Any]:
    """FastAPI endpoint for the Common Analytics Agent.

    Runs the blocking LLM insight call (when requested) in a thread pool
    executor, matching the pattern already used by /bugs/analyze and
    /bugs/insights, so it never blocks the async event loop.
    """
    from common_agent.postgres_bugsy_adapter import PostgresBugsyAdapter
    from common_agent.postgres_testsmith_adapter import PostgresTestSmithAdapter
    from common_agent.postgres_mapping_adapter import PostgresMappingAdapter
    from common_agent.postgres_token_usage_adapter import PostgresTokenUsageAdapter
    from common_agent.core import build_common_dashboard

    try:
        dashboard = build_common_dashboard(
            bug_source=PostgresBugsyAdapter(),
            test_case_source=PostgresTestSmithAdapter(),
            mapping_source=PostgresMappingAdapter(),
            token_usage_source=PostgresTokenUsageAdapter(),
            project_id=project_id,
        )
    except Exception as err:
        raise HTTPException(status_code=500, detail=f"Error building Common Agent dashboard: {str(err)}")

    result: dict[str, Any] = {"dashboard": dashboard}

    if include_insights:
        from common_agent.insights import generate_insights
        from .llm_client import OllamaUnavailableError, OllamaModelError

        loop = asyncio.get_event_loop()
        try:
            fn = partial(generate_insights, dashboard)
            result["insights"] = await loop.run_in_executor(None, fn)
        except OllamaUnavailableError as err:
            raise HTTPException(status_code=503, detail=str(err))
        except OllamaModelError as err:
            raise HTTPException(status_code=422, detail=str(err))
        except Exception as err:
            raise HTTPException(status_code=500, detail=f"Error generating Common Agent insights: {str(err)}")

    return result


@router.get(
    "/common-agent/bug-summary/{bug_id}",
    summary="AI summary of one bug and its explicitly mapped test cases.",
    description="Real bug text + the complete, exact set of test cases mapped to it via "
                "bug_test_case_mappings (never sampled, never inferred from module/feature names)."
)
async def common_agent_bug_summary(bug_id: str) -> dict[str, Any]:
    """FastAPI endpoint for a single bug's AI summary. Runs the LLM call in a
    thread pool executor, same pattern as the dashboard route's insights."""
    from common_agent.postgres_bugsy_adapter import PostgresBugsyAdapter
    from common_agent.postgres_testsmith_adapter import PostgresTestSmithAdapter
    from common_agent.postgres_mapping_adapter import PostgresMappingAdapter
    from common_agent.combined_summary import generate_bug_summary

    bugsy_adapter = PostgresBugsyAdapter()
    try:
        bug = bugsy_adapter.get_bug_by_id(bug_id)
    except Exception as err:
        raise HTTPException(status_code=500, detail=f"Error fetching bug: {str(err)}")

    if bug is None:
        raise HTTPException(status_code=404, detail=f"Bug '{bug_id}' not found.")

    try:
        mappings = PostgresMappingAdapter().get_mappings_for_bug(bug.id)
        mapped_test_cases = PostgresTestSmithAdapter().get_test_cases_by_ids(
            [m.test_case_id for m in mappings]
        )
    except Exception as err:
        raise HTTPException(status_code=500, detail=f"Error fetching mapped test cases: {str(err)}")

    loop = asyncio.get_event_loop()
    fn = partial(generate_bug_summary, bug, mapped_test_cases)
    summary = await loop.run_in_executor(None, fn)

    return {"bug_id": bug_id, "mapped_test_case_count": len(mapped_test_cases), "summary": summary}


class ProjectSummaryRequest(BaseModel):
    project_id: str


@router.post(
    "/common-agent/project-summary",
    summary="AI project-level summary combining Bugsy bugs and TestSmith test cases for one project.",
    description="Narrated from the exact, project-scoped dashboard stats only — no raw bug/test-case "
                "records are shown to the model, so there is nothing for it to miscount."
)
async def common_agent_project_summary(req: ProjectSummaryRequest) -> dict[str, Any]:
    """FastAPI endpoint for the project-level combined AI summary."""
    from common_agent.postgres_bugsy_adapter import PostgresBugsyAdapter
    from common_agent.postgres_testsmith_adapter import PostgresTestSmithAdapter
    from common_agent.postgres_mapping_adapter import PostgresMappingAdapter
    from common_agent.core import build_common_dashboard
    from common_agent.combined_summary import generate_project_summary

    try:
        dashboard = build_common_dashboard(
            bug_source=PostgresBugsyAdapter(),
            test_case_source=PostgresTestSmithAdapter(),
            mapping_source=PostgresMappingAdapter(),
            project_id=req.project_id,
        )
    except Exception as err:
        raise HTTPException(status_code=500, detail=f"Error building project summary data: {str(err)}")

    loop = asyncio.get_event_loop()
    fn = partial(generate_project_summary, dashboard)
    summary = await loop.run_in_executor(None, fn)

    return {"dashboard": dashboard, "summary": summary}


@router.get(
    "/common-agent/mapped-test-case-counts",
    summary="Per-bug mapped test-case counts for one project, keyed by issue number.",
    description="Real, deterministic per-row detail (not an aggregate) needed to render a bug-level "
                "coverage table correctly — e.g. so a UI can show which specific bugs are covered "
                "without inferring it from row position or any other proxy. A fast, direct SQL join; "
                "does not touch common_agent/ (that package stays aggregate-only by design)."
)
async def common_agent_mapped_test_case_counts(project_id: str) -> dict[str, Any]:
    with replica_cursor() as cur:
        cur.execute(
            """
            SELECT b.dynamic_fields->>'source_record_id' AS issue_no, COUNT(*)::int AS mapped_count
            FROM bug_test_case_mappings m
            JOIN bug_reports b ON b.id = m.bug_id
            WHERE b.project_id = %s
              AND b.dynamic_fields->>'source_record_id' IS NOT NULL
            GROUP BY 1
            """,
            (project_id,),
        )
        counts = {r["issue_no"]: r["mapped_count"] for r in cur.fetchall()}
    return {"project_id": project_id, "mapped_counts": counts}


# ══════════════════════════════════════════════════════════════════════════
#  IMPORT METRICS — triggers @register_metric decorators at package load
# ══════════════════════════════════════════════════════════════════════════

from . import metrics as _metrics  # noqa: E402, F401
from . import bug_metrics as _bug_metrics  # noqa: E402, F401
from . import reportiq_metrics as _reportiq_metrics  # noqa: E402, F401

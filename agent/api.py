"""HTTP surface for the QA agent: ingest, analyze, report.

Mounted alongside the metrics router under /api, so the dashboard talks to one
origin. The split of responsibility is deliberate:

    /api/qa/*         the agent — ingest a source, run analysis, fetch a report
    /api/metrics/*    the dashboard — aggregate queries over what it produced

Analysis runs as a job with SSE progress rather than a blocking POST. With a
model configured a full narration takes tens of seconds, and a request that
long behind a proxy is a timeout waiting to happen.

Configuration is environment-only, so pointing this at a real model endpoint on
deployment is a config change and never a code change.
"""

from __future__ import annotations

import json
import os
import queue
import tempfile
import threading
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from dashboards import replica_cursor

from .insights.report import build_report
from .llm.ollama import OllamaProvider
from .llm.prompts.chat_query import answer_question
from .llm.provider import ProviderConfig
from .sources.postgres import DEFAULT_BUG_MAPPING, PostgresSource, TableMapping
from .sources.xlsx import XlsxSource
from .store import pg

router = APIRouter(prefix="/qa", tags=["qa-agent"])

OLLAMA_HOST = os.getenv("OLLAMA_HOST")                      # unset = no narration
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b-instruct")

_provider: Optional[OllamaProvider] = (
    OllamaProvider(ProviderConfig(host=OLLAMA_HOST, model=OLLAMA_MODEL))
    if OLLAMA_HOST else None
)

MAX_UPLOAD_BYTES = int(os.getenv("QA_MAX_UPLOAD_MB", "25")) * 1024 * 1024


# ══════════════════════════════════════════════════════════════════════════
#  JOBS — in-process, one worker thread per analysis
# ══════════════════════════════════════════════════════════════════════════

@dataclass
class Job:
    id: str
    snapshot_id: str
    status: str = "queued"                 # queued | running | done | error
    stage: str = ""
    error: Optional[str] = None
    result: Optional[dict] = None
    events: "queue.Queue[dict]" = field(default_factory=queue.Queue)


class JobStore:
    """Bounded in-memory job registry.

    In-process is the right scope here: a job is a few seconds of work whose
    output is persisted to `qa_reports` the moment it finishes, so a lost job
    costs a re-click and never a result. The cap stops a long-lived process
    from accumulating them without bound.
    """

    MAX_JOBS = 64

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._order: list[str] = []
        self._lock = threading.Lock()

    def add(self, job: Job) -> None:
        with self._lock:
            self._jobs[job.id] = job
            self._order.append(job.id)
            while len(self._order) > self.MAX_JOBS:
                self._jobs.pop(self._order.pop(0), None)

    def get(self, job_id: str) -> Optional[Job]:
        with self._lock:
            return self._jobs.get(job_id)


jobs = JobStore()


def _run_analysis(job: Job) -> None:
    def on_stage(stage: str, status: str) -> None:
        job.stage = stage
        job.events.put({"type": "stage", "stage": stage, "status": status})

    job.status = "running"
    try:
        with replica_cursor() as cur:
            report = build_report(cur, job.snapshot_id, _provider, on_stage)

        pg.save_report(
            snapshot_id=job.snapshot_id,
            payload=report,
            model_enabled=report["model_enabled"],
            model_name=OLLAMA_MODEL if _provider else None,
            partial=report["partial"],
            elapsed_s=report["elapsed_s"],
        )
        job.result = report
        job.status = "done"
        job.events.put({
            "type": "end", "status": "done",
            "verdict": report["verdict"], "counts": report["counts"],
        })
    except Exception as e:  # noqa: BLE001 — surfaced to the client, not swallowed
        job.status = "error"
        job.error = f"{type(e).__name__}: {e}"
        job.events.put({"type": "end", "status": "error", "error": job.error})


# ══════════════════════════════════════════════════════════════════════════
#  HEALTH
# ══════════════════════════════════════════════════════════════════════════

@router.get("/health")
def health(snapshot_id: Optional[str] = None) -> dict[str, Any]:
    """Status for one snapshot — the one on screen, not just the newest.

    Without `snapshot_id` this always reported on the globally latest
    snapshot. A workbook re-ingested several times (each ingest makes a new
    snapshot; analysis is a separate step) can easily have a NEWER snapshot
    with no report yet while an OLDER one does — the console's "analyzed"
    badge would then read true while the dashboard, showing the older
    snapshot the user actually has selected, has no report to display. The
    caller passes what it has on screen so the two never disagree.
    """
    with replica_cursor() as cur:
        target = snapshot_id or pg.latest_snapshot_id(cur)
        has_report = pg.latest_report(cur, target) is not None if target else False

    return {
        "ok": True,
        "snapshot_id": target,
        "has_snapshot": target is not None,
        "has_report": has_report,
        "model_configured": _provider is not None,
        "model_reachable": _provider.healthy() if _provider else False,
        "model": OLLAMA_MODEL if _provider else None,
    }


# ══════════════════════════════════════════════════════════════════════════
#  INGEST
# ══════════════════════════════════════════════════════════════════════════

class IngestSummary(BaseModel):
    snapshot_id: str
    source_kind: str
    source_label: str
    fingerprint: str
    bug_count: int
    test_case_count: int
    matrix_result_count: int
    warnings: list[str]
    sheets: list[dict]


def _persist(source, kind: str) -> IngestSummary:
    result = source.fetch()
    snapshot_id = pg.write_snapshot(result, source_kind=kind, source_label=source.label())
    return IngestSummary(
        snapshot_id=snapshot_id,
        source_kind=kind,
        source_label=source.label(),
        fingerprint=result.fingerprint,
        bug_count=len(result.bugs),
        test_case_count=len(result.test_cases),
        matrix_result_count=len(result.matrix_results),
        warnings=result.warnings,
        sheets=[s.model_dump(mode="json") for s in result.sheets],
    )


@router.post("/ingest", response_model=IngestSummary)
async def ingest_workbook(file: UploadFile = File(...)) -> IngestSummary:
    """Upload an .xlsx workbook and write it as a new snapshot."""
    if not (file.filename or "").lower().endswith((".xlsx", ".xlsm")):
        raise HTTPException(400, "Expected an .xlsx or .xlsm workbook.")

    payload = await file.read()
    if len(payload) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            413, f"Workbook exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)}MB limit."
        )

    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
        tmp.write(payload)
        tmp_path = tmp.name

    try:
        return _persist(XlsxSource(tmp_path, display_name=file.filename), "xlsx")
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(422, f"Could not parse workbook: {e}") from e
    finally:
        os.unlink(tmp_path)


class PostgresIngestRequest(BaseModel):
    """Which table holds bugs, and which of its columns mean what.

    Omitted entirely, the default reads this app's own `bug_reports` table so
    the path is runnable against data that is already seeded.
    """
    bugs_table: Optional[str] = None
    bugs_columns: Optional[dict[str, str]] = None
    test_cases_table: Optional[str] = None
    test_cases_columns: Optional[dict[str, str]] = None
    label: Optional[str] = None


@router.post("/ingest/postgres", response_model=IngestSummary)
def ingest_postgres(req: PostgresIngestRequest) -> IngestSummary:
    """Read an existing Postgres table into a new snapshot."""
    bugs = DEFAULT_BUG_MAPPING
    if req.bugs_table:
        if not req.bugs_columns:
            raise HTTPException(400, "bugs_columns is required when bugs_table is given.")
        bugs = TableMapping(table=req.bugs_table, columns=req.bugs_columns)

    cases = None
    if req.test_cases_table:
        if not req.test_cases_columns:
            raise HTTPException(
                400, "test_cases_columns is required when test_cases_table is given."
            )
        cases = TableMapping(table=req.test_cases_table, columns=req.test_cases_columns)

    try:
        with replica_cursor() as cur:
            source = PostgresSource(cur, bugs=bugs, test_cases=cases, label=req.label)
            return _persist(source, "postgres")
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(422, f"Could not read source: {e}") from e


@router.get("/snapshots")
def snapshots(limit: int = 50) -> dict:
    with replica_cursor() as cur:
        return {"snapshots": pg.list_snapshots(cur, limit=min(limit, 200))}


# ══════════════════════════════════════════════════════════════════════════
#  ANALYZE
# ══════════════════════════════════════════════════════════════════════════

@router.post("/analyze")
def analyze(snapshot_id: Optional[str] = None) -> dict:
    """Kick off analysis for a snapshot (the latest one by default)."""
    with replica_cursor() as cur:
        target = snapshot_id or pg.latest_snapshot_id(cur)
        if target is None:
            raise HTTPException(404, "No snapshot yet — POST /api/qa/ingest first.")
        cur.execute("SELECT 1 FROM qa_snapshots WHERE id = %s", (target,))
        if cur.fetchone() is None:
            raise HTTPException(404, f"Unknown snapshot {target}")

    job = Job(id=str(uuid.uuid4()), snapshot_id=target)
    jobs.add(job)
    threading.Thread(target=_run_analysis, args=(job,), daemon=True).start()
    return {
        "job_id": job.id,
        "snapshot_id": target,
        "model_enabled": _provider is not None,
    }


@router.get("/analyze/{job_id}/events")
def analyze_events(job_id: str) -> StreamingResponse:
    """SSE stream of stage transitions, terminated by an `end` event."""
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "Unknown job id.")

    def stream():
        while True:
            event = job.events.get()
            yield f"data: {json.dumps(event)}\n\n"
            if event["type"] == "end":
                break

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        # Without this an nginx or similar in front will buffer the stream and
        # deliver every stage at once, which defeats the point of streaming.
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/analyze/{job_id}/result")
def analyze_result(job_id: str) -> dict:
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "Unknown job id.")
    if job.status == "error":
        raise HTTPException(500, job.error or "analysis failed")
    if job.status != "done":
        return {"status": job.status, "stage": job.stage}
    return job.result or {}


# ══════════════════════════════════════════════════════════════════════════
#  CAPABILITIES — what this snapshot actually contains
# ══════════════════════════════════════════════════════════════════════════

@router.get("/capabilities")
def capabilities(snapshot_id: Optional[str] = None) -> dict:
    """Which parts of the dashboard have data behind them.

    Not every workbook has every sheet. One with no localization matrix should
    not render a locale heatmap, an empty locale bar chart and a "0.0%"
    localization KPI — three tiles all reporting the same absence. The frontend
    hides a tile whose `requires` keys are not satisfied here, so the layout
    reflows to what the source actually contains.
    """
    with replica_cursor() as cur:
        target = snapshot_id or pg.latest_snapshot_id(cur)
        if target is None:
            return {"snapshot_id": None, "capabilities": {}}

        cur.execute(
            """
            SELECT
              (SELECT COUNT(*) FROM qa_bugs          WHERE snapshot_id = %(s)s)     AS bugs,
              (SELECT COUNT(*) FROM qa_bugs          WHERE snapshot_id = %(s)s
                                                       AND created IS NOT NULL)     AS dated_bugs,
              (SELECT COUNT(*) FROM qa_bugs          WHERE snapshot_id = %(s)s
                                                       AND is_open
                                                       AND severity_rank >= 3)      AS open_major,
              (SELECT COUNT(DISTINCT issue_type) FROM qa_bugs
                                                     WHERE snapshot_id = %(s)s
                                                       AND issue_type IS NOT NULL)  AS issue_types,
              (SELECT COUNT(*) FROM qa_test_cases    WHERE snapshot_id = %(s)s)     AS test_cases,
              (SELECT COUNT(DISTINCT COALESCE(module, section)) FROM qa_test_cases
                                                     WHERE snapshot_id = %(s)s
                                                       AND COALESCE(module, section) IS NOT NULL)
                                                                                    AS modules,
              (SELECT COUNT(*) FROM qa_matrix_results WHERE snapshot_id = %(s)s)    AS matrix_cells,
              (SELECT COUNT(DISTINCT dimension) FROM qa_matrix_results
                                                     WHERE snapshot_id = %(s)s)     AS locales,
              (SELECT COUNT(*) FROM qa_reports       WHERE snapshot_id = %(s)s)     AS reports,
              (SELECT COUNT(*) FROM qa_snapshots s2
                 WHERE s2.source_label = (SELECT source_label FROM qa_snapshots WHERE id = %(s)s)
                   AND s2.ingested_at  < (SELECT ingested_at  FROM qa_snapshots WHERE id = %(s)s))
                                                                                    AS prior_snapshots
            """,
            {"s": target},
        )
        c = dict(cur.fetchone())

    return {
        "snapshot_id": target,
        "counts": c,
        "capabilities": {
            "bugs":          c["bugs"] > 0,
            # A time series needs dates. A workbook whose bug sheet has no
            # usable created column would otherwise draw an empty chart.
            "bug_dates":     c["dated_bugs"] > 0,
            "open_major":    c["open_major"] > 0,
            "issue_types":   c["issue_types"] > 0,
            "test_cases":    c["test_cases"] > 0,
            # One module is not a breakdown — it is the same number twice.
            "modules":       c["modules"] > 1,
            "localization":  c["matrix_cells"] > 0,
            "multi_locale":  c["locales"] > 1,
            "report":        c["reports"] > 0,
            "comparison":    c["prior_snapshots"] > 0,
        },
    }


# ══════════════════════════════════════════════════════════════════════════
#  CHAT — ask the snapshot a question
# ══════════════════════════════════════════════════════════════════════════

class ChatRequest(BaseModel):
    question: str
    snapshot_id: Optional[str] = None


@router.post("/chat")
def chat(req: ChatRequest) -> dict:
    """Answer a question by compiling it to SQL, running it, and narrating.

    The compiled query and the rows come back with the answer. Chat over a QA
    dataset is only worth anything if the reader can check it, and an answer
    without its query is a claim.
    """
    question = req.question.strip()
    if not question:
        raise HTTPException(400, "Empty question.")

    with replica_cursor() as cur:
        target = req.snapshot_id or pg.latest_snapshot_id(cur)
        if target is None:
            raise HTTPException(404, "No snapshot yet — ingest a workbook first.")

        if _provider is None:
            return {
                "answer": (
                    "No model is configured on the server, so questions can't be "
                    "compiled into a query. Set OLLAMA_HOST to enable chat — the "
                    "dashboard and findings work without it."
                ),
                "entity": "unknown", "row_count": 0, "compiled_query": {},
                "sql": "", "rows": [], "used_model": False,
                "error": "no_model_configured",
            }

        result = answer_question(_provider, cur, question, target)

    return result.model_dump()


@router.get("/report")
def report(snapshot_id: Optional[str] = None) -> dict:
    """The newest persisted report, for the latest snapshot unless told otherwise."""
    with replica_cursor() as cur:
        target = snapshot_id or pg.latest_snapshot_id(cur)
        if target is None:
            raise HTTPException(404, "No snapshot yet — POST /api/qa/ingest first.")
        found = pg.latest_report(cur, target)
    if found is None:
        raise HTTPException(404, "No report yet — POST /api/qa/analyze first.")
    return found

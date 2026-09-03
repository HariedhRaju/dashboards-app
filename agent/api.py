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
from datetime import date, timedelta
from typing import Any, Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from dashboards import replica_cursor

from .insights.report import build_report
from .insights.stats import ReportScope
from . import scheduler as _scheduler_mod
from .llm.ollama import OllamaProvider
from .llm.prompts.chat_query import answer_question
from .llm.provider import ProviderConfig
from .sources.postgres import DEFAULT_BUG_MAPPING, PostgresSource, TableMapping
from .sources.multi import MultiXlsxSource, default_label
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
    #: Every filter narrowing the analysis — date window plus dimensions.
    scope: Optional[ReportScope] = None
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
            report = build_report(cur, job.snapshot_id, _provider, on_stage, job.scope)

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
    #: One entry per uploaded file, including any that failed to parse.
    source_files: list[dict] = []


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
        source_files=result.source_files,
    )


@router.post("/ingest", response_model=IngestSummary)
async def ingest_workbook(
    files: list[UploadFile] = File(...),
    label: Optional[str] = Form(None),
) -> IngestSummary:
    """Upload one or more .xlsx workbooks and write them as ONE snapshot.

    Several files, one analysis set: a QA cycle is usually a couple of test
    plans plus a couple of bug trackers, and the questions worth asking span
    them. Every record keeps the name of the file it came from, so the report
    can give both the aggregate and the per-plan breakdown.

    The parameter is `files` (repeated) rather than `file`; a single upload is
    just a set of one and goes through the same path, so attribution is
    written the same way regardless of how many arrived.
    """
    if not files:
        raise HTTPException(400, "No files uploaded.")

    staged: list[tuple[str, str]] = []
    try:
        total = 0
        for f in files:
            name = f.filename or "workbook.xlsx"
            if not name.lower().endswith((".xlsx", ".xlsm")):
                raise HTTPException(400, f"{name}: expected an .xlsx or .xlsm workbook.")
            payload = await f.read()
            total += len(payload)
            # The cap is on the upload as a whole, not per file — ten files
            # just under the limit each is the same problem for the server as
            # one file ten times over it.
            if total > MAX_UPLOAD_BYTES:
                raise HTTPException(
                    413,
                    f"Upload exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)}MB limit.",
                )
            with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
                tmp.write(payload)
                staged.append((tmp.name, name))

        source = MultiXlsxSource(
            staged, label=label or default_label([n for _, n in staged])
        )
        return _persist(source, "xlsx")
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(422, f"Could not parse upload: {e}") from e
    finally:
        for path, _ in staged:
            try:
                os.unlink(path)
            except OSError:
                pass


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
def analyze(
    snapshot_id: Optional[str] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    severity: Optional[str] = None,
    status: Optional[str] = None,
    issue_type: Optional[str] = None,
    module: Optional[str] = None,
    test_status: Optional[str] = None,
    test_priority: Optional[str] = None,
    reporter: Optional[str] = None,
) -> dict:
    """Kick off analysis for a snapshot (the latest one by default).

    `date_from`/`date_to` are inclusive calendar dates from the UI's range
    picker. Passing neither analyses the whole set, which is the default.
    Passing one without the other is rejected rather than half-applied — an
    open-ended range reads as a typo more often than an intention.

    The remaining params are the same dimension filters the dashboard's own
    filter bar applies to its tiles — severity/status/issue_type/reporter for
    bugs, module/test_status/test_priority/reporter for test cases. Threading
    them into the SAME `ReportScope` the dashboard's queries build is what
    keeps the narrated findings describing the data the reader is looking at,
    rather than a stale unfiltered picture.

    The window narrows bugs only; test cases and localization carry no
    per-row date. The report records the whole scope so the reader is never
    left inferring which numbers a filter or range touched.
    """
    if (date_from is None) != (date_to is None):
        raise HTTPException(
            400, "Provide both date_from and date_to, or neither for the whole set."
        )
    if date_from and date_to and date_from > date_to:
        raise HTTPException(400, "date_from is after date_to.")

    # The picker's end date is inclusive to a human and exclusive to SQL.
    window = (date_from, date_to + timedelta(days=1)) if date_from and date_to else None

    scope = ReportScope(
        window=window,
        severity=severity,
        status=status,
        issue_type=issue_type,
        module=module,
        test_status=test_status,
        test_priority=test_priority,
        reporter=reporter,
    )

    with replica_cursor() as cur:
        target = snapshot_id or pg.latest_snapshot_id(cur)
        if target is None:
            raise HTTPException(404, "No snapshot yet — POST /api/qa/ingest first.")
        cur.execute("SELECT 1 FROM qa_snapshots WHERE id = %s", (target,))
        if cur.fetchone() is None:
            raise HTTPException(404, f"Unknown snapshot {target}")

    job = Job(id=str(uuid.uuid4()), snapshot_id=target, scope=scope)
    jobs.add(job)
    threading.Thread(target=_run_analysis, args=(job,), daemon=True).start()
    return {
        "job_id": job.id,
        "snapshot_id": target,
        "model_enabled": _provider is not None,
        "window": (
            {"start": str(date_from), "end": str(date_to)} if window else None
        ),
        "filters": (
            {
                "severity": severity, "status": status, "issue_type": issue_type,
                "module": module, "test_status": test_status,
                "test_priority": test_priority, "reporter": reporter,
            } if scope.is_scoped else None
        ),
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
              (SELECT COUNT(DISTINCT source_file) FROM (
                   SELECT source_file FROM qa_bugs          WHERE snapshot_id = %(s)s
                   UNION SELECT source_file FROM qa_test_cases     WHERE snapshot_id = %(s)s
                   UNION SELECT source_file FROM qa_matrix_results WHERE snapshot_id = %(s)s
               ) f WHERE source_file <> '')                                         AS source_files,
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
            # A snapshot resolved at all — for tiles like ingest confidence
            # that describe the READ, not any one of bugs/tests/localization,
            # and so shouldn't gate on any of them individually.
            "has_data":      True,
            "bugs":          c["bugs"] > 0,
            # A time series needs dates. A workbook whose bug sheet has no
            # usable created column would otherwise draw an empty chart.
            "bug_dates":     c["dated_bugs"] > 0,
            "open_major":    c["open_major"] > 0,
            "issue_types":   c["issue_types"] > 0,
            "test_cases":    c["test_cases"] > 0,
            # One module is not a breakdown — it is the same number twice.
            "modules":       c["modules"] > 1,
            # One file is not a breakdown, same rule as modules.
            "multi_file":    c["source_files"] > 1,
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


@router.get("/reports")
def reports(snapshot_id: Optional[str] = None, limit: int = 50) -> dict:
    """Report history — every past report (manual or scheduled), newest first.

    Deliberately light: id/verdict/headline/counts, not the full payload —
    see GET /report/{report_id} to open one specific historical report.
    """
    with replica_cursor() as cur:
        return {"reports": pg.list_reports(cur, snapshot_id=snapshot_id, limit=min(limit, 200))}


@router.get("/report/{report_id}")
def report_by_id(report_id: str) -> dict:
    """One specific historical report, in full — "open last Tuesday's report"."""
    with replica_cursor() as cur:
        found = pg.report_by_id(cur, report_id)
    if found is None:
        raise HTTPException(404, f"Unknown report {report_id}")
    return found


# ══════════════════════════════════════════════════════════════════════════
#  SCHEDULES — recurring analysis
# ══════════════════════════════════════════════════════════════════════════

class ScheduleCreate(BaseModel):
    label: str
    source_label: str
    cadence: str                          # "daily" | "weekly"
    run_at_hour: int = 6
    run_at_minute: int = 0
    weekday: Optional[int] = None         # 0=Monday..6=Sunday, weekly only
    window_mode: str = "rolling"          # "rolling" | "all"


@router.post("/schedules")
def create_schedule(req: ScheduleCreate) -> dict:
    if req.cadence not in ("daily", "weekly"):
        raise HTTPException(400, "cadence must be 'daily' or 'weekly'.")
    if req.cadence == "weekly" and req.weekday is None:
        raise HTTPException(400, "weekday (0=Monday..6=Sunday) is required for a weekly cadence.")
    if not (0 <= req.run_at_hour <= 23 and 0 <= req.run_at_minute <= 59):
        raise HTTPException(400, "run_at_hour/run_at_minute out of range.")
    with pg.primary_cursor() as cur:
        return pg.create_schedule(
            cur, req.label, req.source_label, req.cadence,
            req.run_at_hour, req.run_at_minute, req.weekday, req.window_mode,
        )


@router.get("/schedules")
def list_schedules() -> dict:
    with replica_cursor() as cur:
        return {"schedules": pg.list_schedules(cur)}


@router.post("/schedules/{schedule_id}/enable")
def enable_schedule(schedule_id: str, enabled: bool = True) -> dict:
    with pg.primary_cursor() as cur:
        pg.set_schedule_enabled(cur, schedule_id, enabled)
    return {"id": schedule_id, "enabled": enabled}


@router.delete("/schedules/{schedule_id}")
def delete_schedule(schedule_id: str) -> dict:
    with pg.primary_cursor() as cur:
        pg.delete_schedule(cur, schedule_id)
    return {"id": schedule_id, "deleted": True}


@router.get("/schedules/{schedule_id}/runs")
def schedule_run_history(schedule_id: str, limit: int = 20) -> dict:
    with replica_cursor() as cur:
        return {"runs": pg.schedule_runs(cur, schedule_id, min(limit, 100))}


@router.post("/schedules/{schedule_id}/run-now")
def run_schedule_now(schedule_id: str) -> dict:
    """Fire one schedule immediately, out of band from its normal cadence.

    Runs synchronously — a scheduled analysis is the same handful of seconds
    of work a manual /analyze is, so there is no need for the job/SSE
    machinery that exists for the interactive UI's progress bar.
    """
    try:
        _scheduler_mod.run_schedule_now(schedule_id, _provider, OLLAMA_MODEL if _provider else None)
    except ValueError as e:
        raise HTTPException(404, str(e))
    with replica_cursor() as cur:
        runs = pg.schedule_runs(cur, schedule_id, limit=1)
    return {"id": schedule_id, "last_run": runs[0] if runs else None}


# ══════════════════════════════════════════════════════════════════════════
#  SCHEDULER LIFECYCLE — started/stopped by the host app
# ══════════════════════════════════════════════════════════════════════════

_scheduler_thread: Optional[_scheduler_mod.SchedulerThread] = None


def start_scheduler() -> None:
    """Start the background polling loop. Called once from the host app's
    startup hook — never imported and started twice, or two loops would race
    to claim the same due schedules."""
    global _scheduler_thread
    if _scheduler_thread is not None:
        return
    _scheduler_thread = _scheduler_mod.SchedulerThread(_provider, OLLAMA_MODEL if _provider else None)
    _scheduler_thread.start()


def stop_scheduler() -> None:
    global _scheduler_thread
    if _scheduler_thread is not None:
        _scheduler_thread.stop()
        _scheduler_thread = None

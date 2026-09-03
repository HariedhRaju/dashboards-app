"""In-process background scheduler for recurring QA analysis.

There is no OS-level cron here — this dev environment has no persistent
service to hand a schedule to. Instead a single background thread, started
once at app startup, polls `qa_schedules` and fires any that are due. The
trade this makes explicit: a schedule only fires while this backend process
is alive. A restart does not lose the schedule (it is a Postgres row), but it
does lose any run that would have fired while the process was down — the
next poll picks up wherever `next_run_at` says, it does not back-fill missed
runs. That is an accepted limitation of running without a real scheduler
service, not an oversight.

Each firing re-resolves `source_label` to whatever the latest matching
snapshot is AT RUN TIME, not the snapshot that existed when the schedule was
created — a schedule names a recurring source ("the Monday QA export"), not
one frozen upload.
"""

from __future__ import annotations

import logging
import threading
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from .insights.report import build_report
from .insights.stats import ReportScope
from .store import pg

logger = logging.getLogger("qa.scheduler")

POLL_INTERVAL_S = 30


def _rolling_window(cadence: str, now: datetime) -> tuple[date, date]:
    """Calendar-date window a run of this cadence should cover.

    Daily covers the full day before the run — a 6am run reports on
    yesterday, not a five-hour fragment of today. Weekly covers the 7 days
    before it. Both ends follow the same (start, end-exclusive) convention
    the manual /analyze endpoint uses, so a scheduled report and a manually
    filtered one read identically.
    """
    end = now.date()
    start = end - timedelta(days=7 if cadence == "weekly" else 1)
    return start, end


def _next_run_at(
    cadence: str,
    run_at_hour: int,
    run_at_minute: int,
    weekday: Optional[int],
    after: datetime,
) -> datetime:
    """Next strictly-future firing time for this schedule.

    Computed from `after` (normally "now"), not from the previous
    `next_run_at` — so a schedule that missed several cycles while the
    process was down rolls forward to the next real occurrence instead of
    firing once per missed cycle to catch up.
    """
    candidate = after.replace(hour=run_at_hour, minute=run_at_minute, second=0, microsecond=0)
    if cadence == "weekly":
        target_wd = weekday if weekday is not None else 0
        days_ahead = (target_wd - candidate.weekday()) % 7
        candidate += timedelta(days=days_ahead)
        if candidate <= after:
            candidate += timedelta(days=7)
    else:
        if candidate <= after:
            candidate += timedelta(days=1)
    return candidate


def _resolve_snapshot(cur, source_label: str) -> Optional[str]:
    """Latest snapshot ingested under this schedule's source label."""
    cur.execute(
        "SELECT id::text FROM qa_snapshots WHERE source_label = %s"
        " ORDER BY ingested_at DESC LIMIT 1",
        (source_label,),
    )
    row = cur.fetchone()
    return row["id"] if row else None


def _run_one(sched: dict, now: datetime, provider, model_name: Optional[str]) -> None:
    schedule_id = sched["id"]
    next_run_at = _next_run_at(
        sched["cadence"], sched["run_at_hour"], sched["run_at_minute"],
        sched["weekday"], now,
    )
    try:
        with pg.primary_cursor() as cur:
            snapshot_id = _resolve_snapshot(cur, sched["source_label"])
            if snapshot_id is None:
                raise RuntimeError(
                    f"No snapshot found for source_label={sched['source_label']!r}"
                )
            scope = ReportScope(
                window=_rolling_window(sched["cadence"], now)
                if sched["window_mode"] == "rolling" else None
            )
            report = build_report(cur, snapshot_id, provider, scope=scope)

        report_id = pg.save_report(
            snapshot_id=snapshot_id,
            payload=report,
            model_enabled=report["model_enabled"],
            model_name=model_name if provider else None,
            partial=report["partial"],
            elapsed_s=report["elapsed_s"],
        )
        with pg.primary_cursor() as cur:
            pg.record_schedule_result(
                cur, schedule_id, next_run_at, status="ok",
                report_id=report_id, snapshot_id=snapshot_id,
            )
        logger.info("schedule %s (%s) ran ok -> report %s", schedule_id, sched["label"], report_id)
    except Exception as e:  # noqa: BLE001 — recorded on the row, never crashes the loop
        logger.exception("schedule %s (%s) failed", schedule_id, sched["label"])
        with pg.primary_cursor() as cur:
            pg.record_schedule_result(cur, schedule_id, next_run_at, status="error", error=str(e))


def run_due_schedules(provider, model_name: Optional[str]) -> int:
    """Run every schedule whose time has come. Returns how many ran.

    Exposed separately from the loop so a "run now" API trigger and a test
    can both call it directly without waiting on the poll interval.
    """
    now = datetime.now(timezone.utc)
    with pg.primary_cursor() as cur:
        due = pg.due_schedules(cur, now)
    for sched in due:
        _run_one(sched, now, provider, model_name)
    return len(due)


def run_schedule_now(schedule_id: str, provider, model_name: Optional[str]) -> None:
    """Force one schedule to run immediately, regardless of `next_run_at`."""
    with pg.primary_cursor() as cur:
        cur.execute(
            "SELECT id::text, label, source_label, cadence, run_at_hour,"
            " run_at_minute, weekday, window_mode FROM qa_schedules WHERE id = %s",
            (schedule_id,),
        )
        row = cur.fetchone()
    if row is None:
        raise ValueError(f"Unknown schedule {schedule_id}")
    _run_one(dict(row), datetime.now(timezone.utc), provider, model_name)


class SchedulerThread(threading.Thread):
    """The loop itself — one instance, started once at app startup and kept
    for the life of the process."""

    def __init__(self, provider, model_name: Optional[str], poll_interval_s: float = POLL_INTERVAL_S):
        super().__init__(daemon=True, name="qa-scheduler")
        self._provider = provider
        self._model_name = model_name
        self._interval = poll_interval_s
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        logger.info("QA scheduler loop started (poll every %ss)", self._interval)
        while not self._stop.is_set():
            try:
                run_due_schedules(self._provider, self._model_name)
            except Exception:  # noqa: BLE001 — one bad poll must not kill the loop
                logger.exception("scheduler poll failed")
            self._stop.wait(self._interval)

"""Persist an ingest run as one immutable Postgres snapshot.

The dashboards package holds a deliberately read-only pool — every metric runs
under `default_transaction_read_only`. Ingest is the one path in this app that
writes, so it gets its own small pool against the primary rather than
loosening that guarantee for everyone.

A snapshot is written in a single transaction. A half-ingested workbook would
be worse than none at all: the dashboard cannot tell "this build fixed 40 bugs"
apart from "40 bugs failed to load", and both render as progress.
"""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from typing import Iterator, Optional

from psycopg2.extras import RealDictCursor, execute_batch
from psycopg2.pool import ThreadedConnectionPool

from ..ingest.models import SEVERITY_RANK, IngestResult

_PRIMARY_DSN = os.getenv(
    "DASHBOARDS_PRIMARY_DSN",
    os.getenv("DASHBOARDS_REPLICA_DSN", os.getenv("DATABASE_URL")),
)
if not _PRIMARY_DSN:
    raise RuntimeError(
        "DASHBOARDS_PRIMARY_DSN (or DASHBOARDS_REPLICA_DSN / DATABASE_URL) must be set"
    )

# Ingest is rare and serial; a large pool here would only hold connections the
# metric pool needs.
_pool = ThreadedConnectionPool(minconn=1, maxconn=4, dsn=_PRIMARY_DSN)

# Batched inserts. Large enough that a 60-row workbook is one round trip,
# small enough that a 50k-cell localization matrix does not build one
# multi-megabyte statement.
_BATCH = 500


@contextmanager
def primary_cursor() -> Iterator[RealDictCursor]:
    """Yield a writable cursor on the primary, committing on clean exit."""
    conn = _pool.getconn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        _pool.putconn(conn)


# ══════════════════════════════════════════════════════════════════════════
#  WRITE
# ══════════════════════════════════════════════════════════════════════════

def write_snapshot(
    result: IngestResult,
    source_kind: str = "xlsx",
    source_label: Optional[str] = None,
) -> str:
    """Insert one snapshot and everything under it. Returns the snapshot id."""
    label = source_label or os.path.basename(result.source_path) or "workbook"

    with primary_cursor() as cur:
        cur.execute(
            """
            INSERT INTO qa_snapshots (source_kind, source_label, fingerprint,
                                      sheets_json, warnings, source_files)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                source_kind,
                label,
                result.fingerprint,
                json.dumps([s.model_dump(mode="json") for s in result.sheets]),
                json.dumps(result.warnings),
                json.dumps(result.source_files),
            ),
        )
        snapshot_id = str(cur.fetchone()["id"])

        _write_bugs(cur, snapshot_id, result)
        _write_test_cases(cur, snapshot_id, result)
        _write_matrix(cur, snapshot_id, result)

    return snapshot_id


def _write_bugs(cur, snapshot_id: str, result: IngestResult) -> None:
    if not result.bugs:
        return
    # The sheet can repeat a bug key (issue #57 appears twice in the pilot
    # workbook). source_row disambiguates, and the UNIQUE carries it, so both
    # rows survive and the duplicate becomes a finding instead of a lost row.
    execute_batch(
        cur,
        """
        INSERT INTO qa_bugs (snapshot_id, source_file, bug_key, source_sheet,
            source_row, reporter, created, severity, severity_rank, issue_type,
            summary, description, steps, actual, expected, build, status,
            is_open, resolution, dev_comments, comments)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (snapshot_id, source_file, source_sheet, bug_key, source_row)
            DO NOTHING
        """,
        [
            (
                snapshot_id, b.source_file, b.id, b.source_sheet, b.source_row,
                b.reporter, b.created, b.severity.value, SEVERITY_RANK[b.severity],
                b.issue_type, b.summary, b.description, b.steps, b.actual,
                b.expected, b.build, b.status.value, b.is_open, b.resolution,
                b.dev_comments, b.comments,
            )
            for b in result.bugs
        ],
        page_size=_BATCH,
    )


def _write_test_cases(cur, snapshot_id: str, result: IngestResult) -> None:
    if not result.test_cases:
        return
    # execute_batch cannot be used here: the bug links need each row's
    # generated id, and only a single multi-row INSERT ... RETURNING gives
    # them back in insert order.
    #
    # Chunked because Postgres caps a statement at 65535 bound parameters.
    # At 11 columns that is 5957 rows, which a large test plan will exceed —
    # and the failure mode would be a workbook that ingests fine in testing
    # and rejects the real one.
    rows = [
        (
            snapshot_id, tc.source_file, tc.source_sheet, tc.source_row,
            tc.case_id, tc.reporter, tc.module, tc.section, tc.title, tc.priority,
            tc.preconditions, tc.description, tc.steps, tc.expected,
            tc.status.value, tc.was_executed, tc.comments,
        )
        for tc in result.test_cases
    ]
    cols_per_row = 17
    chunk_size = min(_BATCH, 65535 // cols_per_row)
    placeholder = "(" + ",".join(["%s"] * cols_per_row) + ")"

    ids: list[str] = []
    for i in range(0, len(rows), chunk_size):
        chunk = rows[i:i + chunk_size]
        cur.execute(
            f"""
            INSERT INTO qa_test_cases (snapshot_id, source_file, source_sheet,
                source_row, case_id, reporter, module, section, title, priority,
                preconditions, description, steps, expected, status,
                was_executed, comments)
            VALUES {",".join([placeholder] * len(chunk))}
            RETURNING id
            """,
            [v for row in chunk for v in row],
        )
        ids.extend(str(r["id"]) for r in cur.fetchall())

    links = [
        (tc_id, bug_key)
        for tc_id, tc in zip(ids, result.test_cases)
        for bug_key in tc.linked_bug_ids
    ]
    if links:
        execute_batch(
            cur,
            "INSERT INTO qa_test_case_bugs (test_case_id, bug_key)"
            " VALUES (%s, %s) ON CONFLICT DO NOTHING",
            links,
            page_size=_BATCH,
        )


def _write_matrix(cur, snapshot_id: str, result: IngestResult) -> None:
    if not result.matrix_results:
        return
    execute_batch(
        cur,
        """
        INSERT INTO qa_matrix_results (snapshot_id, source_file, source_sheet,
            source_row, section, item, dimension, status, comment)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """,
        [
            (
                snapshot_id, m.source_file, m.source_sheet, m.source_row,
                m.section, m.item, m.dimension, m.status.value, m.comment,
            )
            for m in result.matrix_results
        ],
        page_size=_BATCH,
    )


# ══════════════════════════════════════════════════════════════════════════
#  REPORTS
# ══════════════════════════════════════════════════════════════════════════

def save_report(
    snapshot_id: str,
    payload: dict,
    model_enabled: bool,
    model_name: Optional[str],
    partial: bool,
    elapsed_s: float,
) -> str:
    with primary_cursor() as cur:
        cur.execute(
            """
            INSERT INTO qa_reports (snapshot_id, model_enabled, model_name,
                                    partial, elapsed_s, payload)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (snapshot_id, model_enabled, model_name, partial, elapsed_s,
             json.dumps(payload, default=str)),
        )
        return str(cur.fetchone()["id"])


# ══════════════════════════════════════════════════════════════════════════
#  READ HELPERS — used by the API and by the metrics layer
# ══════════════════════════════════════════════════════════════════════════

def latest_snapshot_id(cur) -> Optional[str]:
    """Most recent snapshot, or None if nothing has been ingested."""
    cur.execute("SELECT id FROM qa_snapshots ORDER BY ingested_at DESC LIMIT 1")
    row = cur.fetchone()
    return str(row["id"]) if row else None


def list_snapshots(cur, limit: int = 50) -> list[dict]:
    cur.execute(
        """
        SELECT s.id::text,
               s.source_kind,
               s.source_label,
               s.fingerprint,
               s.ingested_at,
               jsonb_array_length(s.warnings)                       AS warning_count,
               (SELECT COUNT(*) FROM qa_bugs b           WHERE b.snapshot_id = s.id) AS bugs,
               (SELECT COUNT(*) FROM qa_test_cases t     WHERE t.snapshot_id = s.id) AS test_cases,
               (SELECT COUNT(*) FROM qa_matrix_results m WHERE m.snapshot_id = s.id) AS matrix_cells,
               (SELECT COUNT(*) FROM qa_reports r        WHERE r.snapshot_id = s.id) AS reports
        FROM qa_snapshots s
        ORDER BY s.ingested_at DESC
        LIMIT %s
        """,
        (limit,),
    )
    rows = [dict(r) for r in cur.fetchall()]
    for r in rows:
        r["ingested_at"] = r["ingested_at"].isoformat()
    return rows


def latest_report(cur, snapshot_id: Optional[str] = None) -> Optional[dict]:
    """Newest persisted report, optionally scoped to one snapshot."""
    if snapshot_id:
        cur.execute(
            "SELECT payload, generated_at, partial, model_enabled, model_name"
            " FROM qa_reports WHERE snapshot_id = %s"
            " ORDER BY generated_at DESC LIMIT 1",
            (snapshot_id,),
        )
    else:
        cur.execute(
            "SELECT payload, generated_at, partial, model_enabled, model_name"
            " FROM qa_reports ORDER BY generated_at DESC LIMIT 1"
        )
    row = cur.fetchone()
    if row is None:
        return None
    payload = dict(row["payload"])
    payload["generated_at"] = row["generated_at"].isoformat()
    payload["partial"] = row["partial"]
    payload["model_enabled"] = row["model_enabled"]
    payload["model_name"] = row["model_name"]
    return payload


def report_by_id(cur, report_id: str) -> Optional[dict]:
    """One specific historical report, in full — "open last Tuesday's report"."""
    cur.execute(
        "SELECT payload, generated_at, partial, model_enabled, model_name"
        " FROM qa_reports WHERE id = %s",
        (report_id,),
    )
    row = cur.fetchone()
    if row is None:
        return None
    payload = dict(row["payload"])
    payload["generated_at"] = row["generated_at"].isoformat()
    payload["partial"] = row["partial"]
    payload["model_enabled"] = row["model_enabled"]
    payload["model_name"] = row["model_name"]
    return payload


def list_reports(cur, snapshot_id: Optional[str] = None, limit: int = 50) -> list[dict]:
    """Report history — id, verdict, headline, generated_at — WITHOUT the full
    payload. A history list is read often and shows many rows; pulling the
    complete JSONB (findings, evidence, stats) for each would be needless
    weight for a list the reader clicks through one row of.
    """
    if snapshot_id:
        cur.execute(
            """
            SELECT id::text, snapshot_id::text, generated_at, partial,
                   model_enabled, model_name,
                   payload->'verdict'                          AS verdict,
                   payload->'executive_summary'->>'headline'    AS headline,
                   payload->'counts'                            AS counts
            FROM qa_reports WHERE snapshot_id = %s
            ORDER BY generated_at DESC LIMIT %s
            """,
            (snapshot_id, limit),
        )
    else:
        cur.execute(
            """
            SELECT r.id::text, r.snapshot_id::text, r.generated_at, r.partial,
                   r.model_enabled, r.model_name,
                   r.payload->'verdict'                        AS verdict,
                   r.payload->'executive_summary'->>'headline'  AS headline,
                   r.payload->'counts'                          AS counts,
                   s.source_label
            FROM qa_reports r JOIN qa_snapshots s ON s.id = r.snapshot_id
            ORDER BY r.generated_at DESC LIMIT %s
            """,
            (limit,),
        )
    rows = [dict(r) for r in cur.fetchall()]
    for r in rows:
        r["generated_at"] = r["generated_at"].isoformat()
        # jsonb_extract_path via -> already gives Python str/dict for scalars,
        # but a bare JSON string comes back quoted; strip that here so the
        # caller gets a plain string instead of '"blocked"'.
        if isinstance(r.get("verdict"), str):
            r["verdict"] = r["verdict"].strip('"')
    return rows


# ══════════════════════════════════════════════════════════════════════════
#  SCHEDULES — recurring analysis (agent/scheduler.py runs these)
# ══════════════════════════════════════════════════════════════════════════

def create_schedule(
    cur,
    label: str,
    source_label: str,
    cadence: str,
    run_at_hour: int = 6,
    run_at_minute: int = 0,
    weekday: Optional[int] = None,
    window_mode: str = "rolling",
) -> dict:
    cur.execute(
        """
        INSERT INTO qa_schedules
            (label, source_label, cadence, run_at_hour, run_at_minute,
             weekday, window_mode, next_run_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, now())
        RETURNING id::text, label, source_label, cadence, run_at_hour,
                  run_at_minute, weekday, window_mode, enabled,
                  created_at, next_run_at
        """,
        (label, source_label, cadence, run_at_hour, run_at_minute, weekday,
         window_mode),
    )
    row = dict(cur.fetchone())
    row["created_at"] = row["created_at"].isoformat()
    row["next_run_at"] = row["next_run_at"].isoformat()
    return row


def list_schedules(cur) -> list[dict]:
    cur.execute(
        """
        SELECT s.id::text, s.label, s.source_label, s.cadence, s.run_at_hour,
               s.run_at_minute, s.weekday, s.window_mode, s.enabled,
               s.created_at, s.last_run_at, s.last_status, s.last_error,
               s.next_run_at,
               (SELECT COUNT(*) FROM qa_schedule_runs r WHERE r.schedule_id = s.id) AS run_count
        FROM qa_schedules s
        ORDER BY s.created_at DESC
        """
    )
    rows = [dict(r) for r in cur.fetchall()]
    for r in rows:
        for k in ("created_at", "last_run_at", "next_run_at"):
            if r.get(k) is not None:
                r[k] = r[k].isoformat()
    return rows


def due_schedules(cur, now) -> list[dict]:
    """Every enabled schedule whose next_run_at has arrived — the scheduler's
    own poll query. Locked FOR UPDATE SKIP LOCKED so two scheduler loops (a
    hot-reloading dev server spinning up a second process, say) never both
    claim the same run."""
    cur.execute(
        """
        SELECT id::text, label, source_label, cadence, run_at_hour,
               run_at_minute, weekday, window_mode
        FROM qa_schedules
        WHERE enabled AND next_run_at <= %s
        FOR UPDATE SKIP LOCKED
        """,
        (now,),
    )
    return [dict(r) for r in cur.fetchall()]


def set_schedule_enabled(cur, schedule_id: str, enabled: bool) -> None:
    cur.execute("UPDATE qa_schedules SET enabled = %s WHERE id = %s", (enabled, schedule_id))


def delete_schedule(cur, schedule_id: str) -> None:
    cur.execute("DELETE FROM qa_schedules WHERE id = %s", (schedule_id,))


def record_schedule_result(
    cur,
    schedule_id: str,
    next_run_at,
    status: str,
    report_id: Optional[str] = None,
    snapshot_id: Optional[str] = None,
    error: Optional[str] = None,
) -> None:
    """Persist the outcome of one scheduled run and roll the schedule forward.

    Rolling forward happens here, unconditionally — even on error. A schedule
    stuck retrying every poll cycle against a source that keeps failing would
    starve every other schedule's turn; it retries at its normal cadence
    instead, and `last_error` is what tells a reader why.
    """
    cur.execute(
        """
        INSERT INTO qa_schedule_runs (schedule_id, report_id, snapshot_id, status, error)
        VALUES (%s, %s, %s, %s, %s)
        """,
        (schedule_id, report_id, snapshot_id, status, error),
    )
    cur.execute(
        """
        UPDATE qa_schedules
        SET last_run_at = now(), last_status = %s, last_error = %s, next_run_at = %s
        WHERE id = %s
        """,
        (status, error, next_run_at, schedule_id),
    )


def schedule_runs(cur, schedule_id: str, limit: int = 20) -> list[dict]:
    cur.execute(
        """
        SELECT r.id::text, r.ran_at, r.status, r.error,
               r.report_id::text, r.snapshot_id::text,
               rep.payload->'verdict' AS verdict,
               rep.payload->'executive_summary'->>'headline' AS headline
        FROM qa_schedule_runs r
        LEFT JOIN qa_reports rep ON rep.id = r.report_id
        WHERE r.schedule_id = %s
        ORDER BY r.ran_at DESC LIMIT %s
        """,
        (schedule_id, limit),
    )
    rows = [dict(r) for r in cur.fetchall()]
    for r in rows:
        r["ran_at"] = r["ran_at"].isoformat()
        if isinstance(r.get("verdict"), str):
            r["verdict"] = r["verdict"].strip('"')
    return rows

"""QA insights metrics — the dashboard half of the reporting agent.

Reads the snapshots the agent writes (`agent/store/pg.py`) plus the reports it
narrates. Schema lives in `setup/qa_schema.sql`.

    qa_snapshots        one ingest run — a workbook, or a Postgres source
    qa_bugs             the bug tracker, normalized
    qa_test_cases       the test plan, normalized (+ qa_test_case_bugs links)
    qa_matrix_results   the localization matrix, unpivoted to long form
    qa_reports          the agent's narrated output, as JSONB

A workbook is a point-in-time statement of a whole test cycle, not a stream of
dated events. So the SNAPSHOT is the unit of scope throughout: the dashboard's
date range selects which snapshot is in view, and every row in it is then
shown. Bug `created` dates still drive the time series' x-axis, but they never
filter rows — a workbook logged last September, opened under a default "last 30
days" range, would otherwise match nothing and render empty tiles beside a KPI
row reporting 61 bugs.

For the same reason every KPI compares to the PREVIOUS SNAPSHOT of the same
source rather than the previous time period. That is the one substantive
departure from the other dashboards in this app, and it asks the better
question: not "how did last month look" but "what did this build change".
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from psycopg2.extras import RealDictCursor

from . import QaFilters, auto_grain, register_metric


# ══════════════════════════════════════════════════════════════════════════
#  SNAPSHOT RESOLUTION
# ══════════════════════════════════════════════════════════════════════════

def _snapshot_id(cur, f: QaFilters) -> Optional[str]:
    """The snapshot in scope: the pinned one, else the newest in the window."""
    if f.snapshot_id is not None:
        return str(f.snapshot_id)
    cur.execute(
        "SELECT id FROM qa_snapshots WHERE ingested_at <= %s"
        " ORDER BY ingested_at DESC LIMIT 1",
        [f.date_range_end],
    )
    row = cur.fetchone()
    if row:
        return str(row["id"])
    # A workbook ingested today should still render against a range that ends
    # yesterday — an empty dashboard is a worse answer than a labelled one.
    cur.execute("SELECT id FROM qa_snapshots ORDER BY ingested_at DESC LIMIT 1")
    row = cur.fetchone()
    return str(row["id"]) if row else None


def _previous_snapshot_id(cur, snapshot_id: str) -> Optional[str]:
    """The prior snapshot OF THE SAME SOURCE.

    Scoped to `source_label` on purpose. "What did this build change" only
    means something between comparable readings — a 15,000-row Postgres table
    against last week's 61-row workbook is not a regression, it is a different
    question being asked. A source with no prior reading returns None, and the
    UI shows no delta rather than an invented one.
    """
    cur.execute(
        """
        SELECT id FROM qa_snapshots
        WHERE source_label = (SELECT source_label FROM qa_snapshots WHERE id = %s)
          AND ingested_at < (SELECT ingested_at FROM qa_snapshots WHERE id = %s)
        ORDER BY ingested_at DESC LIMIT 1
        """,
        [snapshot_id, snapshot_id],
    )
    row = cur.fetchone()
    return str(row["id"]) if row else None


EMPTY_SCALAR = {"kind": "scalar", "value": 0, "previous": None, "format": "number"}


# ══════════════════════════════════════════════════════════════════════════
#  FILTER HELPERS
# ══════════════════════════════════════════════════════════════════════════

def _bug_where(f: QaFilters, snap: str) -> tuple[str, list]:
    """WHERE for qa_bugs, scoped to one snapshot.

    The dashboard's date range deliberately does NOT filter rows here. A
    snapshot is a point-in-time statement of a whole test cycle, so the range
    selects WHICH snapshot is in view (see `_snapshot_id`) and everything in
    that snapshot is then shown.

    Filtering rows by `created` as well looks reasonable and is a trap: a
    workbook logged last September, opened under a default "last 30 days"
    range, matches nothing — and the dashboard renders an empty bug timeline
    and an empty blocker table next to a KPI row reporting 61 bugs. The tiles
    were not broken; they were being asked a question about a window the data
    does not live in. Bug dates still drive the time series' x-axis.
    """
    conds = ["b.snapshot_id = %s"]
    params: list[Any] = [snap]
    if f.severity:
        conds.append("b.severity = %s"); params.append(f.severity)
    if f.status:
        conds.append("b.status = %s"); params.append(f.status)
    if f.issue_type:
        conds.append("b.issue_type = %s"); params.append(f.issue_type)
    return " AND ".join(conds), params


def _case_where(f: QaFilters, snap: str) -> tuple[str, list]:
    conds = ["t.snapshot_id = %s"]
    params: list[Any] = [snap]
    if f.module:
        conds.append("COALESCE(t.module, t.section) = %s"); params.append(f.module)
    return " AND ".join(conds), params


def _matrix_where(f: QaFilters, snap: str) -> tuple[str, list]:
    conds = ["m.snapshot_id = %s"]
    params: list[Any] = [snap]
    if f.dimension:
        conds.append("m.dimension = %s"); params.append(f.dimension)
    return " AND ".join(conds), params


# ══════════════════════════════════════════════════════════════════════════
#  SCALARS — bug KPIs
# ══════════════════════════════════════════════════════════════════════════

def _bug_scalar(cur, f: QaFilters, expr: str, fmt: str = "number") -> dict:
    """A bug KPI for this snapshot, compared to the same KPI on the previous one.

    Deliberately NOT a previous-period comparison. A workbook states the whole
    bug list as of one moment, so a bug whose `created` date the source never
    recorded belongs to no period and would otherwise be counted in both halves
    of the delta — which is exactly what made "61 bugs, up from 1" appear.
    Comparing snapshot to snapshot asks the question a QA lead actually has:
    what did this build change.
    """
    snap = _snapshot_id(cur, f)
    if snap is None:
        return {**EMPTY_SCALAR, "format": fmt}

    def run(sid: str):
        where, params = _bug_where(f, sid)
        cur.execute(f"SELECT {expr} AS value FROM qa_bugs b WHERE {where}", params)
        row = cur.fetchone()
        return row["value"] if row and row["value"] is not None else 0

    prev_id = _previous_snapshot_id(cur, snap)
    current = run(snap)
    return {
        "kind": "scalar",
        "value": float(current) if fmt != "number" else current,
        # No prior snapshot means nothing to compare to, which the UI renders
        # as an absent delta rather than a misleading change from zero.
        "previous": run(prev_id) if prev_id else None,
        "format": fmt,
    }


@register_metric("qa.bugs_total", kind="scalar", filter_model=QaFilters, cache_ttl=10)
def qa_bugs_total(cur: RealDictCursor, f: QaFilters) -> dict:
    return _bug_scalar(cur, f, "COUNT(*)::bigint")


@register_metric("qa.bugs_open", kind="scalar", filter_model=QaFilters, cache_ttl=10)
def qa_bugs_open(cur: RealDictCursor, f: QaFilters) -> dict:
    return _bug_scalar(cur, f, "COUNT(*) FILTER (WHERE b.is_open)::bigint")


@register_metric("qa.open_blockers", kind="scalar", filter_model=QaFilters, cache_ttl=10)
def qa_open_blockers(cur: RealDictCursor, f: QaFilters) -> dict:
    """Open Blocker- or Critical-severity bugs — the release gate."""
    return _bug_scalar(
        cur, f, "COUNT(*) FILTER (WHERE b.is_open AND b.severity_rank >= 4)::bigint"
    )


@register_metric("qa.open_major_plus", kind="scalar", filter_model=QaFilters, cache_ttl=10)
def qa_open_major_plus(cur: RealDictCursor, f: QaFilters) -> dict:
    return _bug_scalar(
        cur, f, "COUNT(*) FILTER (WHERE b.is_open AND b.severity_rank >= 3)::bigint"
    )


# ══════════════════════════════════════════════════════════════════════════
#  SCALARS — snapshot state, compared to the previous snapshot
# ══════════════════════════════════════════════════════════════════════════

def _snapshot_scalar(cur, f: QaFilters, sql: str, fmt: str = "number") -> dict:
    """Run `sql` (one %s for the snapshot id) on this snapshot and the one before."""
    snap = _snapshot_id(cur, f)
    if snap is None:
        return {**EMPTY_SCALAR, "format": fmt}

    def run(sid: str):
        cur.execute(sql, [sid])
        row = cur.fetchone()
        return float(row["value"]) if row and row["value"] is not None else 0.0

    prev_id = _previous_snapshot_id(cur, snap)
    return {
        "kind": "scalar",
        "value": run(snap),
        # No prior snapshot is genuinely "nothing to compare to", which the UI
        # renders as an absent delta rather than a misleading 0% change.
        "previous": run(prev_id) if prev_id else None,
        "format": fmt,
    }


@register_metric("qa.execution_rate", kind="scalar", filter_model=QaFilters, cache_ttl=10)
def qa_execution_rate(cur: RealDictCursor, f: QaFilters) -> dict:
    """Percent of planned test cases that have any recorded result. 0-100."""
    return _snapshot_scalar(cur, f, """
        SELECT CASE WHEN COUNT(*) = 0 THEN 0
                    ELSE ROUND(100.0 * COUNT(*) FILTER (WHERE was_executed) / COUNT(*), 1)
               END AS value
        FROM qa_test_cases WHERE snapshot_id = %s
    """, fmt="percent_whole")


@register_metric("qa.pass_rate", kind="scalar", filter_model=QaFilters, cache_ttl=10)
def qa_pass_rate(cur: RealDictCursor, f: QaFilters) -> dict:
    """Pass rate over EXECUTED cases only — never-run cases are not failures."""
    return _snapshot_scalar(cur, f, """
        SELECT CASE WHEN COUNT(*) FILTER (WHERE was_executed) = 0 THEN 0
                    ELSE ROUND(100.0 * COUNT(*) FILTER (WHERE status = 'Pass')
                               / COUNT(*) FILTER (WHERE was_executed), 1)
               END AS value
        FROM qa_test_cases WHERE snapshot_id = %s
    """, fmt="percent_whole")


@register_metric("qa.never_run", kind="scalar", filter_model=QaFilters, cache_ttl=10)
def qa_never_run(cur: RealDictCursor, f: QaFilters) -> dict:
    return _snapshot_scalar(cur, f, """
        SELECT COUNT(*) FILTER (WHERE NOT was_executed)::bigint AS value
        FROM qa_test_cases WHERE snapshot_id = %s
    """)


@register_metric("qa.localization_pass_rate", kind="scalar",
                 filter_model=QaFilters, cache_ttl=10)
def qa_localization_pass_rate(cur: RealDictCursor, f: QaFilters) -> dict:
    """Percent of checked localization strings passing outright. 0-100."""
    return _snapshot_scalar(cur, f, """
        SELECT CASE WHEN COUNT(*) = 0 THEN 0
                    ELSE ROUND(100.0 * COUNT(*) FILTER (WHERE status = 'Pass') / COUNT(*), 1)
               END AS value
        FROM qa_matrix_results WHERE snapshot_id = %s
    """, fmt="percent_whole")


@register_metric("qa.confidence_score", kind="scalar", filter_model=QaFilters, cache_ttl=10)
def qa_confidence_score(cur: RealDictCursor, f: QaFilters) -> dict:
    """How much of the source the agent could confidently map to a known
    field — the same column-resolution ratio surfaced in the ingest
    receipt and the report's `stats.confidence`, kept in one place so all
    three never disagree. Independent of whether analysis has been run:
    ingest alone decides it, so this is meaningful the moment a workbook
    lands, before anyone clicks Run analysis.
    """
    return _snapshot_scalar(cur, f, """
        SELECT CASE WHEN COUNT(*) = 0 THEN 0
                    ELSE ROUND(100.0 * COUNT(*) FILTER (WHERE col->>'field' IS NOT NULL)
                               / COUNT(*), 1)
               END AS value
        FROM qa_snapshots s,
             jsonb_array_elements(s.sheets_json) AS sheet,
             jsonb_array_elements(sheet->'columns') AS col
        WHERE s.id = %s
    """, fmt="percent_whole")


@register_metric("qa.module_coverage", kind="scalar", filter_model=QaFilters, cache_ttl=10)
def qa_module_coverage(cur: RealDictCursor, f: QaFilters) -> dict:
    """Percent of modules that have at least one EXECUTED case, of modules
    that have any case at all. Distinct from execution rate: a suite can be
    80% executed while three whole modules sit at zero runs, because the
    other modules absorbed all the repeats.
    """
    return _snapshot_scalar(cur, f, """
        SELECT CASE WHEN COUNT(*) = 0 THEN 0
                    ELSE ROUND(100.0 * COUNT(*) FILTER (WHERE executed_ct > 0) / COUNT(*), 1)
               END AS value
        FROM (
            SELECT COALESCE(module, section, 'Unassigned') AS m,
                   COUNT(*) FILTER (WHERE was_executed) AS executed_ct
            FROM qa_test_cases WHERE snapshot_id = %s
            GROUP BY 1
        ) x
    """, fmt="percent_whole")


@register_metric("qa.critical_findings", kind="scalar", filter_model=QaFilters, cache_ttl=10)
def qa_critical_findings(cur: RealDictCursor, f: QaFilters) -> dict:
    """Critical findings in the agent's latest report for this snapshot."""
    return _snapshot_scalar(cur, f, """
        SELECT COALESCE((payload -> 'counts' ->> 'critical')::int, 0) AS value
        FROM qa_reports WHERE snapshot_id = %s
        ORDER BY generated_at DESC LIMIT 1
    """)


# ══════════════════════════════════════════════════════════════════════════
#  SERIES
# ══════════════════════════════════════════════════════════════════════════

@register_metric("qa.bugs_over_time", kind="series", filter_model=QaFilters, cache_ttl=30)
def qa_bugs_over_time(cur: RealDictCursor, f: QaFilters) -> dict:
    """Bugs reported over time, split into open and closed.

    Two series rather than one: a rising total means nothing on its own, while
    a rising *open* line against a flat closed line is the shape of a backlog
    outrunning the fix rate.
    """
    snap = _snapshot_id(cur, f)
    if snap is None:
        return {"kind": "series", "series": [], "format": "number"}

    # Grain comes from the data's own span, not the filter range. The range no
    # longer bounds these rows, so using it would bucket a six-month workbook
    # by hour because the user happened to have "24h" selected.
    grain = f.grain
    if not grain:
        cur.execute(
            "SELECT MIN(created) AS lo, MAX(created) AS hi FROM qa_bugs"
            " WHERE snapshot_id = %s AND created IS NOT NULL",
            [snap],
        )
        span = cur.fetchone()
        grain = (
            auto_grain(datetime.combine(span["lo"], datetime.min.time()),
                       datetime.combine(span["hi"], datetime.min.time()))
            if span and span["lo"] and span["hi"] else "day"
        )

    where, params = _bug_where(f, snap)
    cur.execute(f"""
        SELECT date_trunc(%s, b.created) AS t,
               COUNT(*) FILTER (WHERE b.is_open)::bigint     AS open_bugs,
               COUNT(*) FILTER (WHERE NOT b.is_open)::bigint AS closed_bugs
        FROM qa_bugs b
        WHERE {where} AND b.created IS NOT NULL
        GROUP BY 1 ORDER BY 1
    """, [grain, *params])
    rows = cur.fetchall()

    return {
        "kind": "series",
        "series": [
            {"name": "open",
             "points": [{"t": r["t"].isoformat(), "v": r["open_bugs"]} for r in rows]},
            {"name": "closed",
             "points": [{"t": r["t"].isoformat(), "v": r["closed_bugs"]} for r in rows]},
        ],
        "format": "number",
    }


# ══════════════════════════════════════════════════════════════════════════
#  GROUPS
# ══════════════════════════════════════════════════════════════════════════

def _empty_group() -> dict:
    return {"kind": "group", "groups": [], "format": "number"}


@register_metric("qa.by_severity", kind="group", filter_model=QaFilters, cache_ttl=30)
def qa_by_severity(cur: RealDictCursor, f: QaFilters) -> dict:
    snap = _snapshot_id(cur, f)
    if snap is None:
        return _empty_group()
    where, params = _bug_where(f, snap)
    # Ordered by rank, not by count — severity is an ordered scale, and sorting
    # it by frequency throws away the one property that makes it meaningful.
    cur.execute(f"""
        SELECT b.severity AS key, COUNT(*)::bigint AS value
        FROM qa_bugs b WHERE {where}
        GROUP BY b.severity ORDER BY MAX(b.severity_rank) DESC
    """, params)
    return {"kind": "group", "groups": [dict(r) for r in cur.fetchall()],
            "format": "number"}


@register_metric("qa.by_status", kind="group", filter_model=QaFilters, cache_ttl=30)
def qa_by_status(cur: RealDictCursor, f: QaFilters) -> dict:
    snap = _snapshot_id(cur, f)
    if snap is None:
        return _empty_group()
    where, params = _bug_where(f, snap)
    cur.execute(f"""
        SELECT b.status AS key, COUNT(*)::bigint AS value
        FROM qa_bugs b WHERE {where}
        GROUP BY b.status ORDER BY value DESC
    """, params)
    return {"kind": "group", "groups": [dict(r) for r in cur.fetchall()],
            "format": "number"}


@register_metric("qa.by_issue_type", kind="group", filter_model=QaFilters, cache_ttl=30)
def qa_by_issue_type(cur: RealDictCursor, f: QaFilters) -> dict:
    snap = _snapshot_id(cur, f)
    if snap is None:
        return _empty_group()
    where, params = _bug_where(f, snap)
    cur.execute(f"""
        SELECT COALESCE(b.issue_type, 'Unclassified') AS key, COUNT(*)::bigint AS value
        FROM qa_bugs b WHERE {where}
        GROUP BY 1 ORDER BY value DESC LIMIT 12
    """, params)
    return {"kind": "group", "groups": [dict(r) for r in cur.fetchall()],
            "format": "number"}


@register_metric("qa.test_status_mix", kind="group", filter_model=QaFilters, cache_ttl=30)
def qa_test_status_mix(cur: RealDictCursor, f: QaFilters) -> dict:
    snap = _snapshot_id(cur, f)
    if snap is None:
        return _empty_group()
    where, params = _case_where(f, snap)
    cur.execute(f"""
        SELECT t.status AS key, COUNT(*)::bigint AS value
        FROM qa_test_cases t WHERE {where}
        GROUP BY t.status
        ORDER BY array_position(
            ARRAY['Pass','Fail','Blocked','In Progress','Not Run','Unknown']::text[],
            t.status::text)
    """, params)
    return {"kind": "group", "groups": [dict(r) for r in cur.fetchall()],
            "format": "number"}


@register_metric("qa.localization_by_dimension", kind="group",
                 filter_model=QaFilters, cache_ttl=30)
def qa_localization_by_dimension(cur: RealDictCursor, f: QaFilters) -> dict:
    """Non-passing strings per locale — the bar that ranks translation debt."""
    snap = _snapshot_id(cur, f)
    if snap is None:
        return _empty_group()
    where, params = _matrix_where(f, snap)
    cur.execute(f"""
        SELECT m.dimension AS key,
               COUNT(*) FILTER (WHERE m.status <> 'Pass')::bigint AS value
        FROM qa_matrix_results m WHERE {where}
        GROUP BY m.dimension ORDER BY value DESC
    """, params)
    return {"kind": "group", "groups": [dict(r) for r in cur.fetchall()],
            "format": "number"}


# ══════════════════════════════════════════════════════════════════════════
#  STATUS MATRIX — localization grid, coloured by outcome
# ══════════════════════════════════════════════════════════════════════════

@register_metric("qa.localization_matrix", kind="status_matrix",
                 filter_model=QaFilters, cache_ttl=30)
def qa_localization_matrix(cur: RealDictCursor, f: QaFilters) -> dict:
    """Item x locale grid, each cell carrying its own status.

    Rows are limited to items that are not uniformly passing. A 200-row grid of
    green tells the reader nothing they could not get from the pass rate; the
    rows worth pixels are the ones with a problem somewhere in them.
    """
    snap = _snapshot_id(cur, f)
    if snap is None:
        return {"kind": "status_matrix", "columns": [], "rows": [],
                "statuses": [], "format": "number"}

    where, params = _matrix_where(f, snap)

    cur.execute(f"""
        SELECT DISTINCT m.dimension FROM qa_matrix_results m
        WHERE {where} ORDER BY m.dimension
    """, params)
    columns = [r["dimension"] for r in cur.fetchall()]

    # The "is this row interesting" subquery runs under the SAME filters as the
    # outer query. Filtered to one locale, the rows worth showing are the ones
    # failing in THAT locale — using a snapshot-wide test instead would fill a
    # single-locale view with rows that are entirely green in it.
    cur.execute(f"""
        SELECT m.item, MIN(m.section) AS section, m.dimension, m.status,
               MAX(m.comment)         AS comment
        FROM qa_matrix_results m
        WHERE {where} AND m.item IS NOT NULL
          AND m.item IN (
              SELECT m2.item FROM qa_matrix_results m2
              WHERE {where.replace("m.", "m2.")}
                AND m2.status <> 'Pass' AND m2.item IS NOT NULL
          )
        GROUP BY m.item, m.dimension, m.status
        ORDER BY m.item
    """, [*params, *params])

    by_item: dict[str, dict] = {}
    for r in cur.fetchall():
        row = by_item.setdefault(r["item"], {
            "item": r["item"], "section": r["section"], "cells": {},
            "not_passing": 0, "comment": r["comment"],
        })
        row["cells"][r["dimension"]] = r["status"]
        if r["status"] != "Pass":
            row["not_passing"] += 1

    rows = sorted(by_item.values(), key=lambda r: -r["not_passing"])[:60]
    return {
        "kind": "status_matrix",
        "columns": columns,
        "rows": rows,
        "statuses": ["Pass", "Some Issue", "Fail", "Blocked", "In Progress",
                     "Not Run", "Unknown"],
        "format": "number",
    }


# ══════════════════════════════════════════════════════════════════════════
#  AGENT OUTPUT — narrative + findings, read from the persisted report
# ══════════════════════════════════════════════════════════════════════════

def _report_payload(cur, f: QaFilters) -> Optional[dict]:
    snap = _snapshot_id(cur, f)
    if snap is None:
        return None
    cur.execute(
        "SELECT payload, generated_at, partial, model_enabled, model_name"
        " FROM qa_reports WHERE snapshot_id = %s"
        " ORDER BY generated_at DESC LIMIT 1",
        [snap],
    )
    row = cur.fetchone()
    if row is None:
        return None
    return {
        "payload": dict(row["payload"]),
        "generated_at": row["generated_at"].isoformat(),
        "partial": row["partial"],
        "model_enabled": row["model_enabled"],
        "model_name": row["model_name"],
    }


@register_metric("qa.executive_summary", kind="narrative",
                 filter_model=QaFilters, cache_ttl=10)
def qa_executive_summary(cur: RealDictCursor, f: QaFilters) -> dict:
    """The agent's narrated summary. Empty until an analysis has been run."""
    found = _report_payload(cur, f)
    if found is None:
        return {"kind": "narrative", "available": False, "verdict": "unknown",
                "headline": "", "narrative": "", "sections": [], "risks": [],
                "recommendation": "", "generated_at": None,
                "model_enabled": False, "model_name": None, "partial": False}

    payload = found["payload"]
    summary = payload.get("executive_summary") or {}
    return {
        "kind": "narrative",
        "available": True,
        "verdict": payload.get("verdict", "unknown"),
        "headline": summary.get("headline", ""),
        "narrative": summary.get("narrative", ""),
        "sections": summary.get("sections", []),
        "risks": summary.get("risks", []),
        "recommendation": summary.get("recommendation", ""),
        "generated_at": found["generated_at"],
        "model_enabled": found["model_enabled"],
        "model_name": found["model_name"],
        "partial": found["partial"],
    }


@register_metric("qa.findings", kind="findings", filter_model=QaFilters, cache_ttl=10)
def qa_findings(cur: RealDictCursor, f: QaFilters) -> dict:
    """Ranked findings from the agent's latest report for this snapshot."""
    found = _report_payload(cur, f)
    if found is None:
        return {"kind": "findings", "available": False, "findings": [],
                "counts": {"critical": 0, "warning": 0, "info": 0},
                "generated_at": None}

    payload = found["payload"]
    return {
        "kind": "findings",
        "available": True,
        "findings": payload.get("findings", []),
        "counts": payload.get("counts", {"critical": 0, "warning": 0, "info": 0}),
        "generated_at": found["generated_at"],
    }


# ══════════════════════════════════════════════════════════════════════════
#  TABLES
# ══════════════════════════════════════════════════════════════════════════

def _empty_table(columns: list[str]) -> dict:
    return {"kind": "table", "columns": columns, "rows": [], "total": 0,
            "format": "number"}


@register_metric("qa.open_blockers_table", kind="table",
                 filter_model=QaFilters, cache_ttl=15)
def qa_open_blockers_table(cur: RealDictCursor, f: QaFilters) -> dict:
    cols = ["bug_key", "severity", "status", "issue_type", "summary", "build"]
    snap = _snapshot_id(cur, f)
    if snap is None:
        return _empty_table(cols)
    where, params = _bug_where(f, snap)
    cur.execute(f"""
        SELECT b.bug_key, b.severity, b.status, b.issue_type, b.summary, b.build
        FROM qa_bugs b
        WHERE {where} AND b.is_open AND b.severity_rank >= 3
        ORDER BY b.severity_rank DESC, b.bug_key
        LIMIT 50
    """, params)
    rows = [dict(r) for r in cur.fetchall()]
    return {"kind": "table", "columns": cols, "rows": rows, "total": len(rows),
            "format": "number"}


@register_metric("qa.module_breakdown", kind="table",
                 filter_model=QaFilters, cache_ttl=30)
def qa_module_breakdown(cur: RealDictCursor, f: QaFilters) -> dict:
    cols = ["module", "cases", "executed", "passed", "failed", "never_run", "exec_rate"]
    snap = _snapshot_id(cur, f)
    if snap is None:
        return _empty_table(cols)
    where, params = _case_where(f, snap)
    cur.execute(f"""
        SELECT COALESCE(t.module, t.section, 'Unassigned')     AS module,
               COUNT(*)::bigint                                 AS cases,
               COUNT(*) FILTER (WHERE t.was_executed)::bigint   AS executed,
               COUNT(*) FILTER (WHERE t.status = 'Pass')::bigint AS passed,
               COUNT(*) FILTER (WHERE t.status = 'Fail')::bigint AS failed,
               COUNT(*) FILTER (WHERE NOT t.was_executed)::bigint AS never_run,
               ROUND(100.0 * COUNT(*) FILTER (WHERE t.was_executed)
                     / NULLIF(COUNT(*), 0), 1)::float            AS exec_rate
        FROM qa_test_cases t WHERE {where}
        GROUP BY 1 ORDER BY cases DESC LIMIT 100
    """, params)
    rows = [dict(r) for r in cur.fetchall()]
    return {"kind": "table", "columns": cols, "rows": rows, "total": len(rows),
            "format": "number"}


@register_metric("qa.systemic_items", kind="table", filter_model=QaFilters, cache_ttl=30)
def qa_systemic_items(cur: RealDictCursor, f: QaFilters) -> dict:
    """Items failing across most locales — one defect seen many times."""
    cols = ["item", "section", "dimensions", "not_passing", "share"]
    snap = _snapshot_id(cur, f)
    if snap is None:
        return _empty_table(cols)
    where, params = _matrix_where(f, snap)
    cur.execute(f"""
        SELECT m.item,
               MIN(m.section)                                       AS section,
               COUNT(DISTINCT m.dimension)::bigint                   AS dimensions,
               COUNT(*) FILTER (WHERE m.status <> 'Pass')::bigint    AS not_passing,
               ROUND(100.0 * COUNT(*) FILTER (WHERE m.status <> 'Pass')
                     / NULLIF(COUNT(DISTINCT m.dimension), 0), 0)::float AS share
        FROM qa_matrix_results m
        WHERE {where} AND m.item IS NOT NULL
        GROUP BY m.item
        HAVING COUNT(DISTINCT m.dimension) >= 3
           AND COUNT(*) FILTER (WHERE m.status <> 'Pass') > 0
        ORDER BY share DESC, not_passing DESC
        LIMIT 25
    """, params)
    rows = [dict(r) for r in cur.fetchall()]
    return {"kind": "table", "columns": cols, "rows": rows, "total": len(rows),
            "format": "number"}


class BugExplorerFilters(QaFilters):
    page: int = 1
    page_size: int = 20
    sort: str = "severity"
    sort_dir: str = "desc"


# Allow-list, because the sort column is interpolated into the statement.
_BUG_SORT = {
    "severity": "b.severity_rank",
    "created": "b.created",
    "bug_key": "b.bug_key",
    "status": "b.status",
}
_DIRS = {"asc", "desc"}


@register_metric("qa.bug_explorer", kind="table",
                 filter_model=BugExplorerFilters, cache_ttl=10)
def qa_bug_explorer(cur: RealDictCursor, f: BugExplorerFilters) -> dict:
    cols = ["bug_key", "created", "severity", "status", "issue_type", "summary",
            "build", "resolution"]
    snap = _snapshot_id(cur, f)
    if snap is None:
        return _empty_table(cols)

    sort_col = _BUG_SORT.get(f.sort, "b.severity_rank")
    sort_dir = f.sort_dir if f.sort_dir in _DIRS else "desc"
    offset = max(0, (f.page - 1) * f.page_size)

    where, params = _bug_where(f, snap)
    cur.execute(f"SELECT COUNT(*)::bigint AS total FROM qa_bugs b WHERE {where}", params)
    total = cur.fetchone()["total"]

    cur.execute(f"""
        SELECT b.bug_key, b.created, b.severity, b.status, b.issue_type,
               b.summary, b.build, b.resolution
        FROM qa_bugs b WHERE {where}
        ORDER BY {sort_col} {sort_dir} NULLS LAST, b.bug_key
        LIMIT %s OFFSET %s
    """, [*params, f.page_size, offset])

    rows = [dict(r) for r in cur.fetchall()]
    for r in rows:
        if r.get("created"):
            r["created"] = r["created"].isoformat()
    return {"kind": "table", "columns": cols, "rows": rows, "total": total,
            "format": "number"}

"""Deterministic statistics for one snapshot.

Everything the report says about numbers originates here, in SQL, before any
model is involved. The narrator receives this payload and is told it may not
introduce a figure that is not in it — which is only enforceable because this
module is the single place figures come from.

Read-only throughout: callers pass the dashboards package's replica cursor.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

# Statuses that still represent outstanding work. Mirrors OPEN_BUG_STATUSES in
# ingest.models — kept in SQL form here because these queries run in Postgres.
OPEN_STATUSES = ("Open", "In Progress", "QA Ready")


#: An explicit reporting window, as (start, end) dates — end exclusive.
#: None means "the whole snapshot", which is the default and the common case.
Window = Optional[tuple[Any, Any]]


@dataclass(frozen=True)
class ReportScope:
    """Everything narrowing a report, in one place.

    The date window and the dimension filters (severity, status, module,
    reporter, …) used to be two unrelated mechanisms — a window threaded
    through every detector, and separate WHERE clauses the live dashboard
    built for itself that the agent's own analysis never saw. That split
    meant picking "Blocker" in the filter bar changed the tiles on screen but
    not the executive summary describing them. One scope, read by both, is
    what makes the summary and the dashboard describe the same data.

    `window` narrows bugs by `created` date, the only field with a real
    per-row date; `reporter` matches BOTH bugs and test cases (the same
    canonical field on each), since "show me everything touching Priya" is
    one question spanning both entities, not two separate ones.
    """
    window: Window = None
    severity: Optional[str] = None
    status: Optional[str] = None
    issue_type: Optional[str] = None
    module: Optional[str] = None
    test_status: Optional[str] = None
    test_priority: Optional[str] = None
    reporter: Optional[str] = None

    @property
    def is_scoped(self) -> bool:
        return any((
            self.window, self.severity, self.status, self.issue_type,
            self.module, self.test_status, self.test_priority, self.reporter,
        ))


def bug_scope(snapshot_id: str, scope: ReportScope | Window = None) -> tuple[str, list]:
    """WHERE fragment scoping bugs to a snapshot, a date window, and filters.

    Bugs are the ONLY records with a real per-row date, so the window is the
    only part of this that can narrow test cases or localization too — those
    are point-in-time state, the sheet says a case passed, not when, and are
    always read whole regardless of window. Callers report that asymmetry
    rather than hiding it, or a reader sees "45% executed" beside a one-week
    range and concludes the week only covered 45%.

    When a window IS set, undated bugs drop out: a bug whose date the source
    never recorded cannot be claimed to fall inside a window. With no window
    they are included, because then there is no claim being made.

    Accepts a bare `Window` tuple too, for the handful of callers that only
    ever cared about the date — wrapped into a scope with nothing else set.
    """
    scope = scope if isinstance(scope, ReportScope) else ReportScope(window=scope)
    conds = ["snapshot_id = %s"]
    params: list[Any] = [snapshot_id]
    if scope.window is not None:
        conds.append("created IS NOT NULL AND created >= %s AND created < %s")
        params += [scope.window[0], scope.window[1]]
    if scope.severity:
        conds.append("severity = %s"); params.append(scope.severity)
    if scope.status:
        conds.append("status = %s"); params.append(scope.status)
    if scope.issue_type:
        conds.append("issue_type = %s"); params.append(scope.issue_type)
    if scope.reporter:
        conds.append("reporter = %s"); params.append(scope.reporter)
    return " AND ".join(conds), params


def case_scope(snapshot_id: str, scope: ReportScope | Window = None) -> tuple[str, list]:
    """WHERE fragment scoping test cases to a snapshot and filters.

    No window here even when one is set on the scope — test cases carry no
    per-row date (see `bug_scope`). module/status/priority/reporter all apply.
    """
    scope = scope if isinstance(scope, ReportScope) else ReportScope()
    conds = ["snapshot_id = %s"]
    params: list[Any] = [snapshot_id]
    if scope.module:
        # Matches the 'Unassigned' fallback the dashboard's own module
        # dimension uses, so a value chosen from that dropdown actually
        # narrows the same rows the tile counted it from.
        conds.append("COALESCE(module, section, 'Unassigned') = %s"); params.append(scope.module)
    if scope.test_status:
        conds.append("status = %s"); params.append(scope.test_status)
    if scope.test_priority:
        conds.append("priority = %s"); params.append(scope.test_priority)
    if scope.reporter:
        conds.append("reporter = %s"); params.append(scope.reporter)
    return " AND ".join(conds), params


def _rows(cur, query: str, params: list | tuple = ()) -> list[dict]:
    cur.execute(query, params)
    return [dict(r) for r in cur.fetchall()]


def _one(cur, query: str, params: list | tuple = ()) -> dict:
    cur.execute(query, params)
    row = cur.fetchone()
    return dict(row) if row else {}


# ══════════════════════════════════════════════════════════════════════════
#  BUGS
# ══════════════════════════════════════════════════════════════════════════

def bug_stats(cur, snapshot_id: str, scope: ReportScope | Window = None) -> dict[str, Any]:
    where, params = bug_scope(snapshot_id, scope)
    totals = _one(cur, f"""
        SELECT COUNT(*)::int                                        AS total,
               COUNT(*) FILTER (WHERE is_open)::int                 AS open,
               -- Blocker AND Critical, matching the `qa.open_blockers` metric
               -- and the open_blockers detector. One definition of "release
               -- gating", or the verdict disagrees with the KPI beside it.
               COUNT(*) FILTER (WHERE is_open AND severity_rank >= 4)::int
                                                                    AS open_blockers,
               COUNT(*) FILTER (WHERE is_open AND severity_rank >= 3)::int
                                                                    AS open_major_plus,
               COUNT(DISTINCT build)::int                           AS builds,
               MIN(created)                                         AS first_reported,
               MAX(created)                                         AS last_reported
        FROM qa_bugs WHERE {where}
    """, params)

    by_severity = _rows(cur, f"""
        SELECT severity AS key, COUNT(*)::int AS value
        FROM qa_bugs WHERE {where}
        GROUP BY severity ORDER BY MAX(severity_rank) DESC
    """, params)

    by_status = _rows(cur, f"""
        SELECT status AS key, COUNT(*)::int AS value
        FROM qa_bugs WHERE {where}
        GROUP BY status ORDER BY value DESC
    """, params)

    by_type = _rows(cur, f"""
        SELECT COALESCE(issue_type, 'Unclassified') AS key, COUNT(*)::int AS value
        FROM qa_bugs WHERE {where}
        GROUP BY 1 ORDER BY value DESC
    """, params)

    # Only bugs with a recorded build — an unbuilt/blank field is not "build
    # zero", it is a fact the source never gave, and it would otherwise
    # dominate every multi-build source as a fake plurality bucket.
    by_build = _rows(cur, f"""
        SELECT build AS key, COUNT(*)::int AS value
        FROM qa_bugs WHERE {where} AND build IS NOT NULL
        GROUP BY build ORDER BY value DESC LIMIT 12
    """, params)

    # Severity x status crosstab — where "an open Major" actually lives.
    crosstab = _rows(cur, f"""
        SELECT severity, status, COUNT(*)::int AS n
        FROM qa_bugs WHERE {where}
        GROUP BY severity, status ORDER BY severity, status
    """, params)

    for k in ("first_reported", "last_reported"):
        if totals.get(k):
            totals[k] = totals[k].isoformat()

    return {
        **totals,
        "by_severity": {r["key"]: r["value"] for r in by_severity},
        "by_status": {r["key"]: r["value"] for r in by_status},
        "by_issue_type": {r["key"]: r["value"] for r in by_type},
        "by_build": {r["key"]: r["value"] for r in by_build},
        "severity_status_crosstab": crosstab,
    }


# ══════════════════════════════════════════════════════════════════════════
#  TEST CASES
# ══════════════════════════════════════════════════════════════════════════

def test_case_stats(cur, snapshot_id: str, scope: ReportScope | Window = None) -> dict[str, Any]:
    where, params = case_scope(snapshot_id, scope)
    totals = _one(cur, f"""
        SELECT COUNT(*)::int                                    AS total,
               COUNT(*) FILTER (WHERE was_executed)::int         AS executed,
               COUNT(*) FILTER (WHERE status = 'Pass')::int      AS passed,
               COUNT(*) FILTER (WHERE status = 'Fail')::int      AS failed,
               COUNT(*) FILTER (WHERE status = 'Blocked')::int   AS blocked,
               COUNT(*) FILTER (WHERE status = 'In Progress')::int AS in_progress,
               COUNT(*) FILTER (WHERE NOT was_executed)::int     AS never_run
        FROM qa_test_cases WHERE {where}
    """, params)

    total = totals.get("total") or 0
    executed = totals.get("executed") or 0
    passed = totals.get("passed") or 0

    by_status = _rows(cur, f"""
        SELECT status AS key, COUNT(*)::int AS value
        FROM qa_test_cases WHERE {where}
        GROUP BY status ORDER BY value DESC
    """, params)

    by_module = _rows(cur, f"""
        SELECT COALESCE(module, section, 'Unassigned') AS module,
               COUNT(*)::int                                   AS cases,
               COUNT(*) FILTER (WHERE was_executed)::int        AS executed,
               COUNT(*) FILTER (WHERE status = 'Fail')::int     AS failed
        FROM qa_test_cases WHERE {where}
        GROUP BY 1 ORDER BY cases DESC
    """, params)

    # Module coverage: what share of the modules that HAVE test cases have
    # been touched at all. Distinct from execution_rate — a suite can be 80%
    # executed while three whole modules have zero runs, because the other
    # modules were run repeatedly and these were never picked up. Computed
    # from by_module rather than a second query since the grouping is already
    # in hand.
    modules_total = len(by_module)
    modules_covered = sum(1 for m in by_module if m["executed"] > 0)

    return {
        **totals,
        # Rates as fractions; the UI decides how to render them. Guarded so an
        # empty snapshot reports 0.0 rather than dividing by zero.
        "execution_rate": round(executed / total, 4) if total else 0.0,
        "pass_rate_of_executed": round(passed / executed, 4) if executed else 0.0,
        "module_coverage": round(modules_covered / modules_total, 4) if modules_total else 0.0,
        "modules_total": modules_total,
        "modules_covered": modules_covered,
        "by_status": {r["key"]: r["value"] for r in by_status},
        "by_module": by_module,
    }


# ══════════════════════════════════════════════════════════════════════════
#  LOCALIZATION / MATRIX
# ══════════════════════════════════════════════════════════════════════════

def matrix_stats(cur, snapshot_id: str) -> dict[str, Any]:
    totals = _one(cur, """
        SELECT COUNT(*)::int                                       AS cells,
               COUNT(DISTINCT dimension)::int                      AS dimensions,
               COUNT(DISTINCT item)::int                           AS items,
               COUNT(*) FILTER (WHERE status = 'Pass')::int        AS passed,
               COUNT(*) FILTER (WHERE status = 'Fail')::int        AS failed,
               COUNT(*) FILTER (WHERE status = 'Some Issue')::int  AS some_issue
        FROM qa_matrix_results WHERE snapshot_id = %s
    """, [snapshot_id])

    cells = totals.get("cells") or 0
    clean = totals.get("passed") or 0

    by_dimension = _rows(cur, """
        SELECT dimension,
               COUNT(*)::int                                      AS cells,
               COUNT(*) FILTER (WHERE status = 'Pass')::int       AS passed,
               COUNT(*) FILTER (WHERE status = 'Fail')::int       AS failed,
               COUNT(*) FILTER (WHERE status = 'Some Issue')::int AS some_issue
        FROM qa_matrix_results WHERE snapshot_id = %s
        GROUP BY dimension
        ORDER BY failed DESC, some_issue DESC
    """, [snapshot_id])

    for d in by_dimension:
        d["pass_rate"] = round(d["passed"] / d["cells"], 4) if d["cells"] else 0.0

    return {
        **totals,
        "pass_rate": round(clean / cells, 4) if cells else 0.0,
        "by_dimension": by_dimension,
    }


# ══════════════════════════════════════════════════════════════════════════
#  INGEST QUALITY
# ══════════════════════════════════════════════════════════════════════════

def ingest_stats(cur, snapshot_id: str) -> dict[str, Any]:
    """How much the agent trusts its own reading of the source.

    A report whose inputs were half-understood should say so. Unresolved
    columns and parse warnings are the honest measure of that, and they belong
    in the payload the narrator sees.
    """
    snap = _one(cur, """
        SELECT source_kind, source_label, fingerprint, ingested_at,
               sheets_json, warnings
        FROM qa_snapshots WHERE id = %s
    """, [snapshot_id])
    if not snap:
        return {}

    sheets = snap.get("sheets_json") or []
    warnings = snap.get("warnings") or []

    resolved = unresolved = 0
    per_sheet = []
    for s in sheets:
        cols = s.get("columns") or []
        got = sum(1 for c in cols if c.get("field"))
        resolved += got
        unresolved += len(cols) - got
        per_sheet.append({
            "name": s.get("name"),
            "role": s.get("role"),
            "shape": s.get("shape"),
            "rows": s.get("row_count", 0),
            "columns_resolved": got,
            "columns_total": len(cols),
        })

    total_cols = resolved + unresolved
    return {
        "source_kind": snap.get("source_kind"),
        "source_label": snap.get("source_label"),
        "fingerprint": snap.get("fingerprint"),
        "ingested_at": snap["ingested_at"].isoformat() if snap.get("ingested_at") else None,
        "sheets": per_sheet,
        "columns_resolved": resolved,
        "columns_unresolved": unresolved,
        "column_resolution_rate": round(resolved / total_cols, 4) if total_cols else 0.0,
        "warning_count": len(warnings),
        "warnings": warnings[:50],
    }


# ══════════════════════════════════════════════════════════════════════════
#  FULL PAYLOAD
# ══════════════════════════════════════════════════════════════════════════

def by_source_file(cur, snapshot_id: str, scope: ReportScope | Window = None) -> list[dict[str, Any]]:
    """Per-file totals — the per-plan view a multi-file snapshot exists for.

    A snapshot spanning a gameplay plan, a map plan and two bug trackers has
    an aggregate execution rate that is true and useless: it averages the plan
    that is finished together with the one nobody has started. This is the cut
    that says which is which.
    """
    scope = scope if isinstance(scope, ReportScope) else ReportScope(window=scope)
    bug_where, bug_params = bug_scope(snapshot_id, scope)
    case_where, case_params = case_scope(snapshot_id, scope)

    bugs = _rows(cur, f"""
        SELECT source_file AS file, COUNT(*)::int AS bugs,
               COUNT(*) FILTER (WHERE is_open)::int                     AS open_bugs,
               COUNT(*) FILTER (WHERE is_open AND severity_rank >= 4)::int
                                                                        AS open_blockers
        FROM qa_bugs WHERE {bug_where} GROUP BY source_file
    """, bug_params)

    cases = _rows(cur, f"""
        SELECT source_file AS file, COUNT(*)::int AS cases,
               COUNT(*) FILTER (WHERE was_executed)::int    AS executed,
               COUNT(*) FILTER (WHERE status = 'Fail')::int AS failed
        FROM qa_test_cases WHERE {case_where} GROUP BY source_file
    """, case_params)

    matrix = _rows(cur, """
        SELECT source_file AS file, COUNT(*)::int AS matrix_cells,
               COUNT(*) FILTER (WHERE status <> 'Pass')::int AS matrix_not_passing
        FROM qa_matrix_results WHERE snapshot_id = %s GROUP BY source_file
    """, [snapshot_id])

    merged: dict[str, dict[str, Any]] = {}
    for group in (bugs, cases, matrix):
        for row in group:
            entry = merged.setdefault(row["file"] or "(unattributed)", {
                "file": row["file"] or "(unattributed)",
                "bugs": 0, "open_bugs": 0, "open_blockers": 0,
                "cases": 0, "executed": 0, "failed": 0,
                "matrix_cells": 0, "matrix_not_passing": 0,
            })
            entry.update({k: v for k, v in row.items() if k != "file"})

    for entry in merged.values():
        entry["execution_rate"] = (
            round(entry["executed"] / entry["cases"], 4) if entry["cases"] else None
        )
    return sorted(merged.values(), key=lambda e: (-e["cases"], -e["bugs"], e["file"]))


def full_stats(cur, snapshot_id: str, scope: ReportScope | Window = None) -> dict[str, Any]:
    """The complete statistics payload — the narrator's only source of numbers."""
    scope = scope if isinstance(scope, ReportScope) else ReportScope(window=scope)
    ingest = ingest_stats(cur, snapshot_id)
    return {
        "snapshot_id": snapshot_id,
        # What the scope did and did not narrow, carried in the payload so the
        # narrator, the dashboard and the PDF all state the same thing.
        "window": {
            "active": scope.window is not None,
            "start": str(scope.window[0]) if scope.window else None,
            "end": str(scope.window[1]) if scope.window else None,
            "applies_to": "bugs only — test cases and localization have no per-row date",
        },
        "filters": {
            "severity": scope.severity, "status": scope.status,
            "issue_type": scope.issue_type, "module": scope.module,
            "test_status": scope.test_status, "test_priority": scope.test_priority,
            "reporter": scope.reporter,
        } if scope.is_scoped else None,
        "ingest": ingest,
        "bugs": bug_stats(cur, snapshot_id, scope),
        "test_cases": test_case_stats(cur, snapshot_id, scope),
        "localization": matrix_stats(cur, snapshot_id),
        "by_source_file": by_source_file(cur, snapshot_id, scope),
        # Re-surfaced from `ingest` under a name a reader recognizes on sight.
        # Deliberately just the column-resolution ratio — blending it with
        # something like "did narration succeed" into one composite index
        # would answer two different questions with one number and make
        # neither traceable back to what actually moved it.
        "confidence": {
            "ingest_confidence": ingest.get("column_resolution_rate", 0.0),
            "columns_resolved": ingest.get("columns_resolved", 0),
            "columns_total": ingest.get("columns_resolved", 0) + ingest.get("columns_unresolved", 0),
            "warning_count": ingest.get("warning_count", 0),
        },
    }

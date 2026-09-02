"""Deterministic statistics for one snapshot.

Everything the report says about numbers originates here, in SQL, before any
model is involved. The narrator receives this payload and is told it may not
introduce a figure that is not in it — which is only enforceable because this
module is the single place figures come from.

Read-only throughout: callers pass the dashboards package's replica cursor.
"""

from __future__ import annotations

from typing import Any

# Statuses that still represent outstanding work. Mirrors OPEN_BUG_STATUSES in
# ingest.models — kept in SQL form here because these queries run in Postgres.
OPEN_STATUSES = ("Open", "In Progress", "QA Ready")


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

def bug_stats(cur, snapshot_id: str) -> dict[str, Any]:
    totals = _one(cur, """
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
        FROM qa_bugs WHERE snapshot_id = %s
    """, [snapshot_id])

    by_severity = _rows(cur, """
        SELECT severity AS key, COUNT(*)::int AS value
        FROM qa_bugs WHERE snapshot_id = %s
        GROUP BY severity ORDER BY MAX(severity_rank) DESC
    """, [snapshot_id])

    by_status = _rows(cur, """
        SELECT status AS key, COUNT(*)::int AS value
        FROM qa_bugs WHERE snapshot_id = %s
        GROUP BY status ORDER BY value DESC
    """, [snapshot_id])

    by_type = _rows(cur, """
        SELECT COALESCE(issue_type, 'Unclassified') AS key, COUNT(*)::int AS value
        FROM qa_bugs WHERE snapshot_id = %s
        GROUP BY 1 ORDER BY value DESC
    """, [snapshot_id])

    # Only bugs with a recorded build — an unbuilt/blank field is not "build
    # zero", it is a fact the source never gave, and it would otherwise
    # dominate every multi-build source as a fake plurality bucket.
    by_build = _rows(cur, """
        SELECT build AS key, COUNT(*)::int AS value
        FROM qa_bugs WHERE snapshot_id = %s AND build IS NOT NULL
        GROUP BY build ORDER BY value DESC LIMIT 12
    """, [snapshot_id])

    # Severity x status crosstab — where "an open Major" actually lives.
    crosstab = _rows(cur, """
        SELECT severity, status, COUNT(*)::int AS n
        FROM qa_bugs WHERE snapshot_id = %s
        GROUP BY severity, status ORDER BY severity, status
    """, [snapshot_id])

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

def test_case_stats(cur, snapshot_id: str) -> dict[str, Any]:
    totals = _one(cur, """
        SELECT COUNT(*)::int                                    AS total,
               COUNT(*) FILTER (WHERE was_executed)::int         AS executed,
               COUNT(*) FILTER (WHERE status = 'Pass')::int      AS passed,
               COUNT(*) FILTER (WHERE status = 'Fail')::int      AS failed,
               COUNT(*) FILTER (WHERE status = 'Blocked')::int   AS blocked,
               COUNT(*) FILTER (WHERE status = 'In Progress')::int AS in_progress,
               COUNT(*) FILTER (WHERE NOT was_executed)::int     AS never_run
        FROM qa_test_cases WHERE snapshot_id = %s
    """, [snapshot_id])

    total = totals.get("total") or 0
    executed = totals.get("executed") or 0
    passed = totals.get("passed") or 0

    by_status = _rows(cur, """
        SELECT status AS key, COUNT(*)::int AS value
        FROM qa_test_cases WHERE snapshot_id = %s
        GROUP BY status ORDER BY value DESC
    """, [snapshot_id])

    by_module = _rows(cur, """
        SELECT COALESCE(module, section, 'Unassigned') AS module,
               COUNT(*)::int                                   AS cases,
               COUNT(*) FILTER (WHERE was_executed)::int        AS executed,
               COUNT(*) FILTER (WHERE status = 'Fail')::int     AS failed
        FROM qa_test_cases WHERE snapshot_id = %s
        GROUP BY 1 ORDER BY cases DESC
    """, [snapshot_id])

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

def full_stats(cur, snapshot_id: str) -> dict[str, Any]:
    """The complete statistics payload — the narrator's only source of numbers."""
    ingest = ingest_stats(cur, snapshot_id)
    return {
        "snapshot_id": snapshot_id,
        "ingest": ingest,
        "bugs": bug_stats(cur, snapshot_id),
        "test_cases": test_case_stats(cur, snapshot_id),
        "localization": matrix_stats(cur, snapshot_id),
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

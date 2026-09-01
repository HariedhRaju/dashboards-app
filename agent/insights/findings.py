"""Ranked findings — the "insights" half of the agent.

A dashboard shows what the numbers are. A finding says which of them somebody
has to act on, and why. Each detector below answers one question a QA lead
would otherwise have to ask the spreadsheet by hand, and every one of them is
pure SQL: a finding is a fact about the data, not a model's impression of it.

Each detector returns zero or more `Finding`s. Silence is a real answer — a
detector that finds nothing means that class of problem is absent, and the
report says so rather than manufacturing something to fill the section.

Ranking is (level, impact) descending, so the list reads worst-first and the
top of it is what belongs in the executive summary.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Callable

# Ordering for the sort. Not merely cosmetic: the narrator is handed the top
# findings by this ranking, so it decides what the summary leads with.
LEVEL_RANK = {"critical": 3, "warning": 2, "info": 1}


@dataclass
class Finding:
    id: str
    kind: str
    level: str                     # 'critical' | 'warning' | 'info'
    title: str
    detail: str
    #: Comparable magnitude used for ranking within a level — a count, or a
    #: rate scaled to a count. Never shown directly.
    impact: float = 0.0
    #: The headline number, with the unit the UI should render.
    value: float | int | None = None
    unit: str = "count"            # 'count' | 'percent' | 'days'
    evidence: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict:
        return asdict(self)


def _rows(cur, query: str, params: list | tuple = ()) -> list[dict]:
    cur.execute(query, params)
    return [dict(r) for r in cur.fetchall()]


# ══════════════════════════════════════════════════════════════════════════
#  DETECTORS — release risk
# ══════════════════════════════════════════════════════════════════════════

def open_blockers(cur, snap: str) -> list[Finding]:
    """Blocker- or Critical-severity bugs that are still open."""
    rows = _rows(cur, """
        SELECT bug_key, severity, status, summary, build
        FROM qa_bugs
        WHERE snapshot_id = %s AND is_open AND severity_rank >= 4
        ORDER BY severity_rank DESC, bug_key
    """, [snap])
    if not rows:
        return []
    return [Finding(
        id="open-blockers",
        kind="release_risk",
        level="critical",
        title=f"{len(rows)} release-blocking bug{'s' if len(rows) != 1 else ''} still open",
        detail=(
            "Blocker and Critical severity issues that have not reached a closed "
            "state. These gate the release regardless of how the rest of the "
            "cycle looks."
        ),
        impact=len(rows) * 100,
        value=len(rows),
        evidence=rows[:10],
    )]


def stalled_fixes(cur, snap: str) -> list[Finding]:
    """Bugs whose own comments record that a fix did not hold.

    A closed-then-failed fix is more expensive than a bug that was never
    fixed: the cycle has already paid for a verification pass that produced a
    false negative, and the status field alone will not show it.
    """
    rows = _rows(cur, """
        SELECT bug_key, severity, status, summary,
               COALESCE(comments, dev_comments) AS note
        FROM qa_bugs
        WHERE snapshot_id = %s
          AND (comments ILIKE '%%fix failed%%'
            OR comments ILIKE '%%not fixed%%'
            OR comments ILIKE '%%reopen%%'
            OR dev_comments ILIKE '%%fix failed%%'
            OR dev_comments ILIKE '%%reopen%%')
        ORDER BY severity_rank DESC
    """, [snap])
    if not rows:
        return []
    return [Finding(
        id="stalled-fixes",
        kind="release_risk",
        level="warning",
        title=f"{len(rows)} bug{'s' if len(rows) != 1 else ''} with a failed or reverted fix",
        detail=(
            "Verification comments on these bugs report that the fix did not "
            "hold. Their status field may still read as resolved, so they will "
            "not appear in an open-bug count."
        ),
        impact=len(rows) * 40,
        value=len(rows),
        evidence=rows[:10],
    )]


def unclosed_major_backlog(cur, snap: str) -> list[Finding]:
    """Open Major-severity work, sized against the whole backlog."""
    row = _rows(cur, """
        SELECT COUNT(*) FILTER (WHERE is_open AND severity = 'Major')::int AS open_major,
               COUNT(*) FILTER (WHERE is_open)::int                        AS open_total,
               COUNT(*)::int                                               AS total
        FROM qa_bugs WHERE snapshot_id = %s
    """, [snap])[0]
    if not row["open_major"]:
        return []
    share = row["open_major"] / row["open_total"] if row["open_total"] else 0
    return [Finding(
        id="open-major-backlog",
        kind="backlog",
        level="warning" if share >= 0.4 else "info",
        title=f"{row['open_major']} open Major bugs ({share:.0%} of the open backlog)",
        detail=(
            "Major-severity defects that remain open. Not individually "
            "release-gating, but they are the population most likely to become "
            "so once a build is exercised more widely."
        ),
        impact=row["open_major"] * 10,
        value=row["open_major"],
        evidence=[row],
    )]


# ══════════════════════════════════════════════════════════════════════════
#  DETECTORS — coverage
# ══════════════════════════════════════════════════════════════════════════

def never_executed(cur, snap: str) -> list[Finding]:
    """Planned test cases that were never run.

    The most under-reported risk in a QA cycle: an unexecuted case contributes
    nothing to a pass rate, so a plan that is 40% run can still show a 100%
    pass rate and read as healthy.
    """
    row = _rows(cur, """
        SELECT COUNT(*)::int                                  AS total,
               COUNT(*) FILTER (WHERE NOT was_executed)::int   AS never_run
        FROM qa_test_cases WHERE snapshot_id = %s
    """, [snap])[0]
    if not row["total"] or not row["never_run"]:
        return []

    share = row["never_run"] / row["total"]
    modules = _rows(cur, """
        SELECT COALESCE(module, section, 'Unassigned') AS module,
               COUNT(*)::int AS never_run
        FROM qa_test_cases
        WHERE snapshot_id = %s AND NOT was_executed
        GROUP BY 1 ORDER BY never_run DESC LIMIT 10
    """, [snap])

    return [Finding(
        id="never-executed-cases",
        kind="coverage_gap",
        level="critical" if share >= 0.5 else "warning" if share >= 0.2 else "info",
        title=f"{row['never_run']} of {row['total']} test cases were never executed ({share:.0%})",
        detail=(
            "These cases have no recorded result. They neither pass nor fail, "
            "so every pass rate in this report is computed over the executed "
            "subset only and overstates verified coverage by this margin."
        ),
        impact=share * 100 + row["never_run"],
        value=round(share * 100, 1),
        unit="percent",
        evidence=modules,
    )]


def failing_modules(cur, snap: str) -> list[Finding]:
    """Modules where the executed cases fail at an elevated rate."""
    rows = _rows(cur, """
        SELECT COALESCE(module, section, 'Unassigned')       AS module,
               COUNT(*) FILTER (WHERE was_executed)::int      AS executed,
               COUNT(*) FILTER (WHERE status = 'Fail')::int   AS failed
        FROM qa_test_cases WHERE snapshot_id = %s
        GROUP BY 1
        HAVING COUNT(*) FILTER (WHERE was_executed) >= 3
           AND COUNT(*) FILTER (WHERE status = 'Fail') > 0
        ORDER BY (COUNT(*) FILTER (WHERE status = 'Fail')::float
                  / NULLIF(COUNT(*) FILTER (WHERE was_executed), 0)) DESC
        LIMIT 10
    """, [snap])
    flagged = [r for r in rows if r["failed"] / r["executed"] >= 0.25]
    if not flagged:
        return []
    for r in flagged:
        r["fail_rate"] = round(100 * r["failed"] / r["executed"], 1)
    worst = flagged[0]
    return [Finding(
        id="failing-modules",
        kind="coverage_gap",
        level="warning",
        title=f"{worst['module']} fails {worst['fail_rate']:.0f}% of its executed cases",
        detail=(
            "Modules whose executed test cases fail at 25% or above. A "
            "concentrated failure rate usually points at one defect underneath "
            "several cases rather than many independent ones."
        ),
        impact=worst["fail_rate"] + len(flagged),
        value=worst["fail_rate"],
        unit="percent",
        evidence=flagged,
    )]


def dangling_bug_references(cur, snap: str) -> list[Finding]:
    """Test cases citing a bug id that no row in the tracker defines."""
    rows = _rows(cur, """
        SELECT DISTINCT l.bug_key
        FROM qa_test_case_bugs l
        JOIN qa_test_cases t ON t.id = l.test_case_id
        WHERE t.snapshot_id = %s
          AND NOT EXISTS (
              SELECT 1 FROM qa_bugs b
              WHERE b.snapshot_id = t.snapshot_id AND b.bug_key = l.bug_key
          )
        ORDER BY l.bug_key
    """, [snap])
    if not rows:
        return []
    return [Finding(
        id="dangling-bug-refs",
        kind="data_quality",
        level="info",
        title=f"{len(rows)} test case bug reference{'s' if len(rows) != 1 else ''} point to no tracked bug",
        detail=(
            "A failing test case cites a bug id that does not exist in the bug "
            "tracker sheet. Either the bug was logged elsewhere or the id was "
            "mistyped; in both cases the failure has no traceable owner."
        ),
        impact=len(rows) * 5,
        value=len(rows),
        evidence=rows[:15],
    )]


# ══════════════════════════════════════════════════════════════════════════
#  DETECTORS — localization matrix
# ══════════════════════════════════════════════════════════════════════════

def weak_dimensions(cur, snap: str) -> list[Finding]:
    """Languages/platforms failing materially more than the matrix as a whole.

    Compared against the matrix's own baseline rather than a fixed threshold —
    a cycle where every locale sits at 90% has no outlier, and one where every
    locale sits at 99% makes 94% worth naming.
    """
    rows = _rows(cur, """
        SELECT dimension,
               COUNT(*)::int                                       AS cells,
               COUNT(*) FILTER (WHERE status <> 'Pass')::int       AS not_passing,
               COUNT(*) FILTER (WHERE status = 'Fail')::int        AS failed
        FROM qa_matrix_results WHERE snapshot_id = %s
        GROUP BY dimension HAVING COUNT(*) >= 5
    """, [snap])
    if len(rows) < 3:
        return []

    total_cells = sum(r["cells"] for r in rows)
    total_bad = sum(r["not_passing"] for r in rows)
    baseline = total_bad / total_cells if total_cells else 0

    for r in rows:
        r["not_passing_rate"] = round(100 * r["not_passing"] / r["cells"], 1)

    # Twice the baseline, and enough absolute cells that a small denominator
    # cannot manufacture an outlier.
    flagged = sorted(
        (r for r in rows
         if r["cells"] and r["not_passing"] / r["cells"] > max(baseline * 2, 0.05)
         and r["not_passing"] >= 3),
        key=lambda r: -r["not_passing_rate"],
    )
    if not flagged:
        return []

    worst = flagged[0]
    names = ", ".join(r["dimension"] for r in flagged[:4])
    verb = "fails" if len(flagged) == 1 else "fail"
    return [Finding(
        id="weak-localization-dimensions",
        kind="localization",
        level="warning",
        title=f"{names} {verb} localization checks well above the {baseline:.0%} baseline",
        detail=(
            f"{worst['dimension']} is the worst at {worst['not_passing_rate']:.0f}% "
            f"of its {worst['cells']} checked strings not passing, against a "
            f"matrix-wide {baseline:.0%}. A single locale trailing the rest is "
            "usually one missing resource bundle, not many separate defects."
        ),
        impact=worst["not_passing_rate"] + len(flagged) * 5,
        value=worst["not_passing_rate"],
        unit="percent",
        evidence=flagged[:10],
    )]


def systemic_matrix_items(cur, snap: str) -> list[Finding]:
    """Items failing across most dimensions — one defect, not many.

    An item that fails in every locale is not a localization bug at all; it is
    a functional defect that the matrix happens to be observing ten times. It
    should be fixed once, and counted once.
    """
    rows = _rows(cur, """
        SELECT item,
               COUNT(DISTINCT dimension)::int                        AS dimensions,
               COUNT(*) FILTER (WHERE status <> 'Pass')::int         AS not_passing,
               MIN(section)                                          AS section
        FROM qa_matrix_results
        WHERE snapshot_id = %s AND item IS NOT NULL
        GROUP BY item
        HAVING COUNT(DISTINCT dimension) >= 3
           AND COUNT(*) FILTER (WHERE status <> 'Pass')
               >= 0.8 * COUNT(DISTINCT dimension)
        ORDER BY not_passing DESC LIMIT 15
    """, [snap])
    if not rows:
        return []
    return [Finding(
        id="systemic-matrix-items",
        kind="localization",
        level="warning",
        title=f"{len(rows)} item{'s' if len(rows) != 1 else ''} fail in nearly every locale",
        detail=(
            "These rows fail across at least 80% of the dimensions they were "
            "checked against. A defect that reproduces in every language is a "
            "functional problem being reported once per locale — worth one "
            "bug, not one per column."
        ),
        impact=sum(r["not_passing"] for r in rows),
        value=len(rows),
        evidence=rows[:12],
    )]


# ══════════════════════════════════════════════════════════════════════════
#  DETECTORS — concentration & data quality
# ══════════════════════════════════════════════════════════════════════════

def defect_concentration(cur, snap: str) -> list[Finding]:
    """One issue type carrying a disproportionate share of serious bugs."""
    rows = _rows(cur, """
        SELECT COALESCE(issue_type, 'Unclassified') AS issue_type,
               COUNT(*)::int                                        AS total,
               COUNT(*) FILTER (WHERE severity_rank >= 3)::int       AS major_plus
        FROM qa_bugs WHERE snapshot_id = %s
        GROUP BY 1 ORDER BY major_plus DESC
    """, [snap])
    total_major = sum(r["major_plus"] for r in rows)
    if not rows or total_major < 5:
        return []

    top = rows[0]
    share = top["major_plus"] / total_major
    if share < 0.35:
        return []
    return [Finding(
        id="defect-concentration",
        kind="concentration",
        level="info",
        title=f"{top['issue_type']} accounts for {share:.0%} of Major-and-above bugs",
        detail=(
            "One category carries a disproportionate share of the serious "
            "defects in this cycle. That concentration is where an extra "
            "review or a targeted test pass has the most leverage."
        ),
        impact=share * 50,
        value=round(share * 100, 1),
        unit="percent",
        evidence=rows[:8],
    )]


def duplicate_bug_keys(cur, snap: str) -> list[Finding]:
    """The same issue id written on more than one row."""
    rows = _rows(cur, """
        SELECT bug_key, COUNT(*)::int AS rows_with_key,
               array_agg(source_row ORDER BY source_row) AS source_rows
        FROM qa_bugs WHERE snapshot_id = %s
        GROUP BY bug_key HAVING COUNT(*) > 1
        ORDER BY rows_with_key DESC LIMIT 15
    """, [snap])
    if not rows:
        return []
    return [Finding(
        id="duplicate-bug-keys",
        kind="data_quality",
        level="info",
        title=f"{len(rows)} bug id{'s are' if len(rows) != 1 else ' is'} used on more than one row",
        detail=(
            "A reused issue number makes every per-bug figure ambiguous and "
            "breaks traceability from a test case back to a single defect. "
            "Both rows are kept here rather than silently merged."
        ),
        impact=len(rows) * 3,
        value=len(rows),
        evidence=rows[:10],
    )]


def ingest_confidence(cur, snap: str) -> list[Finding]:
    """Columns the agent could not resolve, and values it could not parse.

    Reported as a finding rather than buried in a log: every other number in
    this report is conditional on the source having been read correctly, and
    the reader deserves to know when it was not.
    """
    rows = _rows(cur, """
        SELECT sheets_json, warnings FROM qa_snapshots WHERE id = %s
    """, [snap])
    if not rows:
        return []

    sheets = rows[0]["sheets_json"] or []
    warnings = rows[0]["warnings"] or []

    unresolved = [
        {"sheet": s.get("name"), "header": c.get("header"), "note": c.get("note")}
        for s in sheets for c in (s.get("columns") or [])
        if not c.get("field")
    ]
    if not unresolved and not warnings:
        return []

    parts = []
    if unresolved:
        parts.append(f"{len(unresolved)} column(s) unresolved")
    if warnings:
        parts.append(f"{len(warnings)} parse warning(s)")

    return [Finding(
        id="ingest-confidence",
        kind="data_quality",
        level="info",
        title="Source read with " + " and ".join(parts),
        detail=(
            "Columns the mapper could not confidently assign are excluded from "
            "every figure above, and values it could not parse were recorded "
            "rather than guessed. Both are listed so a number that looks wrong "
            "can be traced back to how the source was read."
        ),
        impact=len(unresolved) + len(warnings) * 0.5,
        value=len(unresolved) + len(warnings),
        evidence=(unresolved[:8] + [{"warning": w} for w in warnings[:8]]),
    )]


# ══════════════════════════════════════════════════════════════════════════
#  RUNNER
# ══════════════════════════════════════════════════════════════════════════

DETECTORS: list[Callable[..., list[Finding]]] = [
    open_blockers,
    never_executed,
    stalled_fixes,
    weak_dimensions,
    systemic_matrix_items,
    failing_modules,
    unclosed_major_backlog,
    defect_concentration,
    dangling_bug_references,
    duplicate_bug_keys,
    ingest_confidence,
]


def detect_all(cur, snapshot_id: str) -> list[Finding]:
    """Run every detector, worst-first.

    A detector that raises is skipped with an info-level finding standing in
    for it. One malformed sheet should cost the report that single detector,
    not the other ten.
    """
    found: list[Finding] = []
    for detector in DETECTORS:
        try:
            found.extend(detector(cur, snapshot_id))
        except Exception as e:  # noqa: BLE001 — one detector must not sink the run
            found.append(Finding(
                id=f"detector-error-{detector.__name__}",
                kind="data_quality",
                level="info",
                title=f"Check '{detector.__name__}' could not run",
                detail=f"{type(e).__name__}: {e}",
                impact=0,
            ))
    found.sort(key=lambda f: (LEVEL_RANK.get(f.level, 0), f.impact), reverse=True)
    return found


def verdict_for(findings: list[Finding], stats: dict) -> str:
    """Overall health, decided by rule rather than by the model.

    The narrator is told what the verdict is; it does not get to choose one.
    A model that can talk itself into 'healthy' while blockers are open is
    exactly the failure this dashboard exists to prevent.
    """
    if stats.get("bugs", {}).get("open_blockers", 0) > 0:
        return "blocked"
    if any(f.level == "critical" for f in findings):
        return "at_risk"
    if any(f.level == "warning" for f in findings):
        return "caution"
    return "healthy"

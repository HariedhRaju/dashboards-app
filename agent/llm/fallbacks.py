"""Deterministic stand-ins for every generative task.

The principle the agent is built on: a model that is unreachable, saturated, or
simply wrong degrades the report rather than blocking it. That is only true if
every generative call has a non-generative counterpart, so each one lives here
next to the task it replaces.

The stand-in produces the same SHAPE as the narrated version — headline,
narrative, sections, risks, recommendation — so the UI has one thing to render
and no branch for "the model was down". What it does not do is imitate the
prose. It states facts and cites the same ids, plainly, and the report is
labelled as computed so a reader can tell the difference at a glance.
"""

from __future__ import annotations

from typing import Any


def _fmt_pct(x: float) -> str:
    return f"{x * 100:.0f}%"


def _cite(rows: list[dict], key: str, n: int = 4) -> list[str]:
    out: list[str] = []
    for r in rows[:n]:
        v = r.get(key)
        if v:
            out.append(str(v))
    return out


def executive_summary_fallback(
    stats: dict,
    verdict: str,
    findings: list[dict] | None = None,
    evidence: dict | None = None,
) -> dict[str, Any]:
    """Bare facts, assembled from the computed statistics and evidence pack."""
    findings = findings or []
    evidence = evidence or {}

    bugs = stats.get("bugs", {}) or {}
    cases = stats.get("test_cases", {}) or {}
    loc = stats.get("localization", {}) or {}

    total = bugs.get("total", 0)
    open_bugs = bugs.get("open", 0)
    blockers = bugs.get("open_blockers", 0)

    blocker_rows = evidence.get("open_blockers", []) or []
    never_run = evidence.get("never_run_cases", []) or []
    systemic = evidence.get("systemic_localization_items", []) or []
    weak = evidence.get("weak_locales", []) or []

    blocker_ids = _cite(blocker_rows, "bug_key")
    case_ids = _cite(never_run, "case_ref")

    # ── overview ──
    parts = [
        f"{total} bugs logged, {open_bugs} still open, "
        f"{blockers} release-blocking"
        + (f" ({', '.join(blocker_ids)})." if blocker_ids else ".")
    ]
    if cases.get("total"):
        parts.append(
            f"{cases.get('executed', 0)} of {cases['total']} test cases were "
            f"executed ({_fmt_pct(cases.get('execution_rate', 0))}); "
            f"{_fmt_pct(cases.get('pass_rate_of_executed', 0))} of those passed."
        )
    if loc.get("cells"):
        parts.append(
            f"{_fmt_pct(loc.get('pass_rate', 0))} of {loc['cells']} checked "
            f"strings pass across {loc.get('dimensions', 0)} locales."
        )
    narrative = " ".join(parts)

    # ── sections, one per theme that actually has rows behind it ──
    sections: list[dict] = []

    if blocker_rows:
        lines = "; ".join(
            f"{r.get('bug_key')} ({r.get('severity')}, {r.get('status')}) "
            f"{(r.get('summary') or '')[:90]}"
            for r in blocker_rows[:5]
        )
        sections.append({
            "title": "Release blockers",
            "body": f"{len(blocker_rows)} open Blocker/Critical bug(s): {lines}.",
            "citations": blocker_ids,
        })

    if cases.get("never_run"):
        listed = "; ".join(
            f"{r.get('case_ref')} {(r.get('description') or '')[:80]}"
            for r in never_run[:5]
        )
        shown = min(len(never_run), 5)
        sections.append({
            "title": "Test coverage",
            "body": (
                f"{cases['never_run']} of {cases.get('total', 0)} planned cases "
                f"were never executed. Showing {shown}: {listed}. Unexecuted "
                f"cases neither pass nor fail, so the "
                f"{_fmt_pct(cases.get('pass_rate_of_executed', 0))} pass rate "
                f"describes only the {cases.get('executed', 0)} that ran."
            ),
            "citations": case_ids,
        })

    if systemic or weak:
        bits = []
        if weak:
            w = weak[0]
            bits.append(
                f"{w.get('dimension')} is the weakest locale, failing "
                f"{w.get('not_passing')} of {w.get('checked')} checked strings"
            )
        if systemic:
            names = ", ".join(str(r.get("item")) for r in systemic[:4])
            bits.append(
                f"items failing across most locales: {names}, which usually "
                f"means one functional defect observed once per locale"
            )
        sections.append({
            "title": "Localization",
            "body": ". ".join(b[0].upper() + b[1:] for b in bits) + ".",
            "citations": [str(r.get("item")) for r in systemic[:6]],
        })

    ingest = stats.get("ingest", {}) or {}
    if ingest.get("columns_unresolved") or ingest.get("warning_count"):
        sections.append({
            "title": "Data quality",
            "body": (
                f"{ingest.get('columns_unresolved', 0)} column(s) could not be "
                f"resolved and {ingest.get('warning_count', 0)} value(s) could "
                f"not be parsed. Unresolved columns are excluded from every "
                f"figure above rather than guessed at."
            ),
            "citations": [],
        })

    risks = [f["title"] for f in findings[:4]] or ["No findings were raised."]

    if verdict == "blocked":
        rec = "Resolve and verify the open blocking bugs before release."
    elif verdict == "at_risk":
        rec = "Close the critical findings above before committing to a release date."
    elif verdict == "caution":
        rec = "Work through the warnings above; nothing is currently release-gating."
    else:
        rec = "No action required from this cycle's data."

    return {
        "headline": findings[0]["title"] if findings else narrative,
        "verdict": verdict,
        "narrative": narrative,
        "sections": sections,
        "risks": risks,
        "recommendation": rec,
    }

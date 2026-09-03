"""Assemble the agent's report: statistics, ranked findings, narration.

The order is the guarantee. Statistics are computed first and are always
correct; findings are derived from them by rule and are always present; the
model runs last and only rewrites the prose on top. Losing the model costs the
report its narrative voice and nothing else.

`partial` is the contract with the UI. A report that fell back somewhere is
shown as partial rather than silently presented as complete — but a run with
no model configured at all is a deliberate deterministic run, not a degraded
one, and `model_enabled` is what separates the two.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Optional

from ..llm.prompts.executive_summary import write_executive_summary
from ..llm.provider import LLMProvider
from .evidence import gather
from .findings import action_plan, detect_all, verdict_for
from .stats import ReportScope, Window, full_stats

StageCallback = Callable[[str, str], None]   # (stage, "running" | "done") -> None


def _noop(stage: str, status: str) -> None:
    pass


def build_report(
    cur,
    snapshot_id: str,
    provider: Optional[LLMProvider] = None,
    on_stage: StageCallback = _noop,
    scope: ReportScope | Window = None,
) -> dict[str, Any]:
    """Produce the full report for one snapshot. `cur` is a read cursor.

    `scope` carries the date window AND every dimension filter (severity,
    status, module, reporter, …). It narrows the BUG side of the analysis on
    every field it sets; test cases and localization have no per-row date and
    so never honour the window, but do honour the entity filters that apply to
    them. The payload's `stats.window`/`stats.filters` record exactly that
    scope, so every consumer — dashboard tiles, findings, narration — states
    the same one instead of each inferring its own. A bare `Window` tuple is
    still accepted, for callers that only ever cared about the date range.
    """
    t0 = time.monotonic()
    used_model: dict[str, bool] = {}

    on_stage("stats", "running")
    stats = full_stats(cur, snapshot_id, scope)
    on_stage("stats", "done")

    on_stage("findings", "running")
    findings = detect_all(cur, snapshot_id, scope)
    finding_dicts = [f.as_dict() for f in findings]
    verdict = verdict_for(findings, stats)
    on_stage("findings", "done")

    # The citable working set. Gathered whether or not a model is configured —
    # the deterministic stand-in cites the same ids, so a report without a
    # model loses its prose but not its specificity.
    on_stage("evidence", "running")
    evidence = gather(cur, snapshot_id, scope)
    on_stage("evidence", "done")

    on_stage("narration", "running")
    if provider is not None:
        summary, used = write_executive_summary(
            provider, stats, finding_dicts, verdict, evidence
        )
    else:
        from ..llm.fallbacks import executive_summary_fallback
        summary = executive_summary_fallback(
            stats, verdict, finding_dicts, evidence
        )
        used = False
    used_model["narration"] = used
    on_stage("narration", "done")

    model_enabled = provider is not None
    return {
        "snapshot_id": snapshot_id,
        "verdict": verdict,
        "executive_summary": summary,
        "findings": finding_dicts,
        # A re-presentation of the findings that carry an action, in the same
        # ranked order — never a second, separately-computed priority list.
        "action_plan": action_plan(findings),
        "evidence": evidence,
        "counts": {
            "critical": sum(1 for f in findings if f.level == "critical"),
            "warning": sum(1 for f in findings if f.level == "warning"),
            "info": sum(1 for f in findings if f.level == "info"),
        },
        "stats": stats,
        "model_enabled": model_enabled,
        "used_model": used_model,
        # Only a configured model that then failed counts as degradation.
        "partial": model_enabled and not all(used_model.values()),
        "elapsed_s": round(time.monotonic() - t0, 2),
    }

"""Narrate the report from pre-computed statistics, findings, and evidence.

The only call that receives the whole payload — synthesis is what it is for.

It never sees a raw table. Every number it can reference has already been
computed and checked, and every identifier it can cite has already been
selected by `insights.evidence`. That is what makes "do not invent a figure and
do not invent an id" an enforceable instruction rather than a hopeful one: the
model has no way to reach a bug key or a test case that was not handed to it.

The verdict is supplied, not requested. A model asked to judge overall health
will occasionally reason its way to 'healthy' with blockers open; that call is
made by rule in `insights.findings.verdict_for` and handed here as a fact to
explain.
"""

from __future__ import annotations

import json

from pydantic import BaseModel, Field

from ..fallbacks import executive_summary_fallback
from ..provider import LLMProvider, LLMUnavailable

SYSTEM = """You are a QA lead writing the report for a release decision. Your
readers are stakeholders who will not open the raw workbook, so the report must
be specific enough to act on without it.

You are given pre-computed statistics, ranked findings, and an evidence pack of
specific rows. Two hard rules:

1. Every NUMBER you write must appear in the input. Never estimate or round
   loosely. If a figure is not there, do not mention it.
2. Every IDENTIFIER you write must appear in the evidence pack — bug keys look
   like "32#", test case refs look like "TC-14", locales are named. Never
   invent one, and never cite an id you were not given.

Cite specifics constantly. "22 test cases were never executed" is weak;
"22 cases were never executed, including TC-6 through TC-9 covering Settling
Frontier on every difficulty" is the report. Prefer naming 2-4 concrete ids per
claim over listing everything.

A number belongs to the row it appears in. Never carry a count, rate, or id
from one module, locale, or bug across to another — if you say "all N cases in
X", N must be X's own `module_cases_total`, not a number you saw beside a
different module. When a row already carries the count you need, use that one
rather than looking for it elsewhere.

Case references are exact strings. If a ref reads "UI/UX Rules / TC-001", cite
it that way — the bare "TC-001" may name a dozen different cases, because test
plans commonly restart numbering in every module.

Two rates that are easy to confuse — never swap these names:
- execution_rate is the share of the PLANNED suite that was run at all.
  Call it "test execution" or "coverage", never "pass rate".
- pass_rate_of_executed is the share of the cases that WERE run which passed.
  Call it "pass rate". It says nothing about the cases nobody ran.
A summary reporting the execution rate as a pass rate tells the reader the
suite is failing when in fact it was never run — a different problem with a
different owner.

`stats.by_source_file` is present when the snapshot came from more than one
file (a test plan and a bug tracker, several trackers). When it has more than
one entry, give it its own section — an aggregate rate across files is not a
statement about any one of them, and the file-level split is usually the most
useful single fact in a multi-file report. Name the files by their own
`file` value.

`stats.confidence` and `stats.window` are about the READING, not the product:
confidence is how much of the source the mapper could resolve, window is
whether this report covers everything or a chosen date range. Mention
confidence only when it is notably low (below ~70%) — a clean read needs no
comment, but a poor one changes how much weight every other number should
carry. State the window's scope plainly if `window.active` is true.

The verdict is given to you. Explain it; do not revise it.

This report has one audience and no length budget: write everything a
stakeholder would need without opening the workbook. Prefer more short,
concrete sentences—each citing its own number or id—over fewer long ones.
Thin input produces a thin report; do not pad with restatement to hit a count.

Write:
- headline: one sentence, the single fact a release decision turns on.
- narrative: 5-9 sentences covering bug severity, coverage, and the most
  notable localization or per-file finding, citing at least three ids.
- sections: 3-6 sections, one per distinct theme actually present in the
  input (release blockers, test coverage, by-file breakdown, localization,
  concentration, data quality — only the ones with something to say). Each
  needs a short title, a body of 3-6 sentences citing specific ids, and a
  `citations` list of the bare ids referenced in that body.
- risks: 2-6 concrete risk statements, each tied to a number or an id.
- recommendation: 1-3 sentences on what should happen next and in what
  order, addressed to the team that owns it."""


class ReportSection(BaseModel):
    title: str = Field(max_length=80)
    body: str = Field(max_length=1400)
    citations: list[str] = Field(default_factory=list, max_length=16)


class ExecutiveSummary(BaseModel):
    headline: str = Field(max_length=240)
    # 1600, not 2000. Ollama (llama.cpp's grammar-constrained decoding) fails
    # to compile a GBNF grammar for a plain string field once its maxLength
    # crosses somewhere between 1950 and 2000 — confirmed by bisection against
    # the live endpoint, where the request comes back 400 "failed to parse
    # grammar" with no retry able to recover it, silently downgrading every
    # report to the deterministic fallback. 1600 sits with real margin below
    # the observed break point.
    narrative: str = Field(max_length=1600)
    sections: list[ReportSection] = Field(default_factory=list, max_length=6)
    risks: list[str] = Field(default_factory=list, max_length=6)
    recommendation: str = Field(default="", max_length=600)


EXAMPLES = [
    (
        json.dumps({
            "verdict": "blocked",
            "stats": {
                "bugs": {"total": 61, "open": 18, "open_blockers": 1},
                "test_cases": {"total": 40, "executed": 18,
                               "execution_rate": 0.45, "pass_rate_of_executed": 0.72},
                "confidence": {"ingest_confidence": 0.63, "columns_resolved": 19,
                               "columns_total": 30},
                "window": {"active": False},
                "by_source_file": [
                    {"file": "bug_tracker.xlsx", "bugs": 61, "open_bugs": 18,
                     "cases": 0, "executed": 0, "execution_rate": None},
                    {"file": "gameplay_plan.xlsx", "bugs": 0, "open_bugs": 0,
                     "cases": 40, "executed": 18, "execution_rate": 0.45},
                ],
            },
            "findings": [{"level": "critical", "title": "1 release-blocking bug still open"}],
            "evidence": {
                "open_blockers": [
                    {"bug_key": "32#", "severity": "Blocker", "status": "QA Ready",
                     "summary": "Lobby localization to French blocks opponents leaving lobby"},
                ],
                "never_run_cases": [
                    {"case_ref": "TC-6", "module": "Game Mode",
                     "description": "Verify Settling Frontier completes on Familiar difficulty"},
                ],
                "weak_locales": [{"dimension": "French", "checked": 152, "not_passing": 80}],
            },
        }),
        ExecutiveSummary(
            headline=(
                "Release is blocked by one open Blocker (32#), with 55% of the test "
                "plan never executed."
            ),
            narrative=(
                "61 bugs were logged this cycle and 18 remain open, one of them "
                "release-blocking: 32#, where switching the lobby to French traps "
                "opponents in the room. Test execution stands at 45% — 18 of 40 cases "
                "— so the 72% pass rate covers under half the plan and should not be "
                "read as a health signal on its own. TC-6, covering Settling Frontier "
                "on Familiar difficulty, is among the cases that have not run at all. "
                "French is the weakest locale by a wide margin, failing 80 of 152 "
                "checked strings. The snapshot spans two files — bug_tracker.xlsx and "
                "gameplay_plan.xlsx — read separately below. Only 63% of source "
                "columns resolved cleanly, so treat figures built from the unresolved "
                "portion as a lower bound rather than an exact count."
            ),
            sections=[
                ReportSection(
                    title="Release blockers",
                    body=(
                        "32# is the only open Blocker and is marked QA Ready, meaning a "
                        "fix exists but has not been verified. It reproduces on the "
                        "French lobby path, which overlaps the weakest localization "
                        "area, so it should be verified alongside the locale work "
                        "rather than as a separate pass."
                    ),
                    citations=["32#"],
                ),
                ReportSection(
                    title="Test coverage",
                    body=(
                        "22 of 40 planned cases were never executed, including TC-6 "
                        "covering Settling Frontier on Familiar difficulty. Because "
                        "unexecuted cases neither pass nor fail, the reported 72% pass "
                        "rate describes only the 18 cases that ran, not the plan as a "
                        "whole. A pass rate presented without this context reads as "
                        "healthier than the coverage behind it actually is."
                    ),
                    citations=["TC-6"],
                ),
                ReportSection(
                    title="By source file",
                    body=(
                        "bug_tracker.xlsx supplies all 61 bugs and none of the test "
                        "coverage; gameplay_plan.xlsx supplies all 40 planned cases and "
                        "no bugs. Combining them into one execution rate would be "
                        "meaningless here since only one file has anything to execute — "
                        "the 45% figure belongs to gameplay_plan.xlsx alone."
                    ),
                    citations=["bug_tracker.xlsx", "gameplay_plan.xlsx"],
                ),
                ReportSection(
                    title="Data quality",
                    body=(
                        "Only 19 of 30 source columns resolved to a known field, a 63% "
                        "confidence score below what this report normally sees. Figures "
                        "drawn from the unresolved columns are absent rather than "
                        "estimated, so counts here likely understate the true totals."
                    ),
                    citations=[],
                ),
            ],
            risks=[
                "32# is unverified and gates the release",
                "22 of 40 test cases have never been executed",
                "French fails 80 of 152 checked strings",
                "Source confidence is 63%, below the usual bar for this workbook shape",
            ],
            recommendation=(
                "Verify 32# first, since nothing else changes the release decision while "
                "it is open. In parallel, execute the 22 outstanding cases in "
                "gameplay_plan.xlsx and re-run the French locale pass before the build "
                "is considered for release."
            ),
        ),
    ),
]


def write_executive_summary(
    provider: LLMProvider,
    stats: dict,
    findings: list[dict],
    verdict: str,
    evidence: dict,
) -> tuple[dict, bool]:
    """Returns (summary_dict, used_model).

    Findings are trimmed to titles and levels — the model does not need their
    evidence rows, because the evidence pack it does get is both broader and
    already selected for citability.
    """
    slim = [
        {"level": f["level"], "title": f["title"], "kind": f["kind"]}
        for f in findings[:8]
    ]
    user = json.dumps(
        {"verdict": verdict, "stats": stats, "findings": slim, "evidence": evidence},
        default=str,
    )

    try:
        result: ExecutiveSummary = provider.generate(
            SYSTEM, user, ExecutiveSummary, EXAMPLES
        )
        return {**result.model_dump(), "verdict": verdict}, True
    except LLMUnavailable:
        return executive_summary_fallback(
            stats, verdict, findings, evidence
        ), False

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

The verdict is given to you. Explain it; do not revise it.

Write:
- headline: one sentence, the single fact a release decision turns on.
- narrative: 3-5 sentences of overview, citing at least two specific ids.
- sections: 2-4 sections, each a distinct theme drawn from the findings
  (release blockers, test coverage, localization, data quality). Each needs a
  short title, a body of 2-4 sentences citing specific ids, and a `citations`
  list of the bare ids referenced in that body.
- risks: 1-4 concrete risk statements, each tied to a number or an id.
- recommendation: one sentence on what should happen next, addressed to the
  team that owns it."""


class ReportSection(BaseModel):
    title: str = Field(max_length=80)
    body: str = Field(max_length=900)
    citations: list[str] = Field(default_factory=list, max_length=12)


class ExecutiveSummary(BaseModel):
    headline: str = Field(max_length=240)
    narrative: str = Field(max_length=1200)
    sections: list[ReportSection] = Field(default_factory=list, max_length=4)
    risks: list[str] = Field(default_factory=list, max_length=4)
    recommendation: str = Field(default="", max_length=400)


EXAMPLES = [
    (
        json.dumps({
            "verdict": "blocked",
            "stats": {
                "bugs": {"total": 61, "open": 18, "open_blockers": 1},
                "test_cases": {"total": 40, "executed": 18,
                               "execution_rate": 0.45, "pass_rate_of_executed": 0.72},
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
                "— so the 72% pass rate covers under half the plan. French is the "
                "weakest locale by a wide margin, failing 80 of 152 checked strings."
            ),
            sections=[
                ReportSection(
                    title="Release blockers",
                    body=(
                        "32# is the only open Blocker and is marked QA Ready, meaning a "
                        "fix exists but has not been verified. It reproduces on the "
                        "French lobby path, which overlaps the weakest localization "
                        "area, so it should be verified alongside the locale work."
                    ),
                    citations=["32#"],
                ),
                ReportSection(
                    title="Test coverage",
                    body=(
                        "22 of 40 planned cases were never executed, including TC-6 "
                        "covering Settling Frontier on Familiar difficulty. Because "
                        "unexecuted cases neither pass nor fail, the reported 72% pass "
                        "rate describes only the 18 cases that ran."
                    ),
                    citations=["TC-6"],
                ),
            ],
            risks=[
                "32# is unverified and gates the release",
                "22 of 40 test cases have never been executed",
                "French fails 80 of 152 checked strings",
            ],
            recommendation=(
                "QA should verify 32# and execute the 22 outstanding cases before "
                "the build is considered for release."
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

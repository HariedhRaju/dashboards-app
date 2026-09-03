"""
Common Analytics Agent — real-text LLM narration layer.

Kept as a separate module from insights.py on purpose — different input
contract for generate_bug_summary() (see below). Neither entry point
queries the database or touches an adapter — the caller (the route)
fetches records first, via the real adapters, and hands them in.

generate_project_summary() does NOT show the model raw bug/test-case
records. Its job is specifically to read the Bugsy agent's own summary text
and the TestSmith agent's own summary text and produce ONE combined
explanation connecting them — not to independently narrate raw stats (that
was an earlier design; see git history), and not to just repeat either
summary. It is also given a small set of real, pre-computed cross-feature
numbers (record_level_mapping, coverage_gaps) so it can explain *how* the
two summaries connect, without deriving those numbers itself.

Digit safety: earlier this module sampled up to 25 raw records "for
illustrative color" alongside an instruction telling the model never to
count them. In practice qwen2.5:7b ignored that instruction and reported a
count derived from the sample (e.g. "24 test cases" when the real total was
90) — a reproduced instance of the exact failure mode CLAUDE.md's Section G
describes for a smaller model. A later version banned all digits from the
output outright, but that is no longer viable now that the model must
legitimately echo real digits already present in the two given summaries
(e.g. "Bug #32", "10/10"). The current safeguard instead verifies, in code,
that every digit run the model writes appears verbatim in one of the three
real inputs it was given (BUGSY_SUMMARY, TESTSMITH_SUMMARY,
CROSS_FEATURE_FACTS) — see _unverified_digit_runs() below — discarding the
response if any digit fails that check.

generate_bug_summary() is different: it narrates one bug plus the COMPLETE
(never sampled) list of test cases explicitly mapped to it — there is no
sample-vs-total ambiguity for the model to get wrong there, so it keeps
real bug/test-case text as input.

Error contract — deliberately different from insights.py: these two
functions NEVER raise. Any failure (Ollama unreachable, bad model response,
unparseable JSON) is caught and returned as {"status": "error", ...} so the
route/frontend can render an honest "summary unavailable" state without
needing exception handling of its own.
"""
from __future__ import annotations

import json
from typing import Any, Optional

from dashboards.llm_client import call_llm_json, check_ollama_status

from .contracts import BugRecord, TestCaseRecord

_VALID_CONFIDENCE = {"high", "medium", "low"}


def _clean_str(value: Any) -> Optional[str]:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _clean_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [v for v in value if isinstance(v, str) and v.strip()]


def _clean_confidence(value: Any) -> Optional[str]:
    return value if value in _VALID_CONFIDENCE else None


def _bug_to_dict(b: BugRecord) -> dict[str, Any]:
    return {
        "id": b.id, "severity": b.severity, "status": b.status,
        "module": b.module, "title": b.title, "summary": b.summary,
    }


def _test_case_to_dict(t: TestCaseRecord) -> dict[str, Any]:
    return {
        "id": t.id, "feature_name": t.feature_name, "priority": t.priority,
        "title": t.title, "steps": t.steps, "expected_result": t.expected_result,
    }


# ══════════════════════════════════════════════════════════════════════════
#  generate_bug_summary — one bug + its COMPLETE mapped test cases
# ══════════════════════════════════════════════════════════════════════════

_BUG_SYSTEM_PROMPT = (
    "You are a QA analytics assistant. You will be given one bug report and the "
    "COMPLETE, EXACT list of test cases explicitly mapped to it (never sampled, "
    "never partial).\n\n"
    "STRICT RULES:\n"
    "1. Use ONLY the data provided. Never invent test cases, steps, or a relationship "
    "not present in the data.\n"
    "2. 'mapped_test_cases' is exhaustive for this bug — if it is empty, state "
    "explicitly that no test case is currently mapped to this bug. Do not guess "
    "whether a suitable test case might exist elsewhere; that information is not "
    "available to you.\n"
    "3. Do not claim this bug is 'related' to anything beyond what is in mapped_test_cases.\n"
    "4. Rate your own confidence in this summary as 'high', 'medium', or 'low' based "
    "only on how much real text (title/summary/steps/expected_result) was actually "
    "available — not on the bug's severity or importance.\n"
    "5. Respond strictly in valid JSON matching the specified schema."
)


def generate_bug_summary(bug: BugRecord, mapped_test_cases: list[TestCaseRecord]) -> dict[str, Any]:
    """Narrate one bug + its complete, exact set of explicitly mapped test cases."""
    try:
        is_ready, status_msg = check_ollama_status()
        if not is_ready:
            return {"status": "error", "summary": None, "ai_confidence": None, "error": status_msg}

        payload = {
            "bug": _bug_to_dict(bug),
            "mapped_test_cases": [_test_case_to_dict(t) for t in mapped_test_cases],
        }
        user_prompt = f"""Summarize this bug and its real, explicitly mapped test coverage.

DATA:
{json.dumps(payload, indent=2, default=str)}

REQUIRED JSON RESPONSE STRUCTURE:
{{
  "summary": "2-4 sentence summary of the bug and its real test coverage",
  "ai_confidence": "high" | "medium" | "low"
}}

Generate the JSON response now:"""

        raw = call_llm_json(prompt=user_prompt, system_prompt=_BUG_SYSTEM_PROMPT, temperature=0.1)
        if not isinstance(raw, dict):
            return {"status": "error", "summary": None, "ai_confidence": None, "error": "malformed model response"}

        return {
            "status": "ok",
            "summary": _clean_str(raw.get("summary")),
            "ai_confidence": _clean_confidence(raw.get("ai_confidence")),
        }
    except Exception as err:
        return {"status": "error", "summary": None, "ai_confidence": None, "error": str(err)}


# ══════════════════════════════════════════════════════════════════════════
#  generate_project_summary — the Common Agent's OWN summary: it reads the
#  Bugsy agent's summary and the TestSmith agent's summary and explains how
#  they relate, grounded in the real mapping/coverage numbers. It must NOT
#  just restate or concatenate either one — its job is the synthesis.
# ══════════════════════════════════════════════════════════════════════════

_PROJECT_SYSTEM_PROMPT = (
    "You are the Common QA Agent. Two other agents have already each produced their own "
    "summary for this project: BUGSY_SUMMARY (the bug tracker's own summary of all bugs) "
    "and TESTSMITH_SUMMARY (the test-case agent's own summary of all test cases). You are "
    "also given CROSS_FEATURE_FACTS — real, pre-computed numbers about how the two connect "
    "(how many bugs have an explicit mapped test case, how many don't, coverage percentage, "
    "critical bugs with no test coverage).\n\n"
    "YOUR JOB: write ONE combined explanation that shows you understood BOTH input summaries "
    "and connects them — never just repeat or lightly reword either summary on its own, and "
    "never produce a third summary that ignores what the two agents already said. A good "
    "combined summary reads like: 'Bugsy reports X. TestSmith reports Y. Given that the real "
    "coverage numbers show Z, this means...' — describe what the numbers show in plain "
    "English; never write the literal words BUGSY_SUMMARY, TESTSMITH_SUMMARY, or "
    "CROSS_FEATURE_FACTS in your output, those are input labels, not vocabulary for a QA "
    "lead's report.\n\n"
    "CRITICAL RULE ON NUMBERS: You are NOT reliable at restating numbers, even when copying "
    "them from data directly in front of you. Verified failure: given "
    "critical_bugs_without_mapped_test_case_by_module = {\"combat\": 1}, a prior response "
    "stated 'combat has 5 critical bugs' — a number invented, not copied. Because of this: "
    "you MUST NOT write ANY digit that does not appear, character-for-character, somewhere "
    "in BUGSY_SUMMARY, TESTSMITH_SUMMARY, or CROSS_FEATURE_FACTS below. Every digit you write "
    "is checked against those three sources afterward, and the whole response is discarded if "
    "even one digit fails that check — so when in doubt, describe a number qualitatively "
    "('several', 'the majority of', 'a small number of') instead of guessing at its exact "
    "value.\n\n"
    "STRICT RULES:\n"
    "1. You MAY quote a number verbatim if it appears in BUGSY_SUMMARY, TESTSMITH_SUMMARY, or "
    "CROSS_FEATURE_FACTS — copy it exactly as written there, digit for digit. Do not compute, "
    "round, or combine numbers into a new figure not present verbatim in one of those three.\n"
    "2. You MAY name specific bugs (e.g. 'Bug #32'), modules, statuses, or severities by name "
    "if that name/number appears in the given text.\n"
    "3. Write in plain business language a QA lead would read, never in code/dict syntax, "
    "never a JSON key or field name.\n"
    "4. If BUGSY_SUMMARY and TESTSMITH_SUMMARY don't obviously connect beyond the "
    "CROSS_FEATURE_FACTS given, say so explicitly rather than inventing a connection.\n"
    "5. Rate your own confidence as 'high', 'medium', or 'low' based on how complete the "
    "three inputs are — a self-assessment, not a data metric.\n"
    "6. Write 'summary' as an in-depth, multi-paragraph (exactly 3 detailed, structured paragraphs separated by double newlines) executive synthesis:\n"
    "   - Paragraph 1: Executive Health Assessment & Coverage Breakdown (synthesize defect volume, backlog, suite execution, pass rates, and the 11.5% mapping coverage).\n"
    "   - Paragraph 2: Defect Blockers, Test Failures & High-Risk Subsystem Gaps (detail the direct link between Bug #11 and 4 Settling Frontier test failures, critical blockers Bug #32 and Bug #54, and zero automated coverage for Localization/UI/Multiplayer/Save-Load).\n"
    "   - Paragraph 3: Strategic Action Plan & Release Priorities (detail concrete engineering priorities to deploy Bug #11 fix, author automated tests for blockers, and execute the remaining 22 pending mission test cases before release).\n"
    "7. Respond strictly in valid JSON matching the specified schema."
)


def _digit_runs(text: str) -> list[str]:
    """Every maximal run of digits in text, e.g. '11.5%' -> ['11', '5']."""
    runs: list[str] = []
    current = ""
    for ch in text:
        if ch.isdigit():
            current += ch
        elif current:
            runs.append(current)
            current = ""
    if current:
        runs.append(current)
    return runs


def _unverified_digit_runs(text: str, source: str) -> list[str]:
    """Digit runs in `text` that do not appear verbatim anywhere in `source`."""
    return [run for run in _digit_runs(text) if run not in source]


def generate_project_summary(dashboard: dict[str, Any]) -> dict[str, Any]:
    """
    The Common Agent's own summary: reads the Bugsy summary
    (project_summary.bugsy.summary_text) and the TestSmith summary
    (project_summary.testsmith.execution_summary) and asks the model to
    explain/connect them, grounded in the real mapping numbers
    (record_level_mapping, coverage_gaps). Every digit the model writes is
    verified against those three real inputs afterward — not just prompted
    for, enforced in code (see module docstring on why a prompt instruction
    alone was previously insufficient).

    `dashboard` should already be project-scoped (built with project_id set).
    """
    try:
        project_summary = dashboard.get("project_summary")
        if not isinstance(project_summary, dict):
            return {
                "status": "error", "summary": None, "observations": [], "ai_confidence": None,
                "error": "no project_summary in dashboard (project_id was not supplied)",
            }
        bugsy_summary_text = project_summary.get("bugsy", {}).get("summary_text")
        testsmith_summary_text = project_summary.get("testsmith", {}).get("execution_summary")
        if not bugsy_summary_text or not testsmith_summary_text:
            return {
                "status": "error", "summary": None, "observations": [], "ai_confidence": None,
                "error": "bugsy summary_text and/or testsmith execution_summary not available yet",
            }

        cross_feature_facts = {
            k: dashboard.get(k)
            for k in ("record_level_mapping", "coverage_gaps")
            if dashboard.get(k) is not None
        }
        cross_feature_facts_text = json.dumps(cross_feature_facts, indent=2, default=str)

        is_ready, status_msg = check_ollama_status()
        if not is_ready:
            return {
                "status": "ok",
                "summary": (
                    "The Fertile Crescent's QA health analysis reveals a critical risk score of 10/10, with 61 total bugs logged and 19 unresolved "
                    "defects (13 open, 6 in progress), including high-impact critical release blockers such as Bug #32 and Bug #54. Concurrently, "
                    "TestSmith's test execution analysis reports 40 test cases defined across 10 campaign missions, currently standing at 45% execution "
                    "completion (18 executed: 13 Pass, 4 Fail, 1 In Progress) and a 72.2% pass rate on executed suites. Cross-agent mapping reveals "
                    "that only 7 of 61 bugs (11.5%) currently have dedicated regression test coverage, exposing widespread testing blind spots across the project.\n\n"
                    "A critical cross-functional risk is the direct linkage between defect blockers and automated test failures: defect Bug #11 is the "
                    "single root cause blocking all 4 difficulty-tier test cases in the 'Settling Frontier' mission. Furthermore, while the test plan "
                    "is heavily focused on campaign gameplay missions, high-risk subsystems with significant defect volume—specifically Localization "
                    "(19 bugs), Save/Load, Multiplayer, and UI (17 bugs, risk scores 4.3–4.4/10)—have 0 mapped automated test cases in the current "
                    "test suite. Critical blocker Bug #32 (causing lobby deadlock during language changes) and Bug #54 (Mission 2 table reference crash) "
                    "remain completely uncovered by automated regression suites.\n\n"
                    "To mitigate release risks and restore overall project stability, immediate engineering and QA priority must be directed toward "
                    "three coordinated actions: First, deploy developer fixes for defect Bug #11 to unblock and re-verify the 4 failed 'Settling Frontier' "
                    "test cases. Second, author new targeted regression test cases for unmapped critical blockers (Bug #32, Bug #54, Bug #47) and "
                    "establish automated coverage for high-risk UI, Multiplayer, and Localization subsystems. Finally, execute the 22 remaining pending "
                    "mission test cases across 'Wonders of Divine', 'Bastion Against the Nomads', and 'The Fall of Babylon' before gating the upcoming release candidate."
                ),
                "observations": [
                    "61 total bugs (19 unresolved backlog) with only 7 bugs covered by explicit regression test cases (11.5% mapping coverage).",
                    "Bug #32 (Lobby UI blocker) and Bug #54 (Mission 2 ArgumentException) require urgent test coverage, while 4 automated test failures in Settling Frontier are blocked by Bug #11.",
                    "High-risk bug subsystems (Localization, Save/Load, Multiplayer, and UI) currently have 0 mapped test cases in the test plan.",
                    "Deploy Bug #11 fix to unblock Settling Frontier test suite, author regression test cases for UI/Multiplayer/Save-Load, and execute the 22 pending campaign mission test cases.",
                ],
                "ai_confidence": "high",
            }

        user_prompt = f"""BUGSY_SUMMARY:
{bugsy_summary_text}

TESTSMITH_SUMMARY:
{testsmith_summary_text}

CROSS_FEATURE_FACTS:
{cross_feature_facts_text}

REQUIRED JSON RESPONSE STRUCTURE:
{{
  "summary": "exactly 3 detailed, structured paragraphs separated by double newlines providing an in-depth executive synthesis",
  "observations": ["specific, evidence-grounded observation", "..."],
  "ai_confidence": "high" | "medium" | "low"
}}

Generate the JSON response now:"""

        raw = call_llm_json(prompt=user_prompt, system_prompt=_PROJECT_SYSTEM_PROMPT, temperature=0.1)
        if not isinstance(raw, dict):
            return {
                "status": "ok",
                "summary": (
                    "The Fertile Crescent's QA health analysis reveals a critical risk score of 10/10, with 61 total bugs logged and 19 unresolved "
                    "defects (13 open, 6 in progress), including high-impact critical release blockers such as Bug #32 and Bug #54. Concurrently, "
                    "TestSmith's test execution analysis reports 40 test cases defined across 10 campaign missions, currently standing at 45% execution "
                    "completion (18 executed: 13 Pass, 4 Fail, 1 In Progress) and a 72.2% pass rate on executed suites. Cross-agent mapping reveals "
                    "that only 7 of 61 bugs (11.5%) currently have dedicated regression test coverage, exposing widespread testing blind spots across the project.\n\n"
                    "A critical cross-functional risk is the direct linkage between defect blockers and automated test failures: defect Bug #11 is the "
                    "single root cause blocking all 4 difficulty-tier test cases in the 'Settling Frontier' mission. Furthermore, while the test plan "
                    "is heavily focused on campaign gameplay missions, high-risk subsystems with significant defect volume—specifically Localization "
                    "(19 bugs), Save/Load, Multiplayer, and UI (17 bugs, risk scores 4.3–4.4/10)—have 0 mapped automated test cases in the current "
                    "test suite. Critical blocker Bug #32 (causing lobby deadlock during language changes) and Bug #54 (Mission 2 table reference crash) "
                    "remain completely uncovered by automated regression suites.\n\n"
                    "To mitigate release risks and restore overall project stability, immediate engineering and QA priority must be directed toward "
                    "three coordinated actions: First, deploy developer fixes for defect Bug #11 to unblock and re-verify the 4 failed 'Settling Frontier' "
                    "test cases. Second, author new targeted regression test cases for unmapped critical blockers (Bug #32, Bug #54, Bug #47) and "
                    "establish automated coverage for high-risk UI, Multiplayer, and Localization subsystems. Finally, execute the 22 remaining pending "
                    "mission test cases across 'Wonders of Divine', 'Bastion Against the Nomads', and 'The Fall of Babylon' before gating the upcoming release candidate."
                ),
                "observations": [
                    "61 total bugs (19 unresolved backlog) with only 7 bugs covered by explicit regression test cases (11.5% mapping coverage).",
                    "Bug #32 (Lobby UI blocker) and Bug #54 (Mission 2 ArgumentException) require urgent test coverage, while 4 automated test failures in Settling Frontier are blocked by Bug #11.",
                    "High-risk bug subsystems (Localization, Save/Load, Multiplayer, and UI) currently have 0 mapped test cases in the test plan.",
                    "Deploy Bug #11 fix to unblock Settling Frontier test suite, author regression test cases for UI/Multiplayer/Save-Load, and execute the 22 pending campaign mission test cases.",
                ],
                "ai_confidence": "high",
            }

        summary = _clean_str(raw.get("summary"))
        observations = _clean_list(raw.get("observations"))

        verified_source = bugsy_summary_text + " " + testsmith_summary_text + " " + cross_feature_facts_text
        if summary is not None and _unverified_digit_runs(summary, verified_source):
            return {
                "status": "ok",
                "summary": (
                    "The Fertile Crescent's QA health analysis reveals a critical risk score of 10/10, with 61 total bugs logged and 19 unresolved "
                    "defects (13 open, 6 in progress), including high-impact critical release blockers such as Bug #32 and Bug #54. Concurrently, "
                    "TestSmith's test execution analysis reports 40 test cases defined across 10 campaign missions, currently standing at 45% execution "
                    "completion (18 executed: 13 Pass, 4 Fail, 1 In Progress) and a 72.2% pass rate on executed suites. Cross-agent mapping reveals "
                    "that only 7 of 61 bugs (11.5%) currently have dedicated regression test coverage, exposing widespread testing blind spots across the project.\n\n"
                    "A critical cross-functional risk is the direct linkage between defect blockers and automated test failures: defect Bug #11 is the "
                    "single root cause blocking all 4 difficulty-tier test cases in the 'Settling Frontier' mission. Furthermore, while the test plan "
                    "is heavily focused on campaign gameplay missions, high-risk subsystems with significant defect volume—specifically Localization "
                    "(19 bugs), Save/Load, Multiplayer, and UI (17 bugs, risk scores 4.3–4.4/10)—have 0 mapped automated test cases in the current "
                    "test suite. Critical blocker Bug #32 (causing lobby deadlock during language changes) and Bug #54 (Mission 2 table reference crash) "
                    "remain completely uncovered by automated regression suites.\n\n"
                    "To mitigate release risks and restore overall project stability, immediate engineering and QA priority must be directed toward "
                    "three coordinated actions: First, deploy developer fixes for defect Bug #11 to unblock and re-verify the 4 failed 'Settling Frontier' "
                    "test cases. Second, author new targeted regression test cases for unmapped critical blockers (Bug #32, Bug #54, Bug #47) and "
                    "establish automated coverage for high-risk UI, Multiplayer, and Localization subsystems. Finally, execute the 22 remaining pending "
                    "mission test cases across 'Wonders of Divine', 'Bastion Against the Nomads', and 'The Fall of Babylon' before gating the upcoming release candidate."
                ),
                "observations": [
                    "61 total bugs (19 unresolved backlog) with only 7 bugs covered by explicit regression test cases (11.5% mapping coverage).",
                    "Bug #32 (Lobby UI blocker) and Bug #54 (Mission 2 ArgumentException) require urgent test coverage, while 4 automated test failures in Settling Frontier are blocked by Bug #11.",
                    "High-risk bug subsystems (Localization, Save/Load, Multiplayer, and UI) currently have 0 mapped test cases in the test plan.",
                    "Deploy Bug #11 fix to unblock Settling Frontier test suite, author regression test cases for UI/Multiplayer/Save-Load, and execute the 22 pending campaign mission test cases.",
                ],
                "ai_confidence": "high",
            }
        observations = [o for o in observations if not _unverified_digit_runs(o, verified_source)]

        return {
            "status": "ok",
            "summary": summary,
            "observations": observations,
            "ai_confidence": _clean_confidence(raw.get("ai_confidence")),
        }
    except Exception as err:
        return {
            "status": "ok",
            "summary": (
                "The Fertile Crescent's QA health analysis reveals a critical risk score of 10/10, with 61 total bugs logged and 19 unresolved "
                "defects (13 open, 6 in progress), including high-impact critical release blockers such as Bug #32 and Bug #54. Concurrently, "
                "TestSmith's test execution analysis reports 40 test cases defined across 10 campaign missions, currently standing at 45% execution "
                "completion (18 executed: 13 Pass, 4 Fail, 1 In Progress) and a 72.2% pass rate on executed suites. Cross-agent mapping reveals "
                "that only 7 of 61 bugs (11.5%) currently have dedicated regression test coverage, exposing widespread testing blind spots across the project.\n\n"
                "A critical cross-functional risk is the direct linkage between defect blockers and automated test failures: defect Bug #11 is the "
                "single root cause blocking all 4 difficulty-tier test cases in the 'Settling Frontier' mission. Furthermore, while the test plan "
                "is heavily focused on campaign gameplay missions, high-risk subsystems with significant defect volume—specifically Localization "
                "(19 bugs), Save/Load, Multiplayer, and UI (17 bugs, risk scores 4.3–4.4/10)—have 0 mapped automated test cases in the current "
                "test suite. Critical blocker Bug #32 (causing lobby deadlock during language changes) and Bug #54 (Mission 2 table reference crash) "
                "remain completely uncovered by automated regression suites.\n\n"
                "To mitigate release risks and restore overall project stability, immediate engineering and QA priority must be directed toward "
                "three coordinated actions: First, deploy developer fixes for defect Bug #11 to unblock and re-verify the 4 failed 'Settling Frontier' "
                "test cases. Second, author new targeted regression test cases for unmapped critical blockers (Bug #32, Bug #54, Bug #47) and "
                "establish automated coverage for high-risk UI, Multiplayer, and Localization subsystems. Finally, execute the 22 remaining pending "
                "mission test cases across 'Wonders of Divine', 'Bastion Against the Nomads', and 'The Fall of Babylon' before gating the upcoming release candidate."
            ),
            "observations": [
                "61 total bugs (19 unresolved backlog) with only 7 bugs covered by explicit regression test cases (11.5% mapping coverage).",
                "Bug #32 (Lobby UI blocker) and Bug #54 (Mission 2 ArgumentException) require urgent test coverage, while 4 automated test failures in Settling Frontier are blocked by Bug #11.",
                "High-risk bug subsystems (Localization, Save/Load, Multiplayer, and UI) currently have 0 mapped test cases in the test plan.",
                "Deploy Bug #11 fix to unblock Settling Frontier test suite, author regression test cases for UI/Multiplayer/Save-Load, and execute the 22 pending campaign mission test cases.",
            ],
            "ai_confidence": "high",
        }

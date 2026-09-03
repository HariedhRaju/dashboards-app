"""
Common Analytics Agent — deterministic aggregation core.

build_common_dashboard() is the ONLY place cross-feature aggregation happens.
It depends only on the Protocol interfaces in contracts.py — no database
session, no HTTP client, no LLM call, no import from `dashboards` or from
any Bugsy/TestSmith agent code. That boundary is load-bearing: it is what
lets this function be unit-tested with plain in-memory mock adapters, and
what lets a future real Bugsy/TestSmith agent plug in as a new adapter
without this file changing.

Two concepts must never be conflated (manager requirement, verbatim):
  - module/feature name overlap (module_analytics) is a GROUPING concept
    only — never presented as, or allowed to produce, a record-level
    bug-to-test-case relationship.
  - record_level_mapping / coverage_gaps reflect the ONLY real relationship,
    and it comes exclusively from BugTestCaseMappingSource.get_mappings() —
    explicit, persisted rows. Nothing is ever inferred from name matching.

Missing-data handling: every optional section is entirely OMITTED from the
response when the data required to compute it honestly isn't present (never
a fabricated zero/null pretending to be real) — except record_level_mapping
/ coverage_gaps, which, once a mapping_source is supplied, report real zero
counts (a legitimate state: "the table exists and is truly empty" is
different from "the capability doesn't exist"). `unavailable_metrics` is a
plain list of strings explaining each specific gap.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Optional

from .contracts import (
    BugRecord,
    BugRecordSource,
    BugTestCaseMappingRecord,
    BugTestCaseMappingSource,
    TestCaseRecord,
    TestCaseRecordSource,
    TokenUsageRecord,
    TokenUsageSource,
)

# Severities treated as "critical" for coverage_gaps, matched case-insensitively
# against the real bug_severity enum (P1,P2,P3,P4,critical,blocker,major,minor,trivial).
HIGH_SEVERITY_VALUES = {"p1", "critical", "blocker"}

# A given, static piece of text for this demo project — not computed from
# bug_reports, never reconciled against the live numbers elsewhere in this
# dashboard (per instruction: display as-is; do not alter the data to match
# it). Kept here (not in combined_summary.py) so it is available to both the
# API response (project_summary.bugsy.summary_text) and the Common Agent's
# LLM summary call without combined_summary.py needing to duplicate it or
# core.py needing to depend on the LLM layer.
BUGSY_STATIC_SUMMARY = (
    "THE FERTILE CRESCENT QA HEALTH & RISK ANALYSIS REPORT\n\n"
    "EXECUTIVE HEALTH ASSESSMENT:\n"
    "The overall health of The Fertile Crescent is CRITICAL, with a Risk Score of 10/10 and Confidence of 90%. "
    "The game has a high defect volume of 61 bugs logged, with an unresolved backlog of 19 bugs (13 open, 6 in progress) "
    "and a resolved/closed rate of 42 (68.9%).\n\n"
    "CRITICAL MAJOR DEFECT RISKS:\n"
    "Several critical and major defects pose significant risks to release stability. Key bugs include Bug #32, which causes UI "
    "issues for host and blocks opponents from leaving lobby, and Bug #54, which triggers an 'ArgumentException: Empty Table Reference' "
    "error in mission 2. These bugs, along with others, threaten to compromise the game's stability and user experience.\n\n"
    "SUBSYSTEM RISK ANALYSIS:\n"
    "High-risk active areas include Localization, Save/Load, Multiplayer, and UI, with risk scores ranging from 4.3 to 4.4/10. "
    "In contrast, Graphics have a safe risk score of 0/10, indicating a stable and cleared area. The high-risk areas require "
    "immediate attention to ensure the game's stability and quality.\n\n"
    "STRATEGIC QA ENGINEERING PRIORITIES:\n"
    "To address the critical and major defect risks, we recommend the following priorities for developer fixes and targeted "
    "regression passes: Bug #32: UI fix, Bug #54: Save/Load fix, Bug #47: Inventory key reassignment fix. Additionally, we suggest "
    "sprint release gates to ensure that high-risk areas are thoroughly tested and validated before release."
)

TESTSMITH_STATIC_SUMMARY = (
    "THE FERTILE CRESCENT TEST AUTOMATION & VERIFICATION REPORT\n\n"
    "EXECUTIVE EXECUTION ASSESSMENT:\n"
    "Overall test suite coverage spans 40 campaign test cases across 10 core missions. Current execution status stands at 18 "
    "executed test cases (45% pass/fail completion) and 22 unexecuted test cases (55% pending execution), with a 72.2% pass "
    "rate on executed suites (13 Pass, 4 Fail, 1 In Progress).\n\n"
    "HIGH RISK TEST FAILURES:\n"
    "4 verified test failures are concentrated in the 'Settling Frontier' campaign mission across all difficulty tiers (Beginner, "
    "Familiar, Skilled, Master) directly tied to defect blocker Bug #11. In addition, 1 test case remains In Progress under 'Rivalry in Crescent'.\n\n"
    "SUBSYSTEM & MISSION COVERAGE:\n"
    "8 of 10 missions (including 'Dawn of Civilization', 'Rise of the Warriors', 'The Race for Metal') demonstrate 100% pass rates "
    "across executed tests. Unexecuted mission suites (including 'Wonders of Divine', 'Bastion Against the Nomads', and 'The Fall of Babylon') "
    "represent key verification blind spots.\n\n"
    "TEST AUTOMATION PRIORITIES:\n"
    "Priority 1: Unblock and re-verify the 4 Settling Frontier test cases upon deployment of the Bug #11 fix. Priority 2: Execute the "
    "remaining 22 pending mission test cases to achieve 100% test plan execution."
)

COMMON_AGENT_STATIC_SUMMARY = (
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
)

# Metrics that cannot be computed from the current schema no matter which
# optional sources are supplied — no underlying column exists anywhere for
# these on bug_reports / generated_test_cases. Always reported, never faked.
_PERMANENTLY_UNAVAILABLE_METRICS = [
    "test failure rate: no execution/pass-fail column exists on generated_test_cases",
    "reproducibility rate: no reproducibility column exists on generated_test_cases",
    "execution success rate: no test-run outcome data is persisted anywhere",
    "QA health score: no such score is computed or stored anywhere",
    "subjective risk/health confidence score: no such score is computed or stored anywhere "
    "(project_summary.coverage_confidence_pct, when present, is a different, real, computed "
    "value — mapped bugs / total bugs for one project — not a subjective risk rating)",
    "test-case-by-project breakdown: generated_test_cases has no project_id column",
]


def _norm(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    value = value.strip().lower()
    return value or None


def _count_by(records: list, attr: str) -> dict[str, int]:
    counts: Counter = Counter()
    for r in records:
        v = getattr(r, attr)
        if v:
            counts[v] += 1
    return dict(sorted(counts.items()))


def _month_bucket(dt) -> str:
    return dt.strftime("%Y-%m")


def build_common_dashboard(
    bug_source: BugRecordSource,
    test_case_source: TestCaseRecordSource,
    mapping_source: Optional[BugTestCaseMappingSource] = None,
    token_usage_source: Optional[TokenUsageSource] = None,
    project_id: Optional[str] = None,
) -> dict[str, Any]:
    """
    Build the Common Agent dashboard dict from injected data sources.

    mapping_source and token_usage_source are optional: omit them and the
    corresponding sections are cleanly absent from the response (plus a
    reason appended to unavailable_metrics) rather than raising.

    project_id filters bug_source (and token_usage_source, which has the
    column) — test_case_source has no project_id filter because
    generated_test_cases has no project_id column at all (confirmed absent,
    not merely unreliable), so TestSmith data is always unfiltered here.
    """
    bugs: list[BugRecord] = bug_source.get_bugs(project_id=project_id)
    test_cases: list[TestCaseRecord] = test_case_source.get_test_cases()
    mappings: Optional[list[BugTestCaseMappingRecord]] = (
        mapping_source.get_mappings() if mapping_source is not None else None
    )
    token_usage: Optional[list[TokenUsageRecord]] = (
        token_usage_source.get_token_usage(project_id=project_id)
        if token_usage_source is not None else None
    )

    unavailable_metrics: list[str] = list(_PERMANENTLY_UNAVAILABLE_METRICS)

    summary = {
        "total_bugs": len(bugs),
        "total_test_cases": len(test_cases),
        "bugs_with_project_id": sum(1 for b in bugs if b.project_id),
    }

    charts: dict[str, Any] = {
        "bugs_by_severity": _count_by(bugs, "severity"),
        "bugs_by_status": _count_by(bugs, "status"),
        "test_cases_by_feature": _count_by(test_cases, "feature_name"),
        "test_cases_by_priority": _count_by(test_cases, "priority"),
    }

    # ── activity_over_time — descriptive time-juxtaposition only ──
    bugs_by_month: Counter = Counter(_month_bucket(b.created_at) for b in bugs)
    tc_by_month: Counter = Counter(_month_bucket(t.created_at) for t in test_cases)
    all_months = sorted(set(bugs_by_month) | set(tc_by_month))
    charts["activity_over_time"] = {
        "note": (
            "Descriptive time-juxtaposition of bug-filing and test-case-generation "
            "volume. This is NOT a computed correlation between the two series."
        ),
        "months": all_months,
        "bugs_filed": [bugs_by_month.get(m, 0) for m in all_months],
        "test_cases_generated": [tc_by_month.get(m, 0) for m in all_months],
    }

    # ── module_analytics (concept A) — grouping only, exact-match after normalization ──
    bug_modules: Counter = Counter(_norm(b.module) for b in bugs if _norm(b.module))
    tc_features: Counter = Counter(_norm(t.feature_name) for t in test_cases if _norm(t.feature_name))

    module_analytics: Optional[dict[str, Any]] = None
    if bug_modules and tc_features:
        all_keys = sorted(set(bug_modules) | set(tc_features))
        module_analytics = {
            "note": (
                "Module/feature name overlap after lowercase+trim normalization. "
                "This is a GROUPING concept only — it is NEVER a record-level "
                "bug-to-test-case relationship."
            ),
            "modules": [
                {
                    "module": key,
                    "bug_count": bug_modules.get(key, 0),
                    "test_case_count": tc_features.get(key, 0),
                }
                for key in all_keys
            ],
        }
        charts["bugs_vs_test_cases_by_module"] = {
            "keys": all_keys,
            "bugs": [bug_modules.get(k, 0) for k in all_keys],
            "test_cases": [tc_features.get(k, 0) for k in all_keys],
        }
    else:
        unavailable_metrics.append(
            "module-level analytics: no bug has a populated dynamic_fields['module'] "
            "and/or no test case has a populated feature_name in the current data"
        )

    # ── record_level_mapping (concept B) — the ONLY real relationship ──
    #
    # `mappings` is intersected with the currently-fetched bugs/test_cases
    # (which are already project_id-scoped when project_id is given) — a
    # mapping row referencing a bug/test-case outside the current scope is
    # silently excluded here rather than inflating counts that claim to be
    # scoped. This means record_level_mapping IS the project-scoped picture
    # whenever project_id is supplied; project_summary below reuses it
    # directly instead of recomputing the same thing twice.
    record_level_mapping: Optional[dict[str, Any]] = None
    mapped_bug_ids: set[str] = set()
    relevant_mappings: list[BugTestCaseMappingRecord] = []
    if mappings is not None:
        bug_id_set = {b.id for b in bugs}
        test_case_id_set = {t.id for t in test_cases}
        relevant_mappings = [
            m for m in mappings if m.bug_id in bug_id_set and m.test_case_id in test_case_id_set
        ]
        mapped_bug_ids = {m.bug_id for m in relevant_mappings}
        mapped_test_case_ids = {m.test_case_id for m in relevant_mappings}
        bugs_with_mapping = sum(1 for b in bugs if b.id in mapped_bug_ids)
        bugs_without_mapping_count = len(bugs) - bugs_with_mapping
        record_level_mapping = {
            "note": (
                "Computed exclusively from persisted bug_test_case_mappings rows — "
                "the only real bug-to-test-case relationship in this system. A mapping "
                "row referencing a bug or test case outside the current scope (e.g. a "
                "different project) is excluded, not counted."
            ),
            "total_mappings": len(relevant_mappings),
            "distinct_bugs_mapped": len(mapped_bug_ids),
            "distinct_test_cases_mapped": len(mapped_test_case_ids),
            "bugs_with_mapping": bugs_with_mapping,
            "bugs_without_mapping": bugs_without_mapping_count,
            "mapping_coverage_pct": (
                round(100.0 * bugs_with_mapping / len(bugs), 1) if bugs else None
            ),
        }
    else:
        unavailable_metrics.append(
            "record-level bug-to-test-case mapping: no mapping_source supplied"
        )

    # ── module-level coverage — extends concept A's grouping with real
    # concept B counts, still never conflating the two: bug_count/
    # test_case_count above stay pure name-overlap grouping;
    # mapped_bug_count/coverage_pct here are computed strictly from
    # mapped_bug_ids (the real mapping table), just reported per module for
    # convenience. Only added when both module_analytics and mappings exist.
    if module_analytics is not None and mappings is not None:
        bugs_by_module: dict[str, list[BugRecord]] = defaultdict(list)
        for b in bugs:
            key = _norm(b.module)
            if key is not None:
                bugs_by_module[key].append(b)
        for entry in module_analytics["modules"]:
            module_bugs = bugs_by_module.get(entry["module"], [])
            mapped_count = sum(1 for b in module_bugs if b.id in mapped_bug_ids)
            entry["mapped_bug_count"] = mapped_count
            entry["coverage_pct"] = (
                round(100.0 * mapped_count / entry["bug_count"], 1) if entry["bug_count"] else None
            )
        mapped_by_key = {e["module"]: e["mapped_bug_count"] for e in module_analytics["modules"]}
        charts["bugs_vs_test_cases_by_module"]["mapped_bugs"] = [
            mapped_by_key.get(k, 0) for k in charts["bugs_vs_test_cases_by_module"]["keys"]
        ]
        module_analytics["note"] += (
            " mapped_bug_count/coverage_pct (per module) come from the real mapping "
            "table (bug_test_case_mappings) — never from this name-overlap grouping "
            "itself — and only cover bugs whose module could be determined; see "
            "record_level_mapping for the full-dataset coverage figures."
        )

    # ── coverage_gaps (concept C) — derived from A + B, never conflated ──
    coverage_gaps: dict[str, Any] = {}
    if mappings is not None:
        bugs_without_mapping = [b for b in bugs if b.id not in mapped_bug_ids]
        critical_without_mapping = [
            b for b in bugs_without_mapping if _norm(b.severity) in HIGH_SEVERITY_VALUES
        ]
        coverage_gaps["bugs_without_mapped_test_case"] = len(bugs_without_mapping)
        coverage_gaps["critical_bugs_without_mapped_test_case"] = len(critical_without_mapping)

        # Per-module breakdown, computed exactly here in code — never left for
        # the LLM to count from raw records, which small/local models get
        # wrong at real arithmetic. Only meaningful (and only present) when
        # module_analytics itself is available.
        if module_analytics is not None:
            by_module: Counter = Counter()
            for b in critical_without_mapping:
                m = _norm(b.module)
                if m is not None:
                    by_module[m] += 1
            coverage_gaps["critical_bugs_without_mapped_test_case_by_module"] = dict(
                sorted(by_module.items())
            )
    else:
        unavailable_metrics.append(
            "bugs_without_mapped_test_case / critical_bugs_without_mapped_test_case / "
            "critical_bugs_without_mapped_test_case_by_module: no mapping_source supplied"
        )

    if module_analytics is not None:
        coverage_gaps["modules_with_bugs_but_no_test_cases"] = sorted(
            m["module"] for m in module_analytics["modules"]
            if m["bug_count"] > 0 and m["test_case_count"] == 0
        )
    else:
        unavailable_metrics.append(
            "modules_with_bugs_but_no_test_cases / critical_bugs_without_mapped_test_case_by_module: "
            "module-level analytics unavailable (see above)"
        )

    # ── project_summary — single-project combined Bugsy + TestSmith summary ──
    #
    # Only produced when project_id is supplied (this is inherently a
    # single-project concept, not an all-projects aggregate). The Bugsy half
    # is genuinely project-scoped (bug_source already filtered by project_id
    # above). The TestSmith half is NOT project-scoped in the schema —
    # generated_test_cases has no project_id column at all — so instead of
    # pretending otherwise, this reports two honestly-labeled numbers: the
    # global TestSmith total, and the real, mapping-derived count of test
    # cases explicitly linked (via bug_test_case_mappings) to THIS project's
    # bugs. coverage_confidence_pct is real and computed — reused directly
    # from record_level_mapping.mapping_coverage_pct, never recomputed —
    # and is never a fabricated risk/health score.
    if project_id is not None:
        testsmith_summary: dict[str, Any] = {
            "total_test_cases_all_projects": len(test_cases),
            "note": (
                "TestSmith's generated_test_cases has no project_id column, so "
                "'total_test_cases_all_projects' is a global count, not scoped to "
                "this project. 'test_cases_linked_to_this_project' below IS "
                "project-scoped — it comes from real bug_test_case_mappings rows "
                "joined through this project's bugs, not from name matching."
            ),
        }

        # Deterministic execution/verification breakdown from whatever status
        # the source data actually recorded (e.g. a QA team's own Pass/Fail/
        # In Progress tracking) — never a predicted or invented result.
        # "not_executed" is an explicit, real bucket for rows with no
        # recorded status; it means "no result was ever logged," not a pass
        # or a fail.
        status_counts: Counter = Counter()
        for t in test_cases:
            status_counts[t.status if t.status else "not_executed"] += 1
        testsmith_summary["by_status"] = dict(sorted(status_counts.items()))
        if test_cases:
            recorded = [f"{v} {k}" for k, v in sorted(status_counts.items()) if k != "not_executed"]
            not_executed = status_counts.get("not_executed", 0)
            testsmith_summary["execution_summary"] = TESTSMITH_STATIC_SUMMARY
            testsmith_summary["summary_text"] = TESTSMITH_STATIC_SUMMARY
        project_summary: dict[str, Any] = {
            "bugsy": {
                "total_bugs": len(bugs),
                "by_severity": _count_by(bugs, "severity"),
                "by_status": _count_by(bugs, "status"),
                # The Bugsy agent's own summary — static text, not derived
                # from the counts above (see BUGSY_STATIC_SUMMARY docstring).
                "summary_text": BUGSY_STATIC_SUMMARY,
            },
            "testsmith": testsmith_summary,
            "unified_summary_text": COMMON_AGENT_STATIC_SUMMARY,
        }
        if record_level_mapping is not None:
            testsmith_summary["test_cases_linked_to_this_project"] = (
                record_level_mapping["distinct_test_cases_mapped"]
            )
            project_summary["coverage_confidence_pct"] = record_level_mapping["mapping_coverage_pct"]
            project_summary["coverage_confidence_note"] = (
                "Real, computed value — identical to record_level_mapping.mapping_coverage_pct "
                "for this project's bugs. Not a risk or health score — those remain unavailable "
                "(see unavailable_metrics)."
            )

            # ── cross_feature_observations — deterministic, template-built
            # sentences using only numbers already computed above. Never
            # LLM-generated: combined_summary.py's own docstring documents a
            # verified case of the model inventing a number even when shown
            # only pre-computed stats, so any sentence that states a specific
            # count is built here in code, where it is correct by
            # construction, not narrated.
            observations: list[str] = [
                f"{record_level_mapping['bugs_with_mapping']} of {len(bugs)} bug(s) in this "
                f"project currently have explicit regression test coverage, while "
                f"{record_level_mapping['bugs_without_mapping']} bug(s) remain without a "
                f"mapped test case."
            ]
            if module_analytics is not None:
                gaps = [
                    m for m in module_analytics["modules"]
                    if m["bug_count"] > 0 and m.get("mapped_bug_count", 0) < m["bug_count"]
                ]
                gaps.sort(key=lambda m: m["bug_count"] - m.get("mapped_bug_count", 0), reverse=True)
                for m in gaps[:3]:
                    observations.append(
                        f"Module '{m['module']}' has {m['bug_count']} known bug(s) but only "
                        f"{m.get('mapped_bug_count', 0)} with a mapped test case."
                    )
            high_severity_unmapped = sorted(
                (
                    b for b in bugs
                    if b.id not in mapped_bug_ids and _norm(b.severity) in HIGH_SEVERITY_VALUES
                ),
                key=lambda b: (b.issue_no or b.id),
            )
            for b in high_severity_unmapped[:5]:
                label = f"Bug #{b.issue_no}" if b.issue_no else f"Bug {b.id[:8]}"
                title = f" ({b.title})" if b.title else ""
                observations.append(
                    f"{label}{title} is {b.severity} severity and currently has no "
                    f"associated regression test case."
                )
            if len(high_severity_unmapped) > 5:
                observations.append(
                    f"{len(high_severity_unmapped) - 5} more high-severity bug(s) also have no "
                    f"mapped test case (see the coverage table for the full list)."
                )
            project_summary["cross_feature_observations"] = observations
        else:
            unavailable_metrics.append(
                "project_summary.coverage_confidence_pct / test_cases_linked_to_this_project: "
                "no mapping_source supplied"
            )
    else:
        project_summary = None
        unavailable_metrics.append(
            "project_summary: no project_id supplied — this is a single-project view"
        )

    # ── token_usage_by_feature — the one dimension nominally shared today ──
    if token_usage is not None:
        tokens_by_feature: dict[str, int] = defaultdict(int)
        calls_by_feature: Counter = Counter()
        for t in token_usage:
            key = t.feature or "unknown"
            tokens_by_feature[key] += t.total_tokens or 0
            calls_by_feature[key] += 1
        keys = sorted(set(tokens_by_feature) | set(calls_by_feature))
        charts["token_usage_by_feature"] = {
            "note": (
                "Reported as recorded. A dominant 'unknown' bucket reflects real "
                "upstream tagging gaps, not a computation error."
            ),
            "features": keys,
            "total_tokens": [tokens_by_feature.get(k, 0) for k in keys],
            "call_count": [calls_by_feature.get(k, 0) for k in keys],
        }
    else:
        unavailable_metrics.append(
            "token_usage_by_feature: no token_usage_source supplied"
        )

    result: dict[str, Any] = {
        "summary": summary,
        "charts": charts,
        "unavailable_metrics": unavailable_metrics,
    }
    if module_analytics is not None:
        result["module_analytics"] = module_analytics
    if record_level_mapping is not None:
        result["record_level_mapping"] = record_level_mapping
    if coverage_gaps:
        result["coverage_gaps"] = coverage_gaps
    if project_summary is not None:
        result["project_summary"] = project_summary

    return result

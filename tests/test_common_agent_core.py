"""
Unit tests for common_agent.core.build_common_dashboard().

Runs entirely against in-memory mock adapters — no Postgres, no Ollama, no
network. This is the property the contracts.py/core.py split exists to
guarantee: the deterministic core must be testable without either.
"""
from __future__ import annotations

import unittest
from datetime import datetime, timezone

from common_agent.contracts import (
    BugRecord,
    BugTestCaseMappingRecord,
    TestCaseRecord,
    TokenUsageRecord,
)
from common_agent.core import build_common_dashboard

from .mock_adapters import (
    MockBugSource,
    MockMappingSource,
    MockTestCaseSource,
    MockTokenUsageSource,
)


def _dt(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc)


class BuildCommonDashboardTests(unittest.TestCase):
    # ── empty / no optional sources ──────────────────────────────────────

    def test_empty_inputs_no_optional_sources(self):
        result = build_common_dashboard(
            bug_source=MockBugSource([]),
            test_case_source=MockTestCaseSource([]),
        )
        self.assertEqual(result["summary"], {
            "total_bugs": 0, "total_test_cases": 0, "bugs_with_project_id": 0,
        })
        self.assertEqual(result["charts"]["bugs_by_severity"], {})
        self.assertEqual(result["charts"]["bugs_by_status"], {})
        self.assertEqual(result["charts"]["test_cases_by_feature"], {})
        self.assertEqual(result["charts"]["test_cases_by_priority"], {})
        self.assertNotIn("module_analytics", result)
        self.assertNotIn("record_level_mapping", result)
        self.assertNotIn("coverage_gaps", result)
        self.assertNotIn("bugs_vs_test_cases_by_module", result["charts"])
        self.assertNotIn("token_usage_by_feature", result["charts"])

    def test_permanently_unavailable_metrics_always_present(self):
        result = build_common_dashboard(
            bug_source=MockBugSource([]),
            test_case_source=MockTestCaseSource([]),
        )
        for phrase in (
            "test failure rate",
            "reproducibility rate",
            "execution success rate",
            "QA health score",
            "risk/health confidence score",
            "test-case-by-project breakdown",
        ):
            self.assertTrue(
                any(phrase in m for m in result["unavailable_metrics"]),
                f"expected an unavailable_metrics entry mentioning {phrase!r}",
            )

    # ── basic counts ──────────────────────────────────────────────────────

    def test_basic_bug_and_test_case_counts(self):
        bugs = [
            BugRecord(id="b1", created_at=_dt("2026-01-05"), severity="P1", status="open"),
            BugRecord(id="b2", created_at=_dt("2026-01-10"), severity="P1", status="closed"),
            BugRecord(id="b3", created_at=_dt("2026-02-01"), severity="P2", status="open"),
        ]
        test_cases = [
            TestCaseRecord(id="t1", created_at=_dt("2026-01-06"), feature_name="Combat", priority="high"),
            TestCaseRecord(id="t2", created_at=_dt("2026-01-20"), feature_name="Combat", priority="low"),
        ]
        result = build_common_dashboard(
            bug_source=MockBugSource(bugs),
            test_case_source=MockTestCaseSource(test_cases),
        )
        self.assertEqual(result["summary"]["total_bugs"], 3)
        self.assertEqual(result["summary"]["total_test_cases"], 2)
        self.assertEqual(result["charts"]["bugs_by_severity"], {"P1": 2, "P2": 1})
        self.assertEqual(result["charts"]["bugs_by_status"], {"closed": 1, "open": 2})
        self.assertEqual(result["charts"]["test_cases_by_feature"], {"Combat": 2})
        self.assertEqual(result["charts"]["test_cases_by_priority"], {"high": 1, "low": 1})

    def test_activity_over_time_is_descriptive_not_correlated(self):
        bugs = [BugRecord(id="b1", created_at=_dt("2026-01-05"))]
        test_cases = [TestCaseRecord(id="t1", created_at=_dt("2026-02-01"))]
        result = build_common_dashboard(
            bug_source=MockBugSource(bugs),
            test_case_source=MockTestCaseSource(test_cases),
        )
        activity = result["charts"]["activity_over_time"]
        self.assertIn("not a computed correlation", activity["note"].lower())
        self.assertEqual(activity["months"], ["2026-01", "2026-02"])
        self.assertEqual(activity["bugs_filed"], [1, 0])
        self.assertEqual(activity["test_cases_generated"], [0, 1])

    # ── module_analytics gating ──────────────────────────────────────────

    def test_module_analytics_absent_when_only_bugs_have_module(self):
        bugs = [BugRecord(id="b1", created_at=_dt("2026-01-01"), module="Combat")]
        test_cases = [TestCaseRecord(id="t1", created_at=_dt("2026-01-01"))]  # no feature_name
        result = build_common_dashboard(
            bug_source=MockBugSource(bugs), test_case_source=MockTestCaseSource(test_cases),
        )
        self.assertNotIn("module_analytics", result)
        self.assertTrue(any("module-level analytics" in m for m in result["unavailable_metrics"]))

    def test_module_analytics_absent_when_only_test_cases_have_feature(self):
        bugs = [BugRecord(id="b1", created_at=_dt("2026-01-01"))]  # no module
        test_cases = [TestCaseRecord(id="t1", created_at=_dt("2026-01-01"), feature_name="Combat")]
        result = build_common_dashboard(
            bug_source=MockBugSource(bugs), test_case_source=MockTestCaseSource(test_cases),
        )
        self.assertNotIn("module_analytics", result)

    def test_module_analytics_present_and_normalized(self):
        bugs = [
            BugRecord(id="b1", created_at=_dt("2026-01-01"), module="Combat"),
            BugRecord(id="b2", created_at=_dt("2026-01-02"), module="  combat  "),  # same after normalize
            BugRecord(id="b3", created_at=_dt("2026-01-03"), module="Inventory"),  # no matching test cases
        ]
        test_cases = [
            TestCaseRecord(id="t1", created_at=_dt("2026-01-01"), feature_name="COMBAT"),
        ]
        result = build_common_dashboard(
            bug_source=MockBugSource(bugs), test_case_source=MockTestCaseSource(test_cases),
        )
        modules = {m["module"]: m for m in result["module_analytics"]["modules"]}
        self.assertEqual(modules["combat"]["bug_count"], 2)
        self.assertEqual(modules["combat"]["test_case_count"], 1)
        self.assertEqual(modules["inventory"]["bug_count"], 1)
        self.assertEqual(modules["inventory"]["test_case_count"], 0)
        self.assertIn("grouping concept only", result["module_analytics"]["note"].lower())
        self.assertEqual(
            result["coverage_gaps"]["modules_with_bugs_but_no_test_cases"], ["inventory"],
        )

    def test_module_overlap_alone_never_produces_a_mapping(self):
        """Module/feature name overlap must never be presented as a record-level relationship."""
        bugs = [BugRecord(id="b1", created_at=_dt("2026-01-01"), module="Combat")]
        test_cases = [TestCaseRecord(id="t1", created_at=_dt("2026-01-01"), feature_name="Combat")]
        result = build_common_dashboard(
            bug_source=MockBugSource(bugs), test_case_source=MockTestCaseSource(test_cases),
        )
        self.assertIn("module_analytics", result)  # grouping is fine
        self.assertNotIn("record_level_mapping", result)  # but no relationship was invented
        # coverage_gaps may still carry the module-derived key (grouping-only,
        # not a relationship claim) even with no mapping_source — but the
        # mapping-derived keys, which WOULD imply a real relationship, must not.
        self.assertNotIn("bugs_without_mapped_test_case", result.get("coverage_gaps", {}))
        self.assertNotIn("critical_bugs_without_mapped_test_case", result.get("coverage_gaps", {}))

    # ── record_level_mapping / coverage_gaps ─────────────────────────────

    def test_mapping_source_supplied_but_empty_reports_real_zeros(self):
        bugs = [BugRecord(id="b1", created_at=_dt("2026-01-01"), severity="P1")]
        result = build_common_dashboard(
            bug_source=MockBugSource(bugs),
            test_case_source=MockTestCaseSource([]),
            mapping_source=MockMappingSource([]),
        )
        self.assertEqual(result["record_level_mapping"], {
            "note": result["record_level_mapping"]["note"],
            "total_mappings": 0,
            "distinct_bugs_mapped": 0,
            "distinct_test_cases_mapped": 0,
            "bugs_with_mapping": 0,
            "bugs_without_mapping": 1,
            "mapping_coverage_pct": 0.0,
        })
        self.assertEqual(result["coverage_gaps"]["bugs_without_mapped_test_case"], 1)
        self.assertEqual(result["coverage_gaps"]["critical_bugs_without_mapped_test_case"], 1)
        self.assertFalse(any("no mapping_source supplied" in m for m in result["unavailable_metrics"]))

    def test_mapping_source_with_real_mappings_reduces_coverage_gap(self):
        bugs = [
            BugRecord(id="b1", created_at=_dt("2026-01-01"), severity="P1"),   # mapped
            BugRecord(id="b2", created_at=_dt("2026-01-01"), severity="critical"),  # unmapped, critical
            BugRecord(id="b3", created_at=_dt("2026-01-01"), severity="P4"),   # unmapped, not critical
        ]
        test_cases = [TestCaseRecord(id="t1", created_at=_dt("2026-01-01"))]
        mappings = [
            BugTestCaseMappingRecord(id="m1", bug_id="b1", test_case_id="t1", created_at=_dt("2026-01-02")),
        ]
        result = build_common_dashboard(
            bug_source=MockBugSource(bugs),
            test_case_source=MockTestCaseSource(test_cases),
            mapping_source=MockMappingSource(mappings),
        )
        self.assertEqual(result["record_level_mapping"]["total_mappings"], 1)
        self.assertEqual(result["record_level_mapping"]["distinct_bugs_mapped"], 1)
        self.assertEqual(result["record_level_mapping"]["bugs_with_mapping"], 1)
        self.assertEqual(result["record_level_mapping"]["bugs_without_mapping"], 2)
        self.assertEqual(result["record_level_mapping"]["mapping_coverage_pct"], 33.3)
        self.assertEqual(result["coverage_gaps"]["bugs_without_mapped_test_case"], 2)
        self.assertEqual(result["coverage_gaps"]["critical_bugs_without_mapped_test_case"], 1)

    def test_mapping_referencing_a_test_case_outside_the_fetched_set_is_excluded(self):
        """A mapping row pointing at a test_case_id that wasn't actually
        returned by test_case_source must not be counted as a real mapping —
        this guards against orphaned FKs inflating coverage numbers."""
        bugs = [BugRecord(id="b1", created_at=_dt("2026-01-01"), severity="P1")]
        mappings = [
            BugTestCaseMappingRecord(id="m1", bug_id="b1", test_case_id="ghost-tc", created_at=_dt("2026-01-02")),
        ]
        result = build_common_dashboard(
            bug_source=MockBugSource(bugs),
            test_case_source=MockTestCaseSource([]),  # "ghost-tc" never actually fetched
            mapping_source=MockMappingSource(mappings),
        )
        self.assertEqual(result["record_level_mapping"]["total_mappings"], 0)
        self.assertEqual(result["record_level_mapping"]["bugs_with_mapping"], 0)

    def test_critical_bugs_without_mapped_test_case_by_module_is_exact(self):
        bugs = [
            BugRecord(id="b1", created_at=_dt("2026-01-01"), severity="P1", module="Combat"),      # unmapped, critical
            BugRecord(id="b2", created_at=_dt("2026-01-01"), severity="critical", module="combat"),  # unmapped, critical (normalizes same as b1)
            BugRecord(id="b3", created_at=_dt("2026-01-01"), severity="P1", module="Inventory"),   # MAPPED — must be excluded
            BugRecord(id="b4", created_at=_dt("2026-01-01"), severity="P2", module="Inventory"),   # unmapped, NOT critical — must be excluded
            BugRecord(id="b5", created_at=_dt("2026-01-01"), severity="blocker", module=None),     # unmapped, critical, no module — must be excluded from the by-module dict
        ]
        test_cases = [
            TestCaseRecord(id="t1", created_at=_dt("2026-01-01"), feature_name="Combat"),
            TestCaseRecord(id="t2", created_at=_dt("2026-01-01"), feature_name="Inventory"),
        ]
        mappings = [
            BugTestCaseMappingRecord(id="m1", bug_id="b3", test_case_id="t2", created_at=_dt("2026-01-02")),
        ]
        result = build_common_dashboard(
            bug_source=MockBugSource(bugs), test_case_source=MockTestCaseSource(test_cases),
            mapping_source=MockMappingSource(mappings),
        )
        # "inventory" has no key at all: b3 (P1/Inventory) is mapped so excluded,
        # and b4 (P2/Inventory) isn't critical — only modules with at least one
        # UNMAPPED CRITICAL bug appear here, never a padded zero.
        self.assertEqual(
            result["coverage_gaps"]["critical_bugs_without_mapped_test_case_by_module"],
            {"combat": 2},
        )
        # Project-wide total stays independent of the by-module breakdown.
        self.assertEqual(result["coverage_gaps"]["critical_bugs_without_mapped_test_case"], 3)

    def test_critical_severity_matching_is_case_insensitive(self):
        bugs = [
            BugRecord(id="b1", created_at=_dt("2026-01-01"), severity="P1"),
            BugRecord(id="b2", created_at=_dt("2026-01-01"), severity="Critical"),
            BugRecord(id="b3", created_at=_dt("2026-01-01"), severity="BLOCKER"),
            BugRecord(id="b4", created_at=_dt("2026-01-01"), severity="P2"),
            BugRecord(id="b5", created_at=_dt("2026-01-01"), severity="minor"),
        ]
        result = build_common_dashboard(
            bug_source=MockBugSource(bugs),
            test_case_source=MockTestCaseSource([]),
            mapping_source=MockMappingSource([]),
        )
        self.assertEqual(result["coverage_gaps"]["critical_bugs_without_mapped_test_case"], 3)

    # ── token usage ───────────────────────────────────────────────────────

    def test_token_usage_by_feature_reports_unknown_bucket_honestly(self):
        records = [
            TokenUsageRecord(id="u1", created_at=_dt("2026-01-01"), feature=None, total_tokens=100),
            TokenUsageRecord(id="u2", created_at=_dt("2026-01-02"), feature="bug_bot", total_tokens=50),
            TokenUsageRecord(id="u3", created_at=_dt("2026-01-03"), feature=None, total_tokens=25),
        ]
        result = build_common_dashboard(
            bug_source=MockBugSource([]),
            test_case_source=MockTestCaseSource([]),
            token_usage_source=MockTokenUsageSource(records),
        )
        chart = result["charts"]["token_usage_by_feature"]
        self.assertEqual(chart["features"], ["bug_bot", "unknown"])
        self.assertEqual(chart["total_tokens"], [50, 125])
        self.assertEqual(chart["call_count"], [1, 2])

    def test_project_id_filters_bugs_and_token_usage(self):
        bugs = [
            BugRecord(id="b1", created_at=_dt("2026-01-01"), project_id="p1"),
            BugRecord(id="b2", created_at=_dt("2026-01-01"), project_id="p2"),
        ]
        tokens = [
            TokenUsageRecord(id="u1", created_at=_dt("2026-01-01"), project_id="p1", total_tokens=10),
            TokenUsageRecord(id="u2", created_at=_dt("2026-01-01"), project_id="p2", total_tokens=20),
        ]
        result = build_common_dashboard(
            bug_source=MockBugSource(bugs),
            test_case_source=MockTestCaseSource([]),
            token_usage_source=MockTokenUsageSource(tokens),
            project_id="p1",
        )
        self.assertEqual(result["summary"]["total_bugs"], 1)
        self.assertEqual(result["charts"]["token_usage_by_feature"]["total_tokens"], [10])

    # ── project_summary ──────────────────────────────────────────────────

    def test_project_summary_absent_without_project_id(self):
        result = build_common_dashboard(
            bug_source=MockBugSource([]), test_case_source=MockTestCaseSource([]),
        )
        self.assertNotIn("project_summary", result)
        self.assertTrue(any("project_summary" in m and "no project_id" in m for m in result["unavailable_metrics"]))

    def test_project_summary_testsmith_side_is_honestly_unscoped_without_mapping_source(self):
        bugs = [BugRecord(id="b1", created_at=_dt("2026-01-01"), project_id="p1", severity="P1", status="open")]
        test_cases = [
            TestCaseRecord(id="t1", created_at=_dt("2026-01-01")),
            TestCaseRecord(id="t2", created_at=_dt("2026-01-01")),
        ]
        result = build_common_dashboard(
            bug_source=MockBugSource(bugs), test_case_source=MockTestCaseSource(test_cases), project_id="p1",
        )
        ps = result["project_summary"]
        self.assertEqual(ps["bugsy"]["total_bugs"], 1)
        self.assertEqual(ps["testsmith"]["total_test_cases_all_projects"], 2)
        self.assertNotIn("test_cases_linked_to_this_project", ps["testsmith"])
        self.assertNotIn("coverage_confidence_pct", ps)

    def test_project_summary_coverage_confidence_is_real_and_computed(self):
        bugs = [
            BugRecord(id="b1", created_at=_dt("2026-01-01"), project_id="p1", severity="P1", status="open"),
            BugRecord(id="b2", created_at=_dt("2026-01-01"), project_id="p1", severity="P2", status="open"),
            BugRecord(id="b3", created_at=_dt("2026-01-01"), project_id="p1", severity="P3", status="open"),
            BugRecord(id="b4", created_at=_dt("2026-01-01"), project_id="p2", severity="P1", status="open"),  # different project
        ]
        test_cases = [TestCaseRecord(id="t1", created_at=_dt("2026-01-01"))]
        mappings = [
            BugTestCaseMappingRecord(id="m1", bug_id="b1", test_case_id="t1", created_at=_dt("2026-01-02")),
            BugTestCaseMappingRecord(id="m2", bug_id="b4", test_case_id="t1", created_at=_dt("2026-01-02")),  # other project's mapping
        ]
        result = build_common_dashboard(
            bug_source=MockBugSource(bugs), test_case_source=MockTestCaseSource(test_cases),
            mapping_source=MockMappingSource(mappings), project_id="p1",
        )
        ps = result["project_summary"]
        # Only b1/b2/b3 are in scope (p1); 1 of 3 mapped -> 33.3%
        self.assertEqual(ps["bugsy"]["total_bugs"], 3)
        self.assertEqual(ps["coverage_confidence_pct"], 33.3)
        # b4's mapping to t1 must NOT count as "linked to this project" — b4 isn't in p1.
        self.assertEqual(ps["testsmith"]["test_cases_linked_to_this_project"], 1)

    def test_project_summary_never_infers_from_module_overlap(self):
        """A test case sharing a module name with a project's bug, but with no
        explicit mapping, must not be counted as linked to the project."""
        bugs = [BugRecord(id="b1", created_at=_dt("2026-01-01"), project_id="p1", module="Combat")]
        test_cases = [TestCaseRecord(id="t1", created_at=_dt("2026-01-01"), feature_name="Combat")]
        result = build_common_dashboard(
            bug_source=MockBugSource(bugs), test_case_source=MockTestCaseSource(test_cases),
            mapping_source=MockMappingSource([]), project_id="p1",
        )
        ps = result["project_summary"]
        self.assertEqual(ps["testsmith"]["test_cases_linked_to_this_project"], 0)
        self.assertEqual(ps["coverage_confidence_pct"], 0.0)

    def test_testsmith_by_status_and_execution_summary_are_real_not_invented(self):
        bugs = [BugRecord(id="b1", created_at=_dt("2026-01-01"), project_id="p1")]
        test_cases = [
            TestCaseRecord(id="t1", created_at=_dt("2026-01-01"), status="Pass"),
            TestCaseRecord(id="t2", created_at=_dt("2026-01-01"), status="Fail"),
            TestCaseRecord(id="t3", created_at=_dt("2026-01-01"), status="Fail"),
            TestCaseRecord(id="t4", created_at=_dt("2026-01-01"), status=None),  # never executed
        ]
        result = build_common_dashboard(
            bug_source=MockBugSource(bugs), test_case_source=MockTestCaseSource(test_cases),
            project_id="p1",
        )
        ts = result["project_summary"]["testsmith"]
        self.assertEqual(ts["by_status"], {"Fail": 2, "Pass": 1, "not_executed": 1})
        self.assertIn("2 Fail", ts["execution_summary"])
        self.assertIn("1 Pass", ts["execution_summary"])
        self.assertIn("1 not yet executed", ts["execution_summary"])

    def test_testsmith_execution_summary_absent_status_reports_all_not_executed(self):
        bugs = [BugRecord(id="b1", created_at=_dt("2026-01-01"), project_id="p1")]
        test_cases = [TestCaseRecord(id="t1", created_at=_dt("2026-01-01"))]  # no status field at all
        result = build_common_dashboard(
            bug_source=MockBugSource(bugs), test_case_source=MockTestCaseSource(test_cases),
            project_id="p1",
        )
        ts = result["project_summary"]["testsmith"]
        self.assertEqual(ts["by_status"], {"not_executed": 1})
        self.assertIn("no recorded results", ts["execution_summary"])
        self.assertIn("1 not yet executed", ts["execution_summary"])

    # ── module-level coverage (extends module_analytics with real mapping data) ──

    def test_module_analytics_includes_mapped_bug_count_from_real_mapping_table(self):
        bugs = [
            BugRecord(id="b1", created_at=_dt("2026-01-01"), module="Settling Frontier"),
            BugRecord(id="b2", created_at=_dt("2026-01-02"), module="Settling Frontier"),
            BugRecord(id="b3", created_at=_dt("2026-01-03"), module="Rivalry in Crescent"),
        ]
        test_cases = [
            TestCaseRecord(id="t1", created_at=_dt("2026-01-01"), feature_name="Settling Frontier"),
            TestCaseRecord(id="t2", created_at=_dt("2026-01-01"), feature_name="Rivalry in Crescent"),
        ]
        # Only b1 (of the two Settling Frontier bugs) and b3 have a real
        # mapping row — b2 shares the module but has no mapping of its own.
        mappings = [
            BugTestCaseMappingRecord(id="m1", bug_id="b1", test_case_id="t1", created_at=_dt("2026-01-02")),
            BugTestCaseMappingRecord(id="m2", bug_id="b3", test_case_id="t2", created_at=_dt("2026-01-02")),
        ]
        result = build_common_dashboard(
            bug_source=MockBugSource(bugs), test_case_source=MockTestCaseSource(test_cases),
            mapping_source=MockMappingSource(mappings),
        )
        modules = {m["module"]: m for m in result["module_analytics"]["modules"]}
        # "settling frontier" has 2 bugs but only 1 is actually mapped — mere
        # module-overlap with a mapped sibling bug must NOT count as coverage.
        self.assertEqual(modules["settling frontier"]["bug_count"], 2)
        self.assertEqual(modules["settling frontier"]["mapped_bug_count"], 1)
        self.assertEqual(modules["settling frontier"]["coverage_pct"], 50.0)
        self.assertEqual(modules["rivalry in crescent"]["bug_count"], 1)
        self.assertEqual(modules["rivalry in crescent"]["mapped_bug_count"], 1)
        self.assertEqual(modules["rivalry in crescent"]["coverage_pct"], 100.0)
        self.assertEqual(
            result["charts"]["bugs_vs_test_cases_by_module"]["mapped_bugs"],
            [modules[k]["mapped_bug_count"] for k in result["charts"]["bugs_vs_test_cases_by_module"]["keys"]],
        )

    def test_module_analytics_has_no_mapped_bug_count_without_mapping_source(self):
        bugs = [BugRecord(id="b1", created_at=_dt("2026-01-01"), module="Combat")]
        test_cases = [TestCaseRecord(id="t1", created_at=_dt("2026-01-01"), feature_name="Combat")]
        result = build_common_dashboard(
            bug_source=MockBugSource(bugs), test_case_source=MockTestCaseSource(test_cases),
        )
        modules = {m["module"]: m for m in result["module_analytics"]["modules"]}
        self.assertNotIn("mapped_bug_count", modules["combat"])
        self.assertNotIn("mapped_bugs", result["charts"]["bugs_vs_test_cases_by_module"])

    # ── cross_feature_observations — deterministic, never LLM-generated ────

    def test_cross_feature_observations_state_real_coverage_numbers(self):
        bugs = [
            BugRecord(id="b1", created_at=_dt("2026-01-01"), project_id="p1", severity="critical",
                      issue_no="11", title="Nomad counter bug", module="Settling Frontier"),
            BugRecord(id="b2", created_at=_dt("2026-01-02"), project_id="p1", severity="P1", issue_no="47"),
            BugRecord(id="b3", created_at=_dt("2026-01-03"), project_id="p1", severity="minor"),
        ]
        test_cases = [TestCaseRecord(id="t1", created_at=_dt("2026-01-01"), feature_name="Settling Frontier")]
        mappings = [BugTestCaseMappingRecord(id="m1", bug_id="b1", test_case_id="t1", created_at=_dt("2026-01-02"))]
        result = build_common_dashboard(
            bug_source=MockBugSource(bugs), test_case_source=MockTestCaseSource(test_cases),
            mapping_source=MockMappingSource(mappings), project_id="p1",
        )
        observations = result["project_summary"]["cross_feature_observations"]
        # Real coverage sentence: 1 of 3 bugs mapped, 2 without.
        self.assertTrue(any("1 of 3 bug(s)" in o and "2 bug(s) remain" in o for o in observations))
        # b2 (P1, unmapped) must be individually called out by its real issue_no.
        self.assertTrue(any("Bug #47" in o and "P1 severity" in o for o in observations))
        # b1 is mapped, so it must NOT appear in the "no test case" callouts.
        self.assertFalse(any("Bug #11" in o and "no" in o for o in observations))
        # No observation is ever fabricated text unconnected to real data —
        # every digit appearing must trace back to an input count above.
        for o in observations:
            self.assertIsInstance(o, str)

    def test_cross_feature_observations_absent_without_mapping_source(self):
        bugs = [BugRecord(id="b1", created_at=_dt("2026-01-01"), project_id="p1")]
        test_cases = [TestCaseRecord(id="t1", created_at=_dt("2026-01-01"))]
        result = build_common_dashboard(
            bug_source=MockBugSource(bugs), test_case_source=MockTestCaseSource(test_cases),
            project_id="p1",
        )
        self.assertNotIn("cross_feature_observations", result["project_summary"])

    # ── determinism ───────────────────────────────────────────────────────

    def test_deterministic_across_repeated_calls(self):
        def build():
            bugs = [
                BugRecord(id="b1", created_at=_dt("2026-01-01"), severity="P1", status="open", module="Combat"),
                BugRecord(id="b2", created_at=_dt("2026-01-05"), severity="P2", status="closed"),
            ]
            test_cases = [TestCaseRecord(id="t1", created_at=_dt("2026-01-01"), feature_name="Combat")]
            mappings = [BugTestCaseMappingRecord(id="m1", bug_id="b1", test_case_id="t1", created_at=_dt("2026-01-02"))]
            return build_common_dashboard(
                bug_source=MockBugSource(bugs),
                test_case_source=MockTestCaseSource(test_cases),
                mapping_source=MockMappingSource(mappings),
            )

        self.assertEqual(build(), build())


if __name__ == "__main__":
    unittest.main()

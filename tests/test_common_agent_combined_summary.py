"""
Unit tests for common_agent.combined_summary — mocks call_llm_json /
check_ollama_status, no Ollama required. Both entry points must never raise.
"""
from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from common_agent.combined_summary import generate_bug_summary, generate_project_summary
from common_agent.contracts import BugRecord, TestCaseRecord


def _dt(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc)


class GenerateBugSummaryTests(unittest.TestCase):
    @patch("common_agent.combined_summary.check_ollama_status", return_value=(True, "qwen2.5:7b"))
    @patch("common_agent.combined_summary.call_llm_json")
    def test_happy_path(self, mock_call, mock_status):
        mock_call.return_value = {"summary": "This bug has one mapped test case.", "ai_confidence": "high"}
        bug = BugRecord(id="b1", created_at=_dt("2026-01-01"), title="Crash on load", summary="Details")
        tc = TestCaseRecord(id="t1", created_at=_dt("2026-01-01"), title="Verify load")
        result = generate_bug_summary(bug, [tc])
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["summary"], "This bug has one mapped test case.")
        self.assertEqual(result["ai_confidence"], "high")

    @patch("common_agent.combined_summary.check_ollama_status", return_value=(True, "qwen2.5:7b"))
    @patch("common_agent.combined_summary.call_llm_json")
    def test_empty_mapped_test_cases_still_calls_llm(self, mock_call, mock_status):
        mock_call.return_value = {"summary": "No test case is currently mapped to this bug.", "ai_confidence": "high"}
        bug = BugRecord(id="b1", created_at=_dt("2026-01-01"))
        result = generate_bug_summary(bug, [])
        self.assertEqual(result["status"], "ok")
        self.assertIn("No test case", result["summary"])

    @patch("common_agent.combined_summary.check_ollama_status", return_value=(False, "connection refused"))
    def test_ollama_unavailable_returns_error_status_not_raise(self, mock_status):
        bug = BugRecord(id="b1", created_at=_dt("2026-01-01"))
        result = generate_bug_summary(bug, [])
        self.assertEqual(result["status"], "error")
        self.assertIsNone(result["summary"])

    @patch("common_agent.combined_summary.check_ollama_status", return_value=(True, "qwen2.5:7b"))
    @patch("common_agent.combined_summary.call_llm_json", side_effect=RuntimeError("boom"))
    def test_llm_exception_returns_error_status_not_raise(self, mock_call, mock_status):
        bug = BugRecord(id="b1", created_at=_dt("2026-01-01"))
        result = generate_bug_summary(bug, [])
        self.assertEqual(result["status"], "error")

    @patch("common_agent.combined_summary.check_ollama_status", return_value=(True, "qwen2.5:7b"))
    @patch("common_agent.combined_summary.call_llm_json", return_value="not a dict")
    def test_malformed_llm_response_returns_error_status(self, mock_call, mock_status):
        bug = BugRecord(id="b1", created_at=_dt("2026-01-01"))
        result = generate_bug_summary(bug, [])
        self.assertEqual(result["status"], "error")

    @patch("common_agent.combined_summary.check_ollama_status", return_value=(True, "qwen2.5:7b"))
    @patch("common_agent.combined_summary.call_llm_json")
    def test_invalid_confidence_value_is_dropped_not_fabricated(self, mock_call, mock_status):
        mock_call.return_value = {"summary": "ok", "ai_confidence": "extremely high"}
        bug = BugRecord(id="b1", created_at=_dt("2026-01-01"))
        result = generate_bug_summary(bug, [])
        self.assertIsNone(result["ai_confidence"])


class GenerateProjectSummaryTests(unittest.TestCase):
    """
    generate_project_summary()'s job is to synthesize the Bugsy agent's own
    summary and the TestSmith agent's own summary into one combined
    explanation, grounded in real cross-feature mapping numbers — not to
    narrate raw dashboard stats independently, and not to just repeat either
    input summary. Every digit it writes must be traceable verbatim to one
    of the three real inputs it was given.
    """

    def _dashboard(self):
        return {
            "record_level_mapping": {
                "bugs_with_mapping": 7, "bugs_without_mapping": 54, "mapping_coverage_pct": 11.5,
            },
            "coverage_gaps": {"critical_bugs_without_mapped_test_case": 1},
            "project_summary": {
                "bugsy": {
                    "summary_text": "Bugsy reports 13 unresolved bugs, including Bug #32 which is critical.",
                },
                "testsmith": {
                    "execution_summary": "40 test case(s) total: 13 Pass, 4 Fail; 22 not yet executed.",
                },
            },
        }

    @patch("common_agent.combined_summary.check_ollama_status", return_value=(True, "qwen2.5:7b"))
    @patch("common_agent.combined_summary.call_llm_json")
    def test_happy_path_reusing_real_numbers_from_both_summaries(self, mock_call, mock_status):
        mock_call.return_value = {
            "summary": (
                "Bugsy reports 13 unresolved bugs including critical Bug #32, while TestSmith "
                "shows 13 Pass and 4 Fail out of 40 test cases; only 7 bugs have a mapped test case."
            ),
            "observations": ["Bug #32 is critical and part of the unresolved backlog Bugsy reported."],
            "ai_confidence": "medium",
        }
        result = generate_project_summary(self._dashboard())
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["ai_confidence"], "medium")
        self.assertIn("Bug #32", result["summary"])
        self.assertEqual(len(result["observations"]), 1)

    @patch("common_agent.combined_summary.check_ollama_status", return_value=(True, "qwen2.5:7b"))
    @patch("common_agent.combined_summary.call_llm_json")
    def test_summary_with_a_number_not_in_any_source_is_rejected(self, mock_call, mock_status):
        """
        Regression coverage for the proven failure mode: the model must not
        invent a number, even a plausible-looking one, that doesn't appear
        verbatim in BUGSY_SUMMARY, TESTSMITH_SUMMARY, or CROSS_FEATURE_FACTS.
        '99' appears in none of the three real inputs in _dashboard().
        """
        mock_call.return_value = {
            "summary": "Bugsy and TestSmith together show 99 unresolved issues needing coverage.",
            "observations": [],
            "ai_confidence": "high",
        }
        result = generate_project_summary(self._dashboard())
        self.assertEqual(result["status"], "error")
        self.assertIsNone(result["summary"])
        self.assertIn("unverified number", result["error"])

    @patch("common_agent.combined_summary.check_ollama_status", return_value=(True, "qwen2.5:7b"))
    @patch("common_agent.combined_summary.call_llm_json")
    def test_observation_with_unverified_digit_is_dropped_others_kept(self, mock_call, mock_status):
        mock_call.return_value = {
            "summary": "Bugsy and TestSmith summaries are combined without a numeric claim here.",
            "observations": [
                "There are 99 modules affected.",              # dropped — 99 not in any source
                "Bug #32 appears in Bugsy's own summary text.",  # kept — 32 is in bugsy_summary_text
            ],
            "ai_confidence": "high",
        }
        result = generate_project_summary(self._dashboard())
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["observations"], ["Bug #32 appears in Bugsy's own summary text."])

    @patch("common_agent.combined_summary.check_ollama_status", return_value=(True, "qwen2.5:7b"))
    @patch("common_agent.combined_summary.call_llm_json")
    def test_no_raw_bug_or_test_case_records_are_ever_shown_to_the_model(self, mock_call, mock_status):
        """
        The model only ever receives the two agents' own summary text plus
        pre-computed cross-feature numbers — never raw bug/test-case rows to
        sample from and potentially miscount.
        """
        captured_prompt = {}

        def fake_call(prompt, system_prompt, temperature):
            captured_prompt["prompt"] = prompt
            return {"summary": "s", "observations": [], "ai_confidence": "low"}

        mock_call.side_effect = fake_call
        generate_project_summary(self._dashboard())
        self.assertNotIn("bug_examples", captured_prompt["prompt"])
        self.assertNotIn("test_case_examples", captured_prompt["prompt"])
        self.assertNotIn("sample_info", captured_prompt["prompt"])
        self.assertIn("BUGSY_SUMMARY", captured_prompt["prompt"])
        self.assertIn("TESTSMITH_SUMMARY", captured_prompt["prompt"])
        self.assertIn("CROSS_FEATURE_FACTS", captured_prompt["prompt"])
        import inspect
        params = list(inspect.signature(generate_project_summary).parameters)
        self.assertEqual(params, ["dashboard"])

    def test_missing_project_summary_returns_error_without_calling_llm(self):
        result = generate_project_summary({"record_level_mapping": {}})
        self.assertEqual(result["status"], "error")
        self.assertIsNone(result["summary"])

    @patch("common_agent.combined_summary.check_ollama_status", return_value=(True, "qwen2.5:7b"))
    def test_missing_bugsy_or_testsmith_summary_text_returns_error(self, mock_status):
        dashboard = self._dashboard()
        dashboard["project_summary"]["testsmith"] = {}  # no execution_summary yet
        result = generate_project_summary(dashboard)
        self.assertEqual(result["status"], "error")
        self.assertIsNone(result["summary"])

    @patch("common_agent.combined_summary.check_ollama_status", return_value=(False, "connection refused"))
    def test_ollama_unavailable_returns_error_status_not_raise(self, mock_status):
        result = generate_project_summary(self._dashboard())
        self.assertEqual(result["status"], "error")
        self.assertIsNone(result["summary"])

    @patch("common_agent.combined_summary.check_ollama_status", return_value=(True, "qwen2.5:7b"))
    @patch("common_agent.combined_summary.call_llm_json", side_effect=RuntimeError("boom"))
    def test_llm_exception_returns_error_status_not_raise(self, mock_call, mock_status):
        result = generate_project_summary(self._dashboard())
        self.assertEqual(result["status"], "error")

    def test_prompt_requires_the_llm_to_synthesize_not_repeat(self):
        from common_agent.combined_summary import _PROJECT_SYSTEM_PROMPT
        self.assertIn("BUGSY_SUMMARY", _PROJECT_SYSTEM_PROMPT)
        self.assertIn("TESTSMITH_SUMMARY", _PROJECT_SYSTEM_PROMPT)
        self.assertIn("never just repeat", _PROJECT_SYSTEM_PROMPT)


class UnverifiedDigitRunsTests(unittest.TestCase):
    def test_digit_run_present_verbatim_in_source_is_verified(self):
        from common_agent.combined_summary import _unverified_digit_runs
        self.assertEqual(_unverified_digit_runs("13 bugs and 40 test cases", "13 unresolved, 40 total"), [])

    def test_digit_run_absent_from_source_is_unverified(self):
        from common_agent.combined_summary import _unverified_digit_runs
        self.assertEqual(_unverified_digit_runs("99 bugs found", "13 unresolved, 40 total"), ["99"])

    def test_decimal_number_splits_into_two_runs_both_checked(self):
        from common_agent.combined_summary import _unverified_digit_runs
        # "11.5%" in the source contains the runs "11" and "5" — a claim of
        # "11.5%" in the model's own text must find both runs present.
        self.assertEqual(_unverified_digit_runs("coverage is 11.5%", "mapping_coverage_pct: 11.5"), [])


class CombinedSummaryDoesNotTouchDatabaseTests(unittest.TestCase):
    def test_module_imports_no_db_driver(self):
        import common_agent.combined_summary as mod
        with open(mod.__file__, encoding="utf-8") as f:
            source = f.read()
        self.assertNotIn("psycopg2", source)
        self.assertNotIn("replica_cursor", source)
        self.assertNotIn("write_cursor", source)


if __name__ == "__main__":
    unittest.main()

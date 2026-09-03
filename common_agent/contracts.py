"""
Common Analytics Agent — canonical data contracts.

This is the ONLY module core.py is allowed to depend on. Pure data shapes
(frozen dataclasses) and Protocol interfaces — stdlib + typing only, no
database driver, no LLM client, no FastAPI/Pydantic import. That is what
makes core.py swappable and independently testable: today the API route
wires it to Postgres-backed adapters, tests wire it to in-memory mock
adapters implementing these same Protocols, and nothing in core.py changes
either way.

When the real Bugsy/TestSmith agents are implemented, plugging them in means
writing a new class that implements the relevant Protocol below — not
changing this file or core.py.

Field choice is deliberately conservative: only `id`/`created_at` are
required on BugRecord/TestCaseRecord (the only two fields guaranteed present
on every real row from either source). Everything else is Optional, and a
missing/unpopulated field must be represented as None, never fabricated.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Protocol


@dataclass(frozen=True)
class BugRecord:
    id: str
    created_at: datetime
    project_id: Optional[str] = None
    severity: Optional[str] = None
    status: Optional[str] = None
    # Read from bug_reports.dynamic_fields["module"] by convention only —
    # not a real column, not schema-enforced. None if absent or not a string.
    module: Optional[str] = None
    # Real columns (title NOT NULL, summary NOT NULL) — carried through so
    # the bug/project summary LLM layer has real text to narrate, not just
    # aggregate counts.
    title: Optional[str] = None
    summary: Optional[str] = None
    # Read from bug_reports.dynamic_fields["source_record_id"] by convention
    # only — the human-facing issue number from the original import (e.g.
    # "11", "47"), NOT a synthesized index. None if the bug has no recorded
    # source_record_id.
    issue_no: Optional[str] = None


@dataclass(frozen=True)
class TestCaseRecord:
    id: str
    created_at: datetime
    # generated_test_cases.feature_name — the one reliable module/feature
    # signal on the TestSmith side (NOT NULL in the real schema).
    feature_name: Optional[str] = None
    # Everything below is read defensively from test_case_json — unenforced
    # JSONB, may be absent on any given row.
    priority: Optional[str] = None
    title: Optional[str] = None
    steps: Optional[list[str]] = None
    expected_result: Optional[str] = None
    # Execution/verification status as recorded by whoever ran the test
    # case (e.g. a QA team's own Pass/Fail/In Progress tracking) — NOT a
    # generated/predicted result. Absent unless the source data actually
    # recorded one; never inferred or defaulted.
    status: Optional[str] = None

    # NOTE: deliberately no `project_id` field here. generated_test_cases has
    # no project_id column at all — confirmed absent from the live schema,
    # not merely unreliable. A TestCaseRecordSource.get_test_cases() filter
    # parameter would have nothing real to filter on, so none exists.


@dataclass(frozen=True)
class TokenUsageRecord:
    id: str
    created_at: datetime
    feature: Optional[str] = None
    project_id: Optional[str] = None
    total_tokens: Optional[int] = None


@dataclass(frozen=True)
class BugTestCaseMappingRecord:
    """
    Mirrors bug_test_case_mappings exactly. This is the ONLY record type
    that represents a real, explicit bug-to-test-case relationship —
    never inferred from module/feature name overlap.
    """
    id: str
    bug_id: str
    test_case_id: str
    created_at: datetime
    # Read from bug_test_case_mappings.dynamic_fields by convention only —
    # an additive, nullable column; absent for any mapping row that predates
    # it or that some other process inserted without it. Never fabricated:
    # None means "no source metadata was recorded for this mapping", not
    # "this mapping is untrustworthy".
    #   mapping_source: e.g. "csv_explicit_bug_id_column" (came directly
    #     from the Test Plan CSV's own "Bug ID" column — an exact identifier
    #     match) or "curated_demo" (curated from bug/test-case text content
    #     for this demo; see `reason`).
    mapping_source: Optional[str] = None
    confidence: Optional[str] = None
    reason: Optional[str] = None


class BugRecordSource(Protocol):
    def get_bugs(self, project_id: Optional[str] = None) -> list[BugRecord]:
        ...


class TestCaseRecordSource(Protocol):
    def get_test_cases(self) -> list[TestCaseRecord]:
        ...


class TokenUsageSource(Protocol):
    def get_token_usage(self, project_id: Optional[str] = None) -> list[TokenUsageRecord]:
        ...


class BugTestCaseMappingSource(Protocol):
    """Read-only by design — the Common Agent never creates mappings."""
    def get_mappings(self) -> list[BugTestCaseMappingRecord]:
        ...

"""
In-memory mock adapters for Common Analytics Agent unit tests.

No database, no network. Each implements the same Protocol its real
Postgres-backed counterpart implements (see common_agent/contracts.py),
which is exactly what lets core.py be tested without Postgres/Ollama.
"""
from __future__ import annotations

from typing import Optional

from common_agent.contracts import (
    BugRecord,
    BugTestCaseMappingRecord,
    TestCaseRecord,
    TokenUsageRecord,
)


class MockBugSource:
    def __init__(self, bugs: list[BugRecord]):
        self._bugs = bugs

    def get_bugs(self, project_id: Optional[str] = None) -> list[BugRecord]:
        if project_id is None:
            return list(self._bugs)
        return [b for b in self._bugs if b.project_id == project_id]


class MockTestCaseSource:
    def __init__(self, test_cases: list[TestCaseRecord]):
        self._test_cases = test_cases

    def get_test_cases(self) -> list[TestCaseRecord]:
        return list(self._test_cases)


class MockMappingSource:
    def __init__(self, mappings: list[BugTestCaseMappingRecord]):
        self._mappings = mappings

    def get_mappings(self) -> list[BugTestCaseMappingRecord]:
        return list(self._mappings)


class MockTokenUsageSource:
    def __init__(self, records: list[TokenUsageRecord]):
        self._records = records

    def get_token_usage(self, project_id: Optional[str] = None) -> list[TokenUsageRecord]:
        if project_id is None:
            return list(self._records)
        return [r for r in self._records if r.project_id == project_id]

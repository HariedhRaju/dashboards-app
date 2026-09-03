"""
Read-only adapter over generated_test_cases for the Common Analytics Agent.

Implements contracts.TestCaseRecordSource. Reads only — never writes, never
creates the table (it is owned/migrated outside this repository). No
project_id filter parameter exists here because generated_test_cases has no
project_id column at all — confirmed absent from the live schema, not
merely unreliable.
"""
from __future__ import annotations

from typing import Any, Optional

from dashboards import replica_cursor

from .contracts import TestCaseRecord


def _extract_str(test_case_json: Any, key: str) -> Optional[str]:
    """Defensive string extraction from unenforced test_case_json JSONB."""
    if not isinstance(test_case_json, dict):
        return None
    val = test_case_json.get(key)
    if not isinstance(val, str):
        return None
    val = val.strip()
    return val or None


def _extract_priority(test_case_json: Any) -> Optional[str]:
    return _extract_str(test_case_json, "priority")


def _extract_steps(test_case_json: Any) -> Optional[list[str]]:
    """test_case_json["steps"] is unenforced JSONB — may be absent or malformed."""
    if not isinstance(test_case_json, dict):
        return None
    val = test_case_json.get("steps")
    if not isinstance(val, list):
        return None
    steps = [s for s in val if isinstance(s, str) and s.strip()]
    return steps or None


def _record_from_row(r: dict) -> TestCaseRecord:
    tcj = r["test_case_json"]
    return TestCaseRecord(
        id=str(r["id"]),
        created_at=r["created_at"],
        feature_name=(r["feature_name"].strip() or None) if r["feature_name"] else None,
        priority=_extract_priority(tcj),
        title=_extract_str(tcj, "title"),
        steps=_extract_steps(tcj),
        expected_result=_extract_str(tcj, "expected_result"),
        status=_extract_str(tcj, "status"),
    )


class PostgresTestSmithAdapter:
    """Read-only. Never creates, alters, or writes to generated_test_cases."""

    def get_test_cases(self) -> list[TestCaseRecord]:
        with replica_cursor() as cur:
            cur.execute(
                """
                SELECT id, feature_name, test_case_json, created_at
                FROM generated_test_cases
                """
            )
            rows = cur.fetchall()

        return [_record_from_row(r) for r in rows]

    def get_test_cases_by_ids(self, ids: list[str]) -> list[TestCaseRecord]:
        """Bounded lookup for the bug-summary route (fetches only mapped test cases)."""
        if not ids:
            return []
        with replica_cursor() as cur:
            cur.execute(
                """
                SELECT id, feature_name, test_case_json, created_at
                FROM generated_test_cases
                WHERE id::text = ANY(%s)
                """,
                (ids,),
            )
            rows = cur.fetchall()

        return [_record_from_row(r) for r in rows]

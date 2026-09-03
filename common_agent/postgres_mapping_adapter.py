"""
Read-only adapter over bug_test_case_mappings for the Common Analytics Agent.

Implements contracts.BugTestCaseMappingSource.

IMPORTANT — this table is externally owned. It already exists in the live
database (verified: id, bug_id -> bug_reports.id, test_case_id ->
generated_test_cases.id, created_by -> users.id, created_at, unique
constraint on (bug_id, test_case_id)) but nothing in this repository created
or migrates it, and this adapter must not either. This class issues SELECT
only — it MUST NEVER contain CREATE TABLE, ALTER TABLE, INSERT, UPDATE, or
DELETE. Mapping creation, if ever added, belongs in its own dedicated route,
never here and never inside the Common Agent core.

The one additive exception: a nullable `dynamic_fields jsonb` column was
added to this table (by setup/import_fertile_crescent_from_csv.py, following
the same by-convention JSONB pattern already used on bug_reports and
generated_test_cases) to carry mapping provenance — mapping_source,
confidence, reason. That migration lives in the importer script, never here;
this file only ever reads the column.
"""
from __future__ import annotations

from typing import Any, Optional

from dashboards import replica_cursor

from .contracts import BugTestCaseMappingRecord


def _extract_str(dynamic_fields: Any, key: str) -> Optional[str]:
    if not isinstance(dynamic_fields, dict):
        return None
    val = dynamic_fields.get(key)
    if not isinstance(val, str):
        return None
    val = val.strip()
    return val or None


def _record_from_row(r: dict) -> BugTestCaseMappingRecord:
    df = r.get("dynamic_fields")
    return BugTestCaseMappingRecord(
        id=str(r["id"]),
        bug_id=str(r["bug_id"]),
        test_case_id=str(r["test_case_id"]),
        created_at=r["created_at"],
        mapping_source=_extract_str(df, "mapping_source"),
        confidence=_extract_str(df, "confidence"),
        reason=_extract_str(df, "reason"),
    )


class PostgresMappingAdapter:
    """Strictly read-only. Never creates, alters, seeds, or writes to bug_test_case_mappings."""

    def get_mappings(self) -> list[BugTestCaseMappingRecord]:
        with replica_cursor() as cur:
            cur.execute(
                """
                SELECT id, bug_id, test_case_id, created_at, dynamic_fields
                FROM bug_test_case_mappings
                """
            )
            rows = cur.fetchall()

        return [_record_from_row(r) for r in rows]

    def get_mappings_for_bug(self, bug_id: str) -> list[BugTestCaseMappingRecord]:
        """Single-bug lookup for the bug-summary route. Read-only."""
        with replica_cursor() as cur:
            cur.execute(
                """
                SELECT id, bug_id, test_case_id, created_at, dynamic_fields
                FROM bug_test_case_mappings
                WHERE bug_id = %s
                """,
                (bug_id,),
            )
            rows = cur.fetchall()

        return [_record_from_row(r) for r in rows]

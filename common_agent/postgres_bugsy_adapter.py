"""
Read-only adapter over bug_reports for the Common Analytics Agent.

Implements contracts.BugRecordSource. Reads only — never writes. Uses the
existing dashboards.replica_cursor() connection pool; introduces no new
database connection, no new table, no schema change.
"""
from __future__ import annotations

from typing import Any, Optional

from dashboards import replica_cursor

from .contracts import BugRecord


def _extract_module(dynamic_fields: Optional[dict]) -> Optional[str]:
    """dynamic_fields["module"] / ["Game Mode"] / etc. is a by-convention key, not schema-enforced."""
    if not isinstance(dynamic_fields, dict):
        return None
    for key in ["module", "Module", "Game Mode", "game_mode", "Game Mode ", "feature", "Feature", "issue_type", "Issue Type"]:
        val = dynamic_fields.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return None


def _extract_issue_no(dynamic_fields: Optional[dict]) -> Optional[str]:
    """dynamic_fields["source_record_id"] — the original import's human-facing
    issue number (e.g. "11"), not a synthesized index."""
    if not isinstance(dynamic_fields, dict):
        return None
    for key in ["source_record_id", "issue_no", "Issue ID", "Issue No", "issue"]:
        val = dynamic_fields.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return None


class PostgresBugsyAdapter:
    """Read-only. Never creates, alters, or writes to bug_reports."""

    def get_bugs(self, project_id: Optional[str] = None) -> list[BugRecord]:
        where = ""
        params: list[Any] = []
        if project_id:
            where = "WHERE project_id = %s"
            params.append(project_id)

        with replica_cursor() as cur:
            cur.execute(
                f"""
                SELECT id, project_id, severity, status, dynamic_fields, created_at,
                       title, summary
                FROM bug_reports
                {where}
                """,
                params,
            )
            rows = cur.fetchall()

        return [
            BugRecord(
                id=str(r["id"]),
                created_at=r["created_at"],
                project_id=str(r["project_id"]) if r["project_id"] else None,
                severity=r["severity"],
                status=r["status"],
                module=_extract_module(r["dynamic_fields"]),
                title=r["title"],
                summary=r["summary"],
                issue_no=_extract_issue_no(r["dynamic_fields"]),
            )
            for r in rows
        ]

    def get_bug_by_id(self, bug_id: str) -> Optional[BugRecord]:
        """Single-bug lookup for the bug-summary route. Read-only.
        Accepts UUID string or source_record_id / issue_no (e.g. '2', '11#', '#01').
        """
        clean_no = bug_id.strip().replace("#", "")
        with replica_cursor() as cur:
            cur.execute(
                """
                SELECT id, project_id, severity, status, dynamic_fields, created_at,
                       title, summary
                FROM bug_reports
                WHERE id::text = %s
                   OR dynamic_fields->>'source_record_id' = %s
                   OR dynamic_fields->>'source_record_id' = %s
                   OR dynamic_fields->>'issue_no' = %s
                   OR dynamic_fields->>'Issue ID' = %s
                   OR dynamic_fields->>'Issue No' = %s
                LIMIT 1
                """,
                (bug_id, bug_id, clean_no, bug_id, bug_id, bug_id),
            )
            r = cur.fetchone()

        if r is None:
            return None
        return BugRecord(
            id=str(r["id"]),
            created_at=r["created_at"],
            project_id=str(r["project_id"]) if r["project_id"] else None,
            severity=r["severity"],
            status=r["status"],
            module=_extract_module(r["dynamic_fields"]),
            title=r["title"],
            summary=r["summary"],
            issue_no=_extract_issue_no(r["dynamic_fields"]),
        )

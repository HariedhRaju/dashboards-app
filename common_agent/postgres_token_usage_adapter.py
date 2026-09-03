"""
Read-only adapter over token_usage for the Common Analytics Agent.

Implements contracts.TokenUsageSource. Reads only. Note the real data's
known limitation (see core.py's token_usage_by_feature note and CLAUDE.md
§5): existing rows are dominated by feature='unknown' and project_id=NULL
because upstream tagging only covers certain call paths. This adapter
reports whatever is actually stored — it does not paper over that gap.
"""
from __future__ import annotations

from typing import Any, Optional

from dashboards import replica_cursor

from .contracts import TokenUsageRecord


class PostgresTokenUsageAdapter:
    """Read-only. Never creates, alters, or writes to token_usage."""

    def get_token_usage(self, project_id: Optional[str] = None) -> list[TokenUsageRecord]:
        where = ""
        params: list[Any] = []
        if project_id:
            where = "WHERE project_id = %s"
            params.append(project_id)

        with replica_cursor() as cur:
            cur.execute(
                f"""
                SELECT id, feature, project_id, total_tokens, timestamp AS created_at
                FROM token_usage
                {where}
                """,
                params,
            )
            rows = cur.fetchall()

        return [
            TokenUsageRecord(
                id=str(r["id"]),
                created_at=r["created_at"],
                feature=r["feature"],
                project_id=str(r["project_id"]) if r["project_id"] else None,
                total_tokens=r["total_tokens"],
            )
            for r in rows
        ]

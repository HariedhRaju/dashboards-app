"""Postgres source — read an existing bug/test table into canonical records.

The workbook path has to *discover* its schema. A database does not: the
caller already knows the table and can say which column means what. So this
source takes an explicit mapping and does no guessing at all — a column that
was not mapped is simply not read, and a mapping naming a column the table
does not have is an error at fetch time rather than a silently empty field.

What it shares with the workbook path is everything after the raw value:
`clean_text`, `parse_date`, and `canon_enum` are the same functions, so
'v13000' and 'V13000' fold to one build here exactly as they do there, and an
unrecognised severity raises the same warning instead of vanishing.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from typing import Any, Optional

from psycopg2 import sql
from psycopg2.extras import RealDictCursor

from ..ingest.models import (
    Bug,
    BugStatus,
    IngestResult,
    ResultStatus,
    Severity,
    SheetProbe,
    SheetRole,
    SheetShape,
    TestCase,
)
from ..ingest.normalize import canon_enum, clean_text, normalize_build, parse_date
from ..ingest.synonyms import BUG_STATUS_TERMS, RESULT_TERMS, SEVERITY_TERMS

# Canonical field -> source column. Only these fields are read; anything else
# in the table is ignored rather than inferred.
BUG_FIELDS = frozenset({
    "id", "created", "severity", "issue_type", "summary", "description",
    "steps", "actual", "expected", "build", "status", "resolution",
    "dev_comments", "comments",
})

TEST_CASE_FIELDS = frozenset({
    "module", "section", "description", "steps", "expected", "status", "comments",
})


@dataclass
class TableMapping:
    """Which table to read, and which of its columns mean what."""

    table: str
    columns: dict[str, str]                     # canonical field -> column name
    where: Optional[str] = None                 # optional literal SQL predicate
    params: list[Any] = field(default_factory=list)
    limit: Optional[int] = None


# Sensible default: this app's own bug_reports table. Makes the Postgres path
# runnable out of the box against data that is already seeded, rather than
# requiring a mapping before it can be tried at all.
DEFAULT_BUG_MAPPING = TableMapping(
    table="bug_reports",
    columns={
        "id": "id",
        "created": "created_at",
        "severity": "severity",     # P1-P4, folded by SEVERITY_TERMS
        "status": "status",         # open / in_progress / fixed / closed
        "summary": "title",
        "description": "summary",   # that table's `summary` is the long text
    },
)


class PostgresSource:
    kind = "postgres"

    def __init__(
        self,
        cursor: RealDictCursor,
        bugs: Optional[TableMapping] = DEFAULT_BUG_MAPPING,
        test_cases: Optional[TableMapping] = None,
        label: Optional[str] = None,
    ):
        self._cur = cursor
        self._bugs = bugs
        self._test_cases = test_cases
        self._label = label

    def label(self) -> str:
        if self._label:
            return self._label
        tables = [m.table for m in (self._bugs, self._test_cases) if m]
        return f"postgres:{','.join(tables) or 'none'}"

    # ── fetch ────────────────────────────────────────────────────────────

    def fetch(self) -> IngestResult:
        warnings: list[str] = []
        sheets: list[SheetProbe] = []

        bugs: list[Bug] = []
        if self._bugs:
            rows = self._select(self._bugs, BUG_FIELDS)
            bugs = self._build_bugs(rows, self._bugs.table, warnings)
            sheets.append(self._probe(self._bugs, SheetRole.BUGS, len(bugs)))

        test_cases: list[TestCase] = []
        if self._test_cases:
            rows = self._select(self._test_cases, TEST_CASE_FIELDS)
            test_cases = self._build_test_cases(rows, self._test_cases.table, warnings)
            sheets.append(
                self._probe(self._test_cases, SheetRole.TEST_CASES, len(test_cases))
            )

        return IngestResult(
            source_path=self.label(),
            fingerprint=self._fingerprint(),
            sheets=sheets,
            bugs=bugs,
            test_cases=test_cases,
            matrix_results=[],   # a matrix is a spreadsheet shape, not a table one
            warnings=warnings,
        )

    # ── query ────────────────────────────────────────────────────────────

    def _select(self, mapping: TableMapping, allowed: frozenset[str]) -> list[dict]:
        unknown = set(mapping.columns) - allowed
        if unknown:
            raise ValueError(
                f"{mapping.table}: not canonical field(s): {sorted(unknown)}. "
                f"Known fields: {sorted(allowed)}"
            )
        if not mapping.columns:
            raise ValueError(f"{mapping.table}: mapping selects no columns")

        # Identifiers are composed, never interpolated — the table and column
        # names arrive from a caller-supplied mapping, so they are untrusted
        # input like any other.
        selected = sql.SQL(", ").join(
            sql.SQL("{} AS {}").format(sql.Identifier(col), sql.Identifier(fieldname))
            for fieldname, col in mapping.columns.items()
        )
        query = sql.SQL("SELECT {cols} FROM {table}").format(
            cols=selected, table=sql.Identifier(*mapping.table.split(".")),
        )
        if mapping.where:
            query = sql.SQL("{} WHERE {}").format(query, sql.SQL(mapping.where))
        if mapping.limit:
            query = sql.SQL("{} LIMIT {}").format(query, sql.Literal(mapping.limit))

        self._cur.execute(query, mapping.params or None)
        return [dict(r) for r in self._cur.fetchall()]

    # ── build ────────────────────────────────────────────────────────────

    def _build_bugs(self, rows: list[dict], table: str, warnings: list[str]) -> list[Bug]:
        out: list[Bug] = []
        for i, r in enumerate(rows, start=1):
            where = f"{table} row {i}"
            severity = canon_enum(r.get("severity"), SEVERITY_TERMS, warnings,
                                  f"{where} severity")
            status = canon_enum(r.get("status"), BUG_STATUS_TERMS, warnings,
                                f"{where} status")
            out.append(Bug(
                id=clean_text(r.get("id")) or f"row-{i}",
                source_sheet=table,
                source_row=i,
                created=parse_date(r.get("created"), warnings, f"{where} created"),
                severity=Severity(severity) if severity else Severity.UNKNOWN,
                issue_type=clean_text(r.get("issue_type")),
                summary=clean_text(r.get("summary")),
                description=clean_text(r.get("description")),
                steps=clean_text(r.get("steps")),
                actual=clean_text(r.get("actual")),
                expected=clean_text(r.get("expected")),
                build=normalize_build(r.get("build")),
                status=BugStatus(status) if status else BugStatus.UNKNOWN,
                resolution=clean_text(r.get("resolution")),
                dev_comments=clean_text(r.get("dev_comments")),
                comments=clean_text(r.get("comments")),
            ))
        return out

    def _build_test_cases(
        self, rows: list[dict], table: str, warnings: list[str]
    ) -> list[TestCase]:
        out: list[TestCase] = []
        for i, r in enumerate(rows, start=1):
            raw_status = r.get("status")
            status = canon_enum(raw_status, RESULT_TERMS, warnings,
                                f"{table} row {i} status")
            # Blank means never run — a finding in its own right, and not the
            # same thing as a status we failed to recognise.
            resolved = (
                ResultStatus(status) if status
                else ResultStatus.NOT_RUN if clean_text(raw_status) is None
                else ResultStatus.UNKNOWN
            )
            out.append(TestCase(
                source_sheet=table,
                source_row=i,
                module=clean_text(r.get("module")),
                section=clean_text(r.get("section")),
                description=clean_text(r.get("description")),
                steps=clean_text(r.get("steps")),
                expected=clean_text(r.get("expected")),
                status=resolved,
                linked_bug_ids=[],
                comments=clean_text(r.get("comments")),
            ))
        return out

    # ── metadata ─────────────────────────────────────────────────────────

    def _probe(self, mapping: TableMapping, role: SheetRole, rows: int) -> SheetProbe:
        """A table's mapping described in the same shape a sheet probe uses,
        so the UI's ingest panel renders both sources with one component."""
        from ..ingest.models import ColumnMapping

        return SheetProbe(
            name=mapping.table,
            shape=SheetShape.RECORD,
            header_row=1,
            data_columns=list(range(len(mapping.columns))),
            first_data_row=2,
            last_data_row=rows + 1,
            row_count=rows,
            role=role,
            columns=[
                ColumnMapping(index=i, header=col, field=fieldname,
                              confidence=1.0, method="declared")
                for i, (fieldname, col) in enumerate(mapping.columns.items())
            ],
        )

    def _fingerprint(self) -> str:
        """Hash of the mapping, not the data — same role as the workbook's
        structural fingerprint, so re-reading an unchanged source is
        recognisable as the same shape."""
        parts: list[str] = []
        for mapping in (self._bugs, self._test_cases):
            if not mapping:
                continue
            parts.append(mapping.table)
            parts.extend(f"{k}={v}" for k, v in sorted(mapping.columns.items()))
        return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()[:16]


def source_dsn() -> Optional[str]:
    """DSN for an external QA source, when one is configured separately."""
    return os.getenv("QA_SOURCE_DSN")

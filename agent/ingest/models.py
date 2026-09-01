"""Canonical records and the vocabulary the whole pipeline binds to.

Nothing downstream of normalization knows about spreadsheet columns. Analysis,
visualization, and query all read these types, which is what lets the ingest
layer swap schemas without touching anything else.
"""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------
# sheet structure
# --------------------------------------------------------------------------

class SheetShape(str, Enum):
    """How a sheet lays its data out, which decides the mapper that runs."""

    RECORD = "record"   # one entity per row, columns are fields
    MATRIX = "matrix"   # entity rows x dimension columns, cells are results
    GRID = "grid"       # small summary block
    NOISE = "noise"     # not enough structure to parse


class SheetRole(str, Enum):
    """What a sheet contains, once its columns are understood."""

    BUGS = "bugs"
    TEST_CASES = "test_cases"
    MATRIX_RESULTS = "matrix_results"
    PROGRESS = "progress"
    IGNORE = "ignore"


# --------------------------------------------------------------------------
# controlled vocabularies
# --------------------------------------------------------------------------

class Severity(str, Enum):
    BLOCKER = "Blocker"
    CRITICAL = "Critical"
    MAJOR = "Major"
    MINOR = "Minor"
    TRIVIAL = "Trivial"
    UNKNOWN = "Unknown"


# Severity is ordered, not categorical. The renderer needs this rank to build a
# sequential ramp; without it severity would get arbitrary hues and the ordering
# that is the entire point of the field would be thrown away.
SEVERITY_RANK: dict[str, int] = {
    Severity.BLOCKER: 5,
    Severity.CRITICAL: 4,
    Severity.MAJOR: 3,
    Severity.MINOR: 2,
    Severity.TRIVIAL: 1,
    Severity.UNKNOWN: 0,
}


class BugStatus(str, Enum):
    OPEN = "Open"
    IN_PROGRESS = "In Progress"
    QA_READY = "QA Ready"
    CLOSED = "Closed"
    DEFERRED = "Deferred"
    UNKNOWN = "Unknown"


# Which statuses still represent outstanding work. Used by coverage and by the
# health verdict; kept here so the definition lives in one place.
OPEN_BUG_STATUSES = frozenset(
    {BugStatus.OPEN, BugStatus.IN_PROGRESS, BugStatus.QA_READY}
)


class ResultStatus(str, Enum):
    """Outcome of a test case or a localization matrix cell."""

    PASS = "Pass"
    FAIL = "Fail"
    SOME_ISSUE = "Some Issue"
    BLOCKED = "Blocked"
    IN_PROGRESS = "In Progress"
    NOT_RUN = "Not Run"
    UNKNOWN = "Unknown"


# --------------------------------------------------------------------------
# canonical records
# --------------------------------------------------------------------------

class Bug(BaseModel):
    id: str
    source_sheet: str
    source_row: int

    created: Optional[date] = None
    severity: Severity = Severity.UNKNOWN
    issue_type: Optional[str] = None
    summary: Optional[str] = None
    description: Optional[str] = None
    steps: Optional[str] = None
    actual: Optional[str] = None
    expected: Optional[str] = None
    build: Optional[str] = None
    status: BugStatus = BugStatus.UNKNOWN
    resolution: Optional[str] = None
    dev_comments: Optional[str] = None
    comments: Optional[str] = None

    @property
    def is_open(self) -> bool:
        return self.status in OPEN_BUG_STATUSES

    def text_for_embedding(self) -> str:
        """Concatenation used for clustering and duplicate detection."""
        parts = [self.summary, self.description]
        return "\n".join(p for p in parts if p)


class TestCase(BaseModel):
    source_sheet: str
    source_row: int

    case_id: Optional[str] = None       # 'TC-001' when the source has one
    module: Optional[str] = None
    section: Optional[str] = None
    title: Optional[str] = None
    priority: Optional[str] = None      # Core / High / Medium / Low, as written
    preconditions: Optional[str] = None
    description: Optional[str] = None
    steps: Optional[str] = None
    expected: Optional[str] = None
    status: ResultStatus = ResultStatus.NOT_RUN
    linked_bug_ids: list[str] = Field(default_factory=list)
    comments: Optional[str] = None

    @property
    def was_executed(self) -> bool:
        return self.status not in (ResultStatus.NOT_RUN, ResultStatus.UNKNOWN)

    @property
    def ref(self) -> str:
        """How this case is cited in a report.

        The source's own id when it has one, because that is what a tester
        will search for. Falling back to the sheet row keeps every case
        citable even when the source never numbered them.
        """
        return self.case_id or f"TC-{self.source_row}"


class MatrixResult(BaseModel):
    """One cell of a matrix sheet, unpivoted to long form.

    `dimension` is the column header (a language, a platform); `item` is the row
    label. Long form is what makes these chartable alongside everything else.
    """

    source_sheet: str
    source_row: int

    section: Optional[str] = None
    item: Optional[str] = None
    dimension: str
    status: ResultStatus = ResultStatus.UNKNOWN
    comment: Optional[str] = None


# --------------------------------------------------------------------------
# probe / mapping results
# --------------------------------------------------------------------------

class ColumnMapping(BaseModel):
    index: int
    header: Optional[str]
    field: Optional[str] = None          # canonical field name, None if unresolved
    confidence: float = 0.0
    method: str = "unresolved"           # synonym | signature | llm | unresolved
    note: Optional[str] = None           # why it was rejected, when it was


class SheetProbe(BaseModel):
    name: str
    shape: SheetShape
    header_row: Optional[int] = None     # 1-indexed, as the spreadsheet shows it
    data_columns: list[int] = Field(default_factory=list)
    first_data_row: Optional[int] = None
    last_data_row: Optional[int] = None
    row_count: int = 0
    role: SheetRole = SheetRole.IGNORE
    columns: list[ColumnMapping] = Field(default_factory=list)

    @property
    def unresolved(self) -> list[ColumnMapping]:
        return [c for c in self.columns if c.field is None]


class IngestResult(BaseModel):
    source_path: str
    fingerprint: str
    sheets: list[SheetProbe] = Field(default_factory=list)
    bugs: list[Bug] = Field(default_factory=list)
    test_cases: list[TestCase] = Field(default_factory=list)
    matrix_results: list[MatrixResult] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

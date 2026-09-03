"""Turn mapped columns into validated canonical records.

Everything the source got wrong is absorbed here so nothing downstream has to
know about it: encoding damage, enum values that drifted, build strings that
differ only in case, dates written day-first, section labels that live in a
banner row rather than a column.

Unrecognised enum values are never dropped silently. They map to an `Unknown`
member and raise a warning, because a status nobody anticipated is a fact about
the data, not noise to discard.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any, Optional

import ftfy
from dateutil import parser as dateparser
from rapidfuzz import process as fuzz_process

from .models import (
    Bug,
    BugStatus,
    MatrixResult,
    ResultStatus,
    Severity,
    SheetProbe,
    SheetRole,
    TestCase,
)
from .probe import Sheet, body_rows
from .synonyms import BUG_STATUS_TERMS, RESULT_TERMS, SEVERITY_TERMS

# How close an unrecognised term must be to a known one before we accept it.
ENUM_FUZZ_CUTOFF = 88

_BUG_ID_RE = re.compile(r"[A-Za-z]*[-_ ]?\d+#?")
_WS_RE = re.compile(r"[ \t]+")


def clean_text(v: Any) -> Optional[str]:
    """Repair encoding damage and collapse whitespace.

    Smart quotes round-tripped through the wrong codepage leave replacement
    characters through this file. ftfy restores what it can; the rest are
    stripped so they never reach a model, which a small one is easily derailed
    by, or a report, where they simply look broken.
    """
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, (date, datetime)):
        return v.isoformat()

    s = ftfy.fix_text(str(v))
    s = s.replace("�", "")
    s = _WS_RE.sub(" ", s)
    s = "\n".join(line.strip() for line in s.splitlines())
    s = s.strip()
    return s or None


def parse_date(
    v: Any, warnings: Optional[list[str]] = None, label: str = "date"
) -> Optional[date]:
    """Parse a cell as a date, day-first.

    The pilot workbook writes 15/09/2025. Month-first parsing turns that into an
    invalid month and silently yields None, so day-first is the default rather
    than a fallback.

    A value that is present but unparseable is reported. Blank means "not
    recorded"; malformed means someone typed it wrong, and the difference
    matters to whoever has to fix the source.
    """
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = clean_text(v)
    if not s:
        return None
    try:
        return dateparser.parse(s, dayfirst=True).date()
    except (ValueError, OverflowError, TypeError):
        if warnings is not None:
            warnings.append(f"{label}: unparseable date {s!r}")
        return None


def canon_enum(
    v: Any, terms: dict[str, str], warnings: list[str], label: str
) -> Optional[str]:
    """Map a raw cell to a known vocabulary term, or record that it did not fit."""
    s = clean_text(v)
    if not s:
        return None

    key = s.strip().lower()
    if key in terms:
        return terms[key]

    match = fuzz_process.extractOne(key, list(terms.keys()), score_cutoff=ENUM_FUZZ_CUTOFF)
    if match:
        return terms[match[0]]

    warnings.append(f"{label}: unrecognised value {s!r}")
    return None


def normalize_build(v: Any) -> Optional[str]:
    """Fold build strings that differ only in case or spacing.

    V13000 and v13000 are the same build; treating them as two halves the
    apparent coverage of every build-scoped statistic.
    """
    s = clean_text(v)
    if not s:
        return None
    return s.strip().lower().replace(" ", "")


def split_bug_ids(v: Any) -> list[str]:
    s = clean_text(v)
    if not s:
        return []
    return [m.group(0).strip() for m in _BUG_ID_RE.finditer(s)]


def _section_for(sheet: Sheet, row: int) -> Optional[str]:
    """Nearest banner row above `row` — the section this record sits under."""
    for r in range(row - 1, -1, -1):
        if r in sheet.banner_rows:
            first = next(
                (c for c, v in enumerate(sheet.values[r]) if v is not None), None
            )
            if first is not None:
                return clean_text(sheet.values[r][first])
    return None


def _field_index(probe: SheetProbe) -> dict[str, int]:
    return {m.field: m.index for m in probe.columns if m.field}


def _cell(sheet: Sheet, row: int, idx: Optional[int]) -> Any:
    if idx is None:
        return None
    r = sheet.values[row]
    return r[idx] if idx < len(r) else None


def build_bugs(
    sheet: Sheet, probe: SheetProbe, warnings: list[str]
) -> list[Bug]:
    fields = _field_index(probe)
    rows = body_rows(sheet, probe.data_columns, probe.header_row - 1)
    out: list[Bug] = []

    for i, r in enumerate(rows, start=1):
        raw_id = clean_text(_cell(sheet, r, fields.get("id")))
        severity = canon_enum(
            _cell(sheet, r, fields.get("severity")), SEVERITY_TERMS,
            warnings, f"{sheet.name} row {r + 1} severity",
        )
        status = canon_enum(
            _cell(sheet, r, fields.get("status")), BUG_STATUS_TERMS,
            warnings, f"{sheet.name} row {r + 1} status",
        )
        out.append(Bug(
            id=raw_id or f"row-{r + 1}",
            source_sheet=sheet.name,
            source_row=r + 1,
            reporter=clean_text(_cell(sheet, r, fields.get("reporter"))),
            created=parse_date(
                _cell(sheet, r, fields.get("created")),
                warnings, f"{sheet.name} row {r + 1} created",
            ),
            severity=Severity(severity) if severity else Severity.UNKNOWN,
            issue_type=clean_text(_cell(sheet, r, fields.get("issue_type"))),
            summary=clean_text(_cell(sheet, r, fields.get("summary"))),
            description=clean_text(_cell(sheet, r, fields.get("description"))),
            steps=clean_text(_cell(sheet, r, fields.get("steps"))),
            actual=clean_text(_cell(sheet, r, fields.get("actual"))),
            expected=clean_text(_cell(sheet, r, fields.get("expected"))),
            build=normalize_build(_cell(sheet, r, fields.get("build"))),
            status=BugStatus(status) if status else BugStatus.UNKNOWN,
            resolution=clean_text(_cell(sheet, r, fields.get("resolution"))),
            dev_comments=clean_text(_cell(sheet, r, fields.get("dev_comments"))),
            comments=clean_text(_cell(sheet, r, fields.get("comments"))),
        ))
    return out


def build_test_cases(
    sheet: Sheet, probe: SheetProbe, warnings: list[str]
) -> list[TestCase]:
    fields = _field_index(probe)
    rows = body_rows(sheet, probe.data_columns, probe.header_row - 1)
    out: list[TestCase] = []

    for r in rows:
        raw_status = _cell(sheet, r, fields.get("status"))
        status = canon_enum(
            raw_status, RESULT_TERMS, warnings,
            f"{sheet.name} row {r + 1} status",
        )
        # A blank status is "never run", which is a finding in its own right and
        # must not be conflated with a status we failed to recognise.
        resolved = (
            ResultStatus(status) if status
            else ResultStatus.NOT_RUN if clean_text(raw_status) is None
            else ResultStatus.UNKNOWN
        )
        out.append(TestCase(
            source_sheet=sheet.name,
            source_row=r + 1,
            case_id=clean_text(_cell(sheet, r, fields.get("case_id"))),
            reporter=clean_text(_cell(sheet, r, fields.get("reporter"))),
            module=clean_text(_cell(sheet, r, fields.get("module"))),
            section=_section_for(sheet, r),
            title=clean_text(_cell(sheet, r, fields.get("title"))),
            priority=clean_text(_cell(sheet, r, fields.get("priority"))),
            preconditions=clean_text(_cell(sheet, r, fields.get("preconditions"))),
            description=clean_text(_cell(sheet, r, fields.get("description"))),
            steps=clean_text(_cell(sheet, r, fields.get("steps"))),
            expected=clean_text(_cell(sheet, r, fields.get("expected"))),
            status=resolved,
            linked_bug_ids=split_bug_ids(_cell(sheet, r, fields.get("linked_bug_ids"))),
            comments=clean_text(_cell(sheet, r, fields.get("comments"))),
        ))
    return out


def _dimension_headers_are_untrustworthy(dimensions: list[tuple[int, str]]) -> bool:
    """True when the "dimension" column headers are themselves result words.

    A real matrix's dimension is a locale, a platform, a build — never "Pass"
    or "N/A". Seeing that means header detection locked onto a DATA row
    instead of the true header: a multi-row "swimlane" layout (tester / build
    / date / platform stacked above a generic "Outcome" label row) scores its
    real header poorly, because a row of six repeated "Outcome" cells has
    near-zero distinctness — while the first data row below it, six "Pass"
    cells and an "N/A", looks exactly as label-like by the same test.

    Downstream this reads as "the French dimension" being a test case's
    description and "N/A" being a locale, which is worse than no matrix at
    all — it looks like real localization data. This is the same
    exclude-rather-than-guess call as the bug-role fix: a sheet whose header
    the mapper cannot trust should emit nothing, not something wrong.
    """
    if not dimensions:
        return False
    normalized = [_norm_result_key(name) for _, name in dimensions]
    hits = sum(1 for n in normalized if n in RESULT_TERMS)
    # No minimum column count. A real dimension is never literally the word
    # "pass" or "n/a" regardless of how many columns there are — a one-column
    # matrix whose only dimension is named "Pass" is exactly as untrustworthy
    # as a six-column one, which a `len(dimensions) < 3` guard here originally
    # missed: a Maps-file sheet with a single build column slipped through and
    # was written as 46 "Pass"-dimension records before this was tightened.
    return hits / len(dimensions) >= 0.6


def _norm_result_key(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().lower())


def build_matrix_results(
    sheet: Sheet, probe: SheetProbe, warnings: list[str]
) -> list[MatrixResult]:
    """Unpivot a matrix sheet to long form, one record per populated cell."""
    header = sheet.values[probe.header_row - 1]
    rows = body_rows(sheet, probe.data_columns, probe.header_row - 1)

    item_col = next(
        (m.index for m in probe.columns if m.field == "item"), None
    )
    comment_col = next(
        (m.index for m in probe.columns if m.field == "comment"), None
    )
    dimensions = [
        (m.index, clean_text(header[m.index]) or f"col{m.index}")
        for m in probe.columns if m.field == "dimension"
    ]

    if _dimension_headers_are_untrustworthy(dimensions):
        warnings.append(
            f"{sheet.name}: dimension columns read as result words "
            f"({', '.join(d for _, d in dimensions[:4])}, …) rather than "
            "locale/platform/build names — header detection likely locked "
            "onto a data row on this multi-row-header sheet; excluded rather "
            "than reported as a matrix"
        )
        return []

    out: list[MatrixResult] = []
    for r in rows:
        item = clean_text(_cell(sheet, r, item_col))
        comment = clean_text(_cell(sheet, r, comment_col))
        section = _section_for(sheet, r)

        for col, dim in dimensions:
            raw = _cell(sheet, r, col)
            if clean_text(raw) is None:
                continue
            status = canon_enum(
                raw, RESULT_TERMS, warnings,
                f"{sheet.name} row {r + 1} {dim}",
            )
            out.append(MatrixResult(
                source_sheet=sheet.name,
                source_row=r + 1,
                section=section,
                item=item,
                dimension=dim,
                status=ResultStatus(status) if status else ResultStatus.UNKNOWN,
                comment=comment,
            ))
    return out


BUILDERS = {
    SheetRole.BUGS: build_bugs,
    SheetRole.TEST_CASES: build_test_cases,
    SheetRole.MATRIX_RESULTS: build_matrix_results,
}

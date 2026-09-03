"""Resolve spreadsheet columns to canonical fields.

Two independent signals, deliberately kept separate so they can disagree:
the header's wording, and the shape of the values underneath it. Agreement is a
confident mapping. Disagreement is the interesting case — it is how a column
labelled "Repro Rate" that actually holds dates gets caught instead of being
believed. Columns the pair cannot settle are left unresolved for the model
tie-breaker, never guessed.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any, Optional

from dateutil import parser as dateparser
from rapidfuzz import fuzz

from .models import ColumnMapping, SheetProbe, SheetRole, SheetShape
from .probe import Sheet, body_rows
from .synonyms import (
    BUG_STATUS_TERMS,
    FIELD_SETS,
    RESULT_TERMS,
    SEVERITY_TERMS,
    ValueShape,
)

# Exact-after-normalization matches score 100. Below this a header is only a
# hint, and the value signature has to agree before we accept it.
STRONG_MATCH = 88
WEAK_MATCH = 72

SAMPLE_ROWS = 250


def _norm(s: Any) -> str:
    if s is None:
        return ""
    return " ".join(str(s).strip().lower().replace("_", " ").split())


def _header_match(header: str, fields: dict) -> tuple[Optional[str], float]:
    """Best canonical field for a header string, by fuzzy comparison.

    Token-set matching is restricted to terms of four characters or more. It
    reports a perfect score whenever one string's tokens are a subset of the
    other's, which for a two-letter synonym like "id" means almost any long
    header matches it — the kind of false positive that then blocks the column
    that genuinely owns the field.
    """
    h = _norm(header)
    if not h:
        return None, 0.0

    best_field, best_score = None, 0.0
    for field, (terms, _shape) in fields.items():
        for term in terms:
            score = fuzz.ratio(h, term)
            if len(term) >= 4:
                score = max(score, fuzz.token_set_ratio(h, term) * 0.95)
            # A header leads with the field it names and qualifies afterwards,
            # so an initial match outranks one buried in trailing instructions.
            # "Attachments (use this link)... Issue #" contains both
            # "attachments" and "issue"; only one of them is the column's name.
            if h.startswith(term):
                score = min(100.0, score + 6)
            if score > best_score:
                best_field, best_score = field, score
    return best_field, best_score


def column_values(sheet: Sheet, col: int, rows: list[int]) -> list[Any]:
    out = []
    for r in rows[:SAMPLE_ROWS]:
        row = sheet.values[r]
        if col < len(row) and row[col] is not None:
            if not (isinstance(row[col], str) and not row[col].strip()):
                out.append(row[col])
    return out


_DATE_LIKE = re.compile(r"^\s*\d{1,4}[-/.]\d{1,2}[-/.]\d{1,4}\s*$")


def looks_like_date(v: Any) -> bool:
    """True for real dates and for the strings spreadsheets leave as text.

    Excel stores a date typed into a text-formatted cell as a plain string, so
    a column can be entirely dates and contain no date objects at all. The
    regex gate comes first because dateutil will happily read a build number or
    an issue key as a date if simply handed one.
    """
    if isinstance(v, (date, datetime)):
        return True
    if not isinstance(v, str) or not _DATE_LIKE.match(v):
        return False
    try:
        dateparser.parse(v, dayfirst=True)
        return True
    except (ValueError, OverflowError):
        return False


def value_shape(values: list[Any]) -> ValueShape:
    """Classify what a column actually contains."""
    if not values:
        return ValueShape.ANY

    dates = sum(1 for v in values if looks_like_date(v))
    if dates / len(values) >= 0.7:
        return ValueShape.DATE

    texts = [str(v).strip() for v in values]
    distinct = {t.lower() for t in texts}
    avg_len = sum(len(t) for t in texts) / len(texts)

    if avg_len > 45:
        return ValueShape.TEXT
    if len(distinct) <= 12 and avg_len <= 30:
        return ValueShape.ENUM
    if len(distinct) / len(texts) >= 0.85 and avg_len <= 20:
        return ValueShape.IDENTIFIER
    return ValueShape.TEXT


def _shapes_agree(expected: ValueShape, actual: ValueShape) -> bool:
    if expected is ValueShape.ANY or actual is ValueShape.ANY:
        return True
    if expected == actual:
        return True
    # Enum and identifier both look like short tokens; text absorbs either when
    # a field is sparsely filled. Only DATE is treated as strictly exclusive,
    # because a date where a category belongs is the failure worth catching.
    soft = {ValueShape.ENUM, ValueShape.IDENTIFIER, ValueShape.TEXT}
    return expected in soft and actual in soft


def _vocabulary_hint(values: list[Any]) -> Optional[str]:
    """Recognise a column from its values when the header is unhelpful."""
    if not values:
        return None
    lowered = {str(v).strip().lower() for v in values}
    for terms, field in (
        (SEVERITY_TERMS, "severity"),
        (RESULT_TERMS, "status"),
        (BUG_STATUS_TERMS, "status"),
    ):
        hits = sum(1 for v in lowered if v in terms)
        if lowered and hits / len(lowered) >= 0.6:
            return field
    return None


def map_matrix_columns(sheet: Sheet, probe: SheetProbe) -> list[ColumnMapping]:
    """Map a matrix sheet, where most columns are values rather than fields.

    "Chinese" and "Polish" are not fields to resolve — they are the dimension
    the matrix is indexed by, and their headers become data when the sheet is
    unpivoted. Only the row label and any trailing annotation are real fields.
    """
    rows = body_rows(sheet, probe.data_columns, probe.header_row - 1)
    header = sheet.values[probe.header_row - 1]
    mappings: list[ColumnMapping] = []

    for i, c in enumerate(probe.data_columns):
        raw = header[c] if c < len(header) else None
        values = column_values(sheet, c, rows)

        if i == 0:
            mappings.append(ColumnMapping(
                index=c, header=str(raw) if raw is not None else None,
                field="item", confidence=1.0, method="structural",
                note="row label of the matrix",
            ))
            continue

        lowered = {str(v).strip().lower() for v in values}
        in_vocab = sum(1 for v in lowered if v in RESULT_TERMS)
        if lowered and in_vocab / len(lowered) >= 0.6:
            mappings.append(ColumnMapping(
                index=c, header=str(raw) if raw is not None else None,
                field="dimension", confidence=1.0, method="structural",
                note=f"dimension '{_norm(raw)}' — unpivoted to long form",
            ))
        else:
            field, score = _header_match(raw, FIELD_SETS["matrix_results"])
            mappings.append(ColumnMapping(
                index=c, header=str(raw) if raw is not None else None,
                field="comment" if score >= WEAK_MATCH and field == "comment"
                else None,
                confidence=score / 100 if score >= WEAK_MATCH else 0.0,
                method="synonym" if score >= WEAK_MATCH else "unresolved",
                note=None if score >= WEAK_MATCH
                else "neither a result column nor a recognised field",
            ))

    return mappings


def map_columns(
    sheet: Sheet, probe: SheetProbe, role: SheetRole
) -> list[ColumnMapping]:
    if probe.header_row is None:
        return []
    if role is SheetRole.MATRIX_RESULTS:
        return map_matrix_columns(sheet, probe)

    fields = FIELD_SETS.get(role.value)
    if fields is None:
        return []

    rows = body_rows(sheet, probe.data_columns, probe.header_row - 1)
    header = sheet.values[probe.header_row - 1]
    taken: set[str] = set()
    mappings: list[ColumnMapping] = []

    # Resolve strongest matches first so a confident column claims its field
    # before a weaker candidate can take it.
    scored = []
    for c in probe.data_columns:
        raw = header[c] if c < len(header) else None
        field, score = _header_match(raw, fields)
        scored.append((score, c, raw, field))
    scored.sort(key=lambda t: -t[0])

    for score, c, raw, field in scored:
        values = column_values(sheet, c, rows)
        actual = value_shape(values)

        if field is None or score < WEAK_MATCH or field in taken:
            hint = _vocabulary_hint(values)
            if hint and hint not in taken and hint in fields:
                taken.add(hint)
                mappings.append(ColumnMapping(
                    index=c, header=str(raw) if raw is not None else None,
                    field=hint, confidence=0.7, method="signature",
                    note="matched on its values; header was not decisive",
                ))
            else:
                mappings.append(ColumnMapping(
                    index=c, header=str(raw) if raw is not None else None,
                    note="no confident field match" if field is None
                    else f"'{field}' already claimed by a stronger column",
                ))
            continue

        expected = fields[field][1]
        if not _shapes_agree(expected, actual):
            mappings.append(ColumnMapping(
                index=c, header=str(raw) if raw is not None else None,
                confidence=0.0, method="rejected",
                note=(
                    f"header reads '{raw}' but the column holds "
                    f"{actual.value} values, not {expected.value} — dropped"
                ),
            ))
            continue

        taken.add(field)
        mappings.append(ColumnMapping(
            index=c, header=str(raw) if raw is not None else None,
            field=field,
            confidence=min(1.0, score / 100),
            method="synonym" if score >= STRONG_MATCH else "synonym-weak",
        ))

    mappings.sort(key=lambda m: m.index)
    return mappings


def detect_role(sheet: Sheet, probe: SheetProbe) -> SheetRole:
    """Decide what a sheet holds, by trying each field set and seeing what fits."""
    if probe.header_row is None or probe.shape is SheetShape.NOISE:
        return SheetRole.IGNORE

    if probe.shape is SheetShape.MATRIX:
        return SheetRole.MATRIX_RESULTS

    if probe.shape is SheetShape.GRID:
        return SheetRole.PROGRESS

    header = sheet.values[probe.header_row - 1]
    best_role, best_score, best_matched = SheetRole.IGNORE, 0.0, 0

    for role_name in ("bugs", "test_cases"):
        fields = FIELD_SETS[role_name]
        matched, total, matched_fields = 0.0, 0, 0
        for c in probe.data_columns:
            raw = header[c] if c < len(header) else None
            if not _norm(raw):
                continue
            total += 1
            _f, score = _header_match(raw, fields)
            if score >= WEAK_MATCH:
                matched += score / 100
                matched_fields += 1
        ratio = matched / total if total else 0.0

        # A bug tracker is distinguishable from a test plan by fields only one
        # of them has; header overlap alone ("status", "comments") is not enough.
        #
        # "priority" is deliberately NOT a bug signal. Test plans prioritise
        # their cases just as often as trackers prioritise defects, and
        # treating it as evidence for "bugs" is what made a sheet headed
        # "Test Case ID | Feature | Priority | Title" import as 87 bugs whose
        # severity was 'Core'. What actually separates the two is a field only
        # one of them can have: a bug records what happened ("actual result",
        # "repro rate", "dev comments"); a test case records what should
        # ("preconditions", "expected result", "test case id").
        #
        # "build" is NOT a bug signal either, for the identical reason and a
        # second real incident. A per-feature test sheet laid out as item x
        # build (rows = test items, one column per tested build) has a
        # "Build Number" header and otherwise near-zero resolvable columns —
        # matched=1/8. The flat +0.35 alone pushed that 0.12 ratio over the
        # 0.45 bar and imported 172 rows of near-empty "bugs" with severity
        # Unknown. A build column appears on trackers and test plans alike;
        # it distinguishes nothing.
        headers = {_norm(header[c]) for c in probe.data_columns if c < len(header)}
        if role_name == "bugs" and any(
            h.startswith(("severity", "repro", "actual", "dev ", "resolution"))
            for h in headers
        ):
            ratio += 0.35
        if role_name == "test_cases" and any(
            h.startswith(("verification", "test case", "testcase", "module",
                          "precondition", "pre condition", "expected result",
                          "test steps", "tc id"))
            for h in headers
        ):
            ratio += 0.35

        if ratio > best_score:
            best_role, best_score, best_matched = SheetRole(role_name), ratio, matched_fields

    if best_score < 0.45:
        return SheetRole.IGNORE

    # A single strong-header boost must not, by itself, carry a sheet whose
    # actual content the mapper barely understood. On a sheet with several
    # real headers to judge, one resolved field plus a +0.35 boost is what
    # committed "item x build" test sheets as bug trackers — matched=1,
    # total=8, ratio=0.12, boosted straight past the 0.45 bar. Two resolved
    # fields is a low bar a real tracker clears many times over; a sheet that
    # cannot clear it is one the mapper does not understand well enough to
    # emit records from.
    header_evidence = sum(
        1 for c in probe.data_columns if c < len(header) and _norm(header[c])
    )
    if header_evidence >= 4 and best_matched < 2:
        return SheetRole.IGNORE
    return best_role

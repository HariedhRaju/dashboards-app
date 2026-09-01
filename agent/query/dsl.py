"""The filter DSL a chat question compiles into.

The model translates a question into this schema; Python compiles the schema
into SQL. The model never writes SQL and never sees the database schema — the
field enum below *is* its interface. A question about a column that does not
exist fails validation with a clear message rather than producing a confusing
empty result or, worse, an injected query.

Every identifier that reaches SQL is checked against these sets first, so the
compiler can interpolate column names knowing they came from this file and not
from the model.
"""

from __future__ import annotations

from enum import Enum
from typing import Union

from pydantic import BaseModel, Field, field_validator

# Entity -> the table it reads, and the snapshot column that scopes it.
ENTITY_TABLES: dict[str, str] = {
    "bug": "qa_bugs",
    "test_case": "qa_test_cases",
    "matrix_result": "qa_matrix_results",
}

# The only fields a filter may reference, per entity. Anything else is a
# hallucinated field name and is rejected before it reaches SQL.
ALLOWED_FIELDS: dict[str, set[str]] = {
    "bug": {
        "bug_key", "severity", "status", "issue_type", "build", "is_open",
        "created", "resolution",
    },
    "test_case": {"status", "module", "was_executed", "section"},
    "matrix_result": {"dimension", "status", "section", "item"},
}

# Free-text fields, routed to a text search rather than a column predicate.
# Bugs have a generated tsvector; the others fall back to ILIKE, which is fine
# at these row counts and avoids a second index nobody would otherwise need.
FTS_FIELDS: dict[str, set[str]] = {
    "bug": {"summary", "description", "steps", "actual", "expected",
            "dev_comments", "comments"},
    "test_case": {"description", "expected", "steps", "comments"},
    "matrix_result": {"comment"},
}

ORDERABLE_FIELDS: dict[str, set[str]] = {
    "bug": {"created", "severity_rank", "bug_key"},
    "test_case": {"source_row", "module", "status"},
    "matrix_result": {"source_row", "dimension", "item"},
}

# Columns returned to the narrator, per entity. Deliberately narrow: the
# narrating call is told to use only these rows, so sending it a 4,000-character
# repro-steps blob per row would crowd out the rows themselves.
SELECT_FIELDS: dict[str, list[str]] = {
    "bug": ["bug_key", "severity", "status", "issue_type", "build", "created",
            "summary", "resolution"],
    "test_case": ["source_row", "module", "section", "status", "was_executed",
                  "description", "comments"],
    "matrix_result": ["item", "section", "dimension", "status", "comment"],
}

# Boolean fields, so a model that writes the string "true" still compiles.
BOOL_FIELDS: frozenset[str] = frozenset({"is_open", "was_executed"})


class Op(str, Enum):
    EQ = "eq"
    NEQ = "neq"
    IN = "in"
    CONTAINS = "contains"


class Condition(BaseModel):
    field: str
    op: Op
    value: Union[str, bool, int, list[str]]


class FilterQuery(BaseModel):
    entity: str
    where: list[Condition] = Field(default_factory=list, max_length=6)
    order_by: str | None = None
    descending: bool = True
    limit: int = Field(default=25, ge=1, le=100)

    @field_validator("entity")
    @classmethod
    def _known_entity(cls, v: str) -> str:
        if v not in ALLOWED_FIELDS:
            raise ValueError(f"unknown entity {v!r}")
        return v


class QueryError(Exception):
    """A filter referenced a field, operator, or entity outside the DSL.

    Raised before any SQL is built, so there is never a partially-constructed
    query — the caller reports the failure and the user rephrases.
    """


def validate_query(q: FilterQuery) -> None:
    allowed = ALLOWED_FIELDS[q.entity] | FTS_FIELDS.get(q.entity, set())
    for cond in q.where:
        if cond.field not in allowed:
            raise QueryError(
                f"field {cond.field!r} is not queryable on {q.entity!r} — "
                f"known fields: {sorted(allowed)}"
            )
        if cond.field in FTS_FIELDS.get(q.entity, set()) and cond.op is not Op.CONTAINS:
            raise QueryError(
                f"field {cond.field!r} is free text and only supports 'contains'"
            )
        if cond.op is Op.IN and not isinstance(cond.value, list):
            raise QueryError(f"op 'in' on {cond.field!r} needs a list value")

    if q.order_by and q.order_by not in ORDERABLE_FIELDS.get(q.entity, set()):
        raise QueryError(
            f"cannot order {q.entity!r} by {q.order_by!r} — known order "
            f"fields: {sorted(ORDERABLE_FIELDS.get(q.entity, set()))}"
        )

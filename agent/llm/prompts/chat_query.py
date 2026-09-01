"""Answer a question by compiling it to the filter DSL, running it, narrating.

Two small model calls rather than one large one.

The first never sees the database — only the field list below, which is why a
hallucinated column fails validation instead of becoming a query. The second
never sees the rest of the snapshot — only the rows the compiled query actually
returned, which keeps every answer traceable to a specific SQL result rather
than to the model's impression of the dataset.

The compiled SQL is returned alongside the answer and shown in the UI. An
answer the reader cannot check against a query is a claim, not a result.
"""

from __future__ import annotations

import json

from pydantic import BaseModel, Field

from ...query.compile import run_query
from ...query.dsl import FilterQuery, QueryError
from ..provider import LLMProvider, LLMUnavailable

TRANSLATE_SYSTEM = """Translate a QA question into a filter query over one of
three entities: "bug", "test_case", "matrix_result".

Only use fields from this list, per entity. Using any other field name is a
hard failure:
- bug: bug_key, severity, status, issue_type, build, is_open, created,
  resolution (plus free-text search with op "contains" on: summary,
  description, steps, actual, expected, dev_comments, comments)
- test_case: status, module, was_executed, section
  (free-text "contains" on: description, expected, steps, comments)
- matrix_result: dimension, status, section, item
  (free-text "contains" on: comment)

Operators: eq, neq, in (value is a list), contains (free-text fields only).
is_open and was_executed take a bare true/false via eq.

Known values — prefer these over inventing spellings:
- severity: Blocker, Critical, Major, Minor, Trivial
- bug status: Open, In Progress, QA Ready, Closed, Deferred
- test/matrix status: Pass, Fail, Some Issue, Blocked, In Progress, Not Run

CRITICAL — "open" is not a status:
"still open", "outstanding", "unresolved", "not fixed" mean is_open eq true.
Do NOT write status eq "Open" for these. "Open" is only ONE of the three
statuses that count as open (Open, In Progress, QA Ready), so filtering on it
silently drops the other two and reports far fewer bugs than exist.
Likewise "closed", "done", "resolved" mean is_open eq false.
Use status only when the user names a specific status.

Same rule for test cases: "not run", "never executed", "untested" mean
was_executed eq false, not status eq "Not Run".

Pick the entity that matches what is being asked: a question about test
coverage is test_case, about translations or locales is matrix_result, about a
defect is bug. If the question does not map to a filterable question at all,
return entity "bug" with an empty where list and limit 1."""


class ChatFilterQuery(BaseModel):
    """Loosely typed on purpose — the model's draft is coerced into the strict
    FilterQuery afterwards, so a malformed draft produces a clear validation
    error rather than a schema rejection with no explanation."""
    entity: str
    where: list[dict] = Field(default_factory=list)
    order_by: str | None = None
    descending: bool = True
    limit: int = 25


TRANSLATE_EXAMPLES = [
    (
        "Which localization bugs are still open?",
        ChatFilterQuery(
            entity="bug",
            where=[
                {"field": "issue_type", "op": "eq", "value": "Localization"},
                {"field": "is_open", "op": "eq", "value": True},
            ],
            limit=25,
        ),
    ),
    (
        "What test cases have never been run?",
        ChatFilterQuery(
            entity="test_case",
            where=[{"field": "was_executed", "op": "eq", "value": False}],
            limit=50,
        ),
    ),
    (
        "Which strings fail in French?",
        ChatFilterQuery(
            entity="matrix_result",
            where=[
                {"field": "dimension", "op": "eq", "value": "French"},
                {"field": "status", "op": "neq", "value": "Pass"},
            ],
            limit=50,
        ),
    ),
    (
        "Any bugs mentioning wall placement?",
        ChatFilterQuery(
            entity="bug",
            where=[{"field": "description", "op": "contains", "value": "wall placement"}],
            limit=10,
        ),
    ),
]


NARRATE_SYSTEM = """Answer the user's question using ONLY the rows given below.
They are the exact and complete result of the query that was run for this
question. Do not reference anything outside these rows.

If the list is empty, say so plainly rather than guessing at a reason. Cite
specific ids or item names when useful. Keep the answer to 2-4 sentences."""


class ChatAnswer(BaseModel):
    answer: str = Field(max_length=800)


NARRATE_EXAMPLES = [
    (
        json.dumps({
            "question": "Which localization bugs are still open?",
            "rows": [
                {"bug_key": "31#", "summary": "Lobby localization fails to reflect on room activity text"},
                {"bug_key": "45#", "summary": "Debug text is displayed for trade button in market"},
            ],
        }),
        ChatAnswer(answer=(
            "Two localization bugs are still open. #31 covers lobby room-activity "
            "text not picking up the selected language, and #45 is debug text "
            "showing on the market trade button. Both are waiting on translations "
            "rather than code."
        )),
    ),
]


class ChatResult(BaseModel):
    answer: str
    entity: str
    row_count: int
    compiled_query: dict
    sql: str
    rows: list[dict]
    used_model: bool
    error: str | None = None


def _clamp(raw: ChatFilterQuery) -> FilterQuery:
    """Coerce the model's draft into a real FilterQuery.

    Anything failing validation raises, and the caller reports it — a
    hallucinated field must produce a clear failure, never a best-effort query
    against the wrong column.
    """
    return FilterQuery(
        entity=raw.entity,
        where=raw.where,
        order_by=raw.order_by,
        descending=raw.descending,
        limit=min(max(raw.limit, 1), 50),
    )


def answer_question(
    provider: LLMProvider, cur, question: str, snapshot_id: str
) -> ChatResult:
    # --- call 1: question -> filter query ---
    try:
        draft: ChatFilterQuery = provider.generate(
            TRANSLATE_SYSTEM, question, ChatFilterQuery, TRANSLATE_EXAMPLES
        )
        query = _clamp(draft)
        rows, sql = run_query(cur, query, snapshot_id)
    except (LLMUnavailable, QueryError, ValueError) as e:
        return ChatResult(
            answer=f"Couldn't turn that into a query: {e}",
            entity="unknown", row_count=0, compiled_query={}, sql="",
            rows=[], used_model=False, error=str(e),
        )

    # --- call 2: rows -> prose ---
    payload = json.dumps({"question": question, "rows": rows[:30]}, default=str)
    try:
        narrated: ChatAnswer = provider.generate(
            NARRATE_SYSTEM, payload, ChatAnswer, NARRATE_EXAMPLES
        )
        answer_text, used = narrated.answer, True
    except LLMUnavailable:
        # The query still ran and the rows are still shown. Losing the narrator
        # costs the prose, not the result.
        answer_text = (
            f"The query ran and returned {len(rows)} row(s), but the model was "
            "unavailable to summarize them. The rows are below."
        )
        used = False

    return ChatResult(
        answer=answer_text,
        entity=query.entity,
        row_count=len(rows),
        compiled_query=query.model_dump(mode="json"),
        sql=sql,
        rows=rows[:50],
        used_model=used,
    )

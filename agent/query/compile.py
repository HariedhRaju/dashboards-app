"""Compile a validated FilterQuery into parameterized SQL and run it.

Every value is bound, never interpolated. Every identifier is interpolated,
but only after `validate_query` has confirmed it is a member of one of the
frozen sets in `dsl.py` — so the strings that reach the query text come from
this repository, and the strings that come from the model are all parameters.
That split is the whole security model, and it is why the compiler refuses to
run a query it was not handed a validated object for.

Results are always scoped to one snapshot. A chat answer that silently mixed
two ingests would be worse than no answer at all.
"""

from __future__ import annotations

from typing import Any

from .dsl import (
    BOOL_FIELDS,
    ENTITY_TABLES,
    FTS_FIELDS,
    SELECT_FIELDS,
    Condition,
    FilterQuery,
    Op,
    QueryError,
    validate_query,
)


def _coerce_bool(value: Any) -> bool:
    """Accept the several ways a model writes a boolean."""
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "yes", "1", "y"}


def _condition_sql(entity: str, cond: Condition, params: list) -> str:
    field = cond.field
    fts = FTS_FIELDS.get(entity, set())

    if cond.field in fts:
        # Bugs carry a generated tsvector; everything else uses ILIKE, which at
        # these row counts is indistinguishable and needs no extra index.
        if entity == "bug":
            params.append(str(cond.value))
            return "search @@ plainto_tsquery('english', %s)"
        params.append(f"%{cond.value}%")
        return f"{field} ILIKE %s"

    if field in BOOL_FIELDS:
        params.append(_coerce_bool(cond.value))
        return f"{field} = %s" if cond.op is not Op.NEQ else f"{field} <> %s"

    if cond.op is Op.IN:
        values = [str(v) for v in cond.value]  # type: ignore[union-attr]
        if not values:
            raise QueryError(f"op 'in' on {field!r} got an empty list")
        params.append(values)
        return f"{field} = ANY(%s)"

    params.append(str(cond.value))
    if cond.op is Op.NEQ:
        return f"{field} <> %s"
    return f"{field} = %s"


def build_sql(q: FilterQuery, snapshot_id: str) -> tuple[str, list]:
    """Return (sql, params). Validates first; raises QueryError if it cannot."""
    validate_query(q)

    table = ENTITY_TABLES[q.entity]
    columns = SELECT_FIELDS[q.entity]

    params: list = [snapshot_id]
    clauses = ["snapshot_id = %s"]
    for cond in q.where:
        clauses.append(_condition_sql(q.entity, cond, params))

    order = ""
    if q.order_by:
        order = f" ORDER BY {q.order_by} {'DESC' if q.descending else 'ASC'} NULLS LAST"

    params.append(q.limit)
    sql = (
        f"SELECT {', '.join(columns)} FROM {table}"
        f" WHERE {' AND '.join(clauses)}{order} LIMIT %s"
    )
    return sql, params


def run_query(cur, q: FilterQuery, snapshot_id: str) -> tuple[list[dict], str]:
    """Execute a validated query. Returns (rows, the SQL that produced them).

    The SQL is returned so the UI can show it under the answer. An answer the
    reader cannot check against a query is a claim, not a result.
    """
    sql, params = build_sql(q, snapshot_id)
    cur.execute(sql, params)
    rows = [dict(r) for r in cur.fetchall()]
    for r in rows:
        for k, v in r.items():
            if hasattr(v, "isoformat"):
                r[k] = v.isoformat()
    return rows, sql

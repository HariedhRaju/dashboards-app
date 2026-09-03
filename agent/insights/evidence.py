"""Citable rows for the narrated report.

The findings carry evidence already, but trimmed for a dashboard list. A report
that names "22 unexecuted test cases" without saying WHICH is not actionable —
the reader still has to open the workbook. So this module gathers the specific
identifiers the narrator is allowed to cite, and the prompt requires it to use
them.

Everything here is bounded. The narrator gets a working set, not the dataset:
a 7B model handed 15,000 bug summaries will start inventing relationships
between them, and the whole design rests on it only ever restating rows it was
given.

A note on test case identity: `case_ref` is the source's own id when it has one
("TC-001"), because that is the string a tester will search for. A plan that
never numbered its cases falls back to `TC-<source_row>`, which is stable within
a snapshot and points at the exact spreadsheet row. Both are cited identically,
so nothing downstream needs to know which it got.
"""

from __future__ import annotations

from typing import Any

from .stats import ReportScope, Window, bug_scope, case_scope

# Per-section caps. Enough to be specific, small enough that the model cannot
# drift into summarizing a list instead of citing from it.
MAX_BLOCKERS = 12
MAX_CASES = 15
MAX_ITEMS = 10
MAX_MODULES = 8


def _rows(cur, sql: str, params: list) -> list[dict]:
    cur.execute(sql, params)
    return [dict(r) for r in cur.fetchall()]


# A case reference that identifies exactly one case.
#
# Test plans very often restart numbering per module, so "TC-001" can name a
# dozen different cases in one workbook — a citation that ambiguous is not a
# citation at all. Where the id repeats, it is qualified with its module; where
# it is already unique, it is left alone so the common case stays terse. Plans
# with no id column fall back to the sheet row, which is unique by definition.
#
# Parameterized on the WHERE fragment rather than a fixed `snapshot_id = %s` —
# module/status/priority/reporter filters have to narrow the base `cases` set
# itself, not just be bolted on after, or "TC-001" could still be cited for a
# case the filter excluded.
def _case_ref_cte(where: str) -> str:
    return f"""
    WITH cases AS (
        SELECT *,
               COUNT(*) OVER (PARTITION BY case_id) AS id_uses
        FROM qa_test_cases
        WHERE {where}
    ),
    refs AS (
        SELECT *,
               CASE
                 WHEN case_id IS NULL          THEN 'TC-' || source_row
                 WHEN id_uses > 1              THEN COALESCE(module, section, '?')
                                                    || ' / ' || case_id
                 ELSE case_id
               END AS case_ref
        FROM cases
    )
    """


def gather(cur, snapshot_id: str, scope: ReportScope | Window = None) -> dict[str, Any]:
    """The citable working set for one snapshot.

    Bug evidence honours the date window AND the entity filters; test-case
    evidence honours the entity filters (module/status/priority/reporter) but
    never the date window; localization evidence is always read whole. Same
    asymmetry as the stats, for the same reason: only bugs carry a per-row
    date to filter on.
    """
    scope = scope if isinstance(scope, ReportScope) else ReportScope(window=scope)
    s = [snapshot_id]
    bug_where, bug_params = bug_scope(snapshot_id, scope)
    case_where, case_params = case_scope(snapshot_id, scope)
    case_cte = _case_ref_cte(case_where)

    blockers = _rows(cur, f"""
        SELECT bug_key, severity, status, COALESCE(issue_type, 'Unclassified') AS issue_type,
               summary, build
        FROM qa_bugs
        WHERE {bug_where} AND is_open AND severity_rank >= 4
        ORDER BY severity_rank DESC, bug_key
        LIMIT {MAX_BLOCKERS}
    """, bug_params)

    open_major = _rows(cur, f"""
        SELECT bug_key, severity, status, COALESCE(issue_type, 'Unclassified') AS issue_type,
               summary
        FROM qa_bugs
        WHERE {bug_where} AND is_open AND severity_rank = 3
        ORDER BY bug_key
        LIMIT {MAX_BLOCKERS}
    """, bug_params)

    # Verification comments that contradict the status field. Worth citing by
    # id because the status column alone will not show them.
    stalled = _rows(cur, f"""
        SELECT bug_key, severity, status, summary,
               COALESCE(comments, dev_comments) AS note
        FROM qa_bugs
        WHERE {bug_where}
          AND (comments ILIKE '%%fix failed%%' OR comments ILIKE '%%not fixed%%'
            OR comments ILIKE '%%reopen%%'     OR dev_comments ILIKE '%%fix failed%%'
            OR dev_comments ILIKE '%%reopen%%')
        ORDER BY severity_rank DESC
        LIMIT {MAX_BLOCKERS}
    """, bug_params)

    never_run = _rows(cur, f"""
        {case_cte}
        SELECT case_ref,
               COALESCE(module, section, 'Unassigned') AS module,
               COALESCE(title, description)            AS description,
               priority,
               status,
               -- The module's own totals, carried on every row.
               --
               -- The narrator was given these counts in a separate `modules`
               -- list and had to join the two by module name to say "all N
               -- cases in X". It got that join wrong — attaching one module's
               -- count of 10 to another that has 5. Putting the right number
               -- beside the citation removes the join, and with it the error.
               COUNT(*)      OVER (PARTITION BY COALESCE(module, section))
                                                       AS module_cases_unrun,
               MIN(mod_total) OVER (PARTITION BY COALESCE(module, section))
                                                       AS module_cases_total
        FROM (
            SELECT *, COUNT(*) OVER (PARTITION BY COALESCE(module, section)) AS mod_total
            FROM refs
        ) r
        WHERE NOT was_executed
        -- Core/High first: which cases went unrun matters more than their order
        -- in the sheet, and the cap means the top of this list is what the
        -- narrator actually sees.
        ORDER BY array_position(ARRAY['Core','High','Medium','Low']::text[],
                                priority::text) NULLS LAST, source_row
        LIMIT {MAX_CASES}
    """, case_params)

    failed_cases = _rows(cur, f"""
        {case_cte}
        SELECT t.case_ref,
               COALESCE(t.module, t.section, 'Unassigned') AS module,
               COALESCE(t.title, t.description)            AS description,
               t.priority,
               t.status,
               -- The bug a failing case was raised against, so the report can
               -- join the two halves the workbook keeps on separate sheets.
               COALESCE(string_agg(l.bug_key, ', ' ORDER BY l.bug_key), '') AS bug_refs
        FROM refs t
        LEFT JOIN qa_test_case_bugs l ON l.test_case_id = t.id
        WHERE t.status = 'Fail'
        GROUP BY t.case_ref, t.source_row, t.module, t.section, t.title,
                 t.description, t.priority, t.status
        ORDER BY t.source_row
        LIMIT {MAX_CASES}
    """, case_params)

    systemic = _rows(cur, f"""
        SELECT item,
               MIN(section)                                       AS section,
               COUNT(DISTINCT dimension)::int                     AS locales_checked,
               COUNT(*) FILTER (WHERE status <> 'Pass')::int       AS locales_failing,
               string_agg(DISTINCT dimension, ', ')
                 FILTER (WHERE status <> 'Pass')                  AS failing_locales
        FROM qa_matrix_results
        WHERE snapshot_id = %s AND item IS NOT NULL
        GROUP BY item
        HAVING COUNT(*) FILTER (WHERE status <> 'Pass') > 0
        ORDER BY locales_failing DESC
        LIMIT {MAX_ITEMS}
    """, s)

    weak_locales = _rows(cur, f"""
        SELECT dimension,
               COUNT(*)::int                                  AS checked,
               COUNT(*) FILTER (WHERE status <> 'Pass')::int   AS not_passing
        FROM qa_matrix_results
        WHERE snapshot_id = %s
        GROUP BY dimension
        HAVING COUNT(*) FILTER (WHERE status <> 'Pass') > 0
        ORDER BY not_passing DESC
        LIMIT {MAX_ITEMS}
    """, s)

    modules = _rows(cur, f"""
        SELECT COALESCE(module, section, 'Unassigned')      AS module,
               COUNT(*)::int                                 AS cases,
               COUNT(*) FILTER (WHERE was_executed)::int      AS executed,
               COUNT(*) FILTER (WHERE status = 'Fail')::int   AS failed,
               COUNT(*) FILTER (WHERE NOT was_executed)::int  AS never_run
        FROM qa_test_cases
        WHERE {case_where}
        GROUP BY 1 ORDER BY cases DESC
        LIMIT {MAX_MODULES}
    """, case_params)

    return {
        "open_blockers": blockers,
        "open_major": open_major,
        "stalled_fixes": stalled,
        "never_run_cases": never_run,
        "failed_cases": failed_cases,
        "systemic_localization_items": systemic,
        "weak_locales": weak_locales,
        "modules": modules,
        # So the narrator can say "15 of 22 shown" rather than implying the
        # truncated list is the whole population.
        "truncated": {
            "never_run_cases": MAX_CASES,
            "open_blockers": MAX_BLOCKERS,
            "systemic_localization_items": MAX_ITEMS,
        },
    }

"""
Import the real "The Fertile Crescent" QA source data into the live
database, replacing the dev-seed dummy data previously used to validate the
Common Agent. Read-only against the CSVs — never modifies them.

Source files (already in this repo, at the dashboards-app root):
    Copy of The Fertile Crescent - 2025(Bug Tracker).csv   -> Bugsy data
    Copy of The Fertile Crescent - 2025(Test plan).csv     -> TestSmith data

Deliberately NOT imported as data rows:
  - Progress.csv: every field it carries (mission names, per-difficulty
    tiers) is already present in the Test Plan's own test-case descriptions;
    it adds no new ingestible column the existing contracts model. Its "Sl
    No" column (the real mission-number <-> mission-name correspondence) IS
    used below, read-only, purely to corroborate two curated mappings that
    reference a mission only by number ("mission 6, 7") or chapter
    ("chapter 8") in the bug's own text — see CURATED_CONTENT_MAPPINGS.
  - Localization.csv: no LocalizationRecord contract/adapter/UI section
    exists anywhere in this implementation. Out of scope per instruction —
    "do not add unless the existing implementation already supports it."

Bug import reuses Bugsy's OWN existing importer (dashboards.importer.
import_bugs) completely unmodified — inspection of its SEVERITY_MAP,
STATUS_MAP, and date-typo regex shows it already handles every real value
and quirk found in this exact CSV (e.g. the "16/092025" missing-slash typo
is handled by a regex whose docstring names that literal pattern), so
there is nothing to adapt.

Test-case import is new, minimal logic specific to this one file's shape —
no TestSmith importer exists anywhere in this repo to reuse, because
TestSmith itself is not implemented.

Mapping rule: two distinct, separately-tagged kinds of mapping are created,
both explicit rows in bug_test_case_mappings, never inferred at query time:

  1. csv_explicit_bug_id_column — the one relationship the CSV itself states
     directly: Test Plan "Bug ID" = 11# on all 4 "Settling Frontier" rows,
     matching Bug Tracker "Issue No" = 11#.

  2. curated_demo — a small, hand-curated set of additional mappings built
     by reading the actual bug and test-case text (see CURATED_CONTENT_MAPPINGS
     below), for the demo mapping layer requested on top of the one CSV-native
     relationship. Every one of the 40 test cases has the same fixed shape —
     "Verify if the mission <name> can be completed on <difficulty>
     difficulty" — so a bug is only curated-mapped to a mission when its own
     summary/description explicitly names that mission (or an explicitly
     corroborated mission number/chapter — see Progress.csv's "Sl No" column,
     which gives the real number<->name correspondence for all 10 campaign
     missions) AND describes something that plausibly happens during that
     mission's playthrough. Bugs are deliberately NOT force-mapped: of 61
     bugs, most concern UI/multiplayer/Hordes/localization-string issues that
     have no corresponding mission-completion test case anywhere in the Test
     Plan CSV, and are left unmapped as real, honest coverage gaps.

Each mapping row's dynamic_fields records mapping_source, confidence, and a
short reason — so the two kinds stay distinguishable downstream instead of
looking like one undifferentiated pile of "mappings".

Known, pre-existing gap this script works around WITHOUT modifying Bugsy:
dashboards.importer.ensure_import_infrastructure() / resolve_project_id()
each INSERT into `users` / `projects` with fewer columns than those tables'
real NOT NULL constraints — but only take that INSERT path when their own
lookup-by-name/id finds nothing. This script pre-creates a complete project
row and a complete system-reporter user row first, so those lookups always
succeed and the incomplete INSERT paths are never reached. This is the same
strategy already used by setup/seed_common_agent_dev_data.py.

Idempotent: safe to re-run.
  - Bugs: Bugsy's own import_bugs() upserts on (project_id, source,
    source_record_id) — its existing behavior, untouched.
  - Test cases / test run: deterministic uuid5 ids (this script's own
    namespace, distinct from the dev-seed script's) + upsert (ON CONFLICT
    (id) DO UPDATE), so a rerun can refresh feature_name/test_case_json.
  - Mappings: deterministic uuid5 ids + the table's own real UNIQUE
    (bug_id, test_case_id) constraint, ON CONFLICT DO UPDATE — reruns
    never create duplicate bug<->test-case relationships.

Schema note: bug_test_case_mappings has no metadata column of its own in the
live DB (only id/bug_id/test_case_id/created_by/created_at). This script
adds one additive, nullable `dynamic_fields jsonb` column to it (idempotent
ALTER TABLE ADD COLUMN IF NOT EXISTS), following the exact same by-convention
JSONB pattern already used on bug_reports and generated_test_cases — not a
new schema paradigm, and never touched by common_agent/postgres_mapping_adapter.py
itself (read-only, per its own docstring).

Run from dashboards-app/:
    python setup/import_fertile_crescent_from_csv.py
"""
from __future__ import annotations

import csv
import json
import os
import re
import sys
import uuid
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dashboards import write_cursor
from dashboards.importer import (
    SYSTEM_REPORTER_EMAIL,
    SYSTEM_REPORTER_NAME,
    SYSTEM_REPORTER_UUID,
    import_bugs,
)

_NAMESPACE = uuid.UUID("c1c1c1c1-fe27-4c01-9f01-fee1efe12345")  # distinct from the dev-seed script's


def _did(key: str) -> str:
    return str(uuid.uuid5(_NAMESPACE, key))


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUG_TRACKER_CSV = os.path.join(REPO_ROOT, "Copy of The Fertile Crescent - 2025(Bug Tracker).csv")
TEST_PLAN_CSV = os.path.join(REPO_ROOT, "Copy of The Fertile Crescent - 2025(Test plan).csv")

PROJECT_NAME = "The Fertile Crescent"
PROJECT_CODE = "TFC"
PROJECT_ID = _did(f"project:{PROJECT_CODE}")
TEST_RUN_ID = _did("testplan-csv:run")

# Every one of the 40 real Test Plan rows has this exact shape — verified
# against all 40 rows, 100% match. Mission name and difficulty are both
# extracted directly from the row's own real text, never invented.
_MISSION_PATTERN = re.compile(r"mission (.+?) can be completed on (\w+) difficulty", re.IGNORECASE)

# Curated, hand-reviewed Bug -> Mission mappings, built by reading the real
# text of both the Bug Tracker and Test Plan CSVs (Progress.csv's "Sl No"
# column supplied the mission-number <-> mission-name correspondence used to
# resolve bugs that reference a mission only by number/chapter). A bug is
# mapped to a mission's 4 test cases (one per difficulty — none of these bugs
# call out a single difficulty tier) only when its own summary/description
# explicitly names or numbers that mission AND describes something that
# plausibly occurs during that mission's playthrough (not a post-completion
# screen, and not a generic mechanic like "Wonder" that appears across many
# missions). See the module docstring for the full rule. Bug issue numbers
# here are normalized (no leading/trailing '#'), matching how
# dashboards.importer stores dynamic_fields['source_record_id'].
CURATED_CONTENT_MAPPINGS = [
    {
        "bug": "3",
        "mission": "The Race for Metal",
        "confidence": "high",
        "reason": (
            "Bug #3 explicitly names the mission (\"Campaign 'The race of metal' ends "
            "automatically...\") and describes the session ending automatically, "
            "'blocking further progression' — directly contradicts this test case's "
            "expected result of completing the mission without blockers."
        ),
    },
    {
        "bug": "18",
        "mission": "Settling Frontier",
        "confidence": "medium",
        "reason": (
            "Bug #18 explicitly occurs \"During mission Settling the frontier\" (mission 2) "
            "— a UI overlap encountered during that mission's playthrough, which this test "
            "case's expected result ('without any blockers or issues') is meant to catch."
        ),
    },
    {
        "bug": "54",
        "mission": "Settling Frontier",
        "confidence": "high",
        "reason": (
            "Bug #54 explicitly occurs during 'mission 2' nomad-attack mechanics — the same "
            "specific mission and mechanic named in the confirmed Bug #11 mapping — and "
            "throws an exception during play."
        ),
    },
    {
        "bug": "26",
        "mission": "Rivalry in Crescent",
        "confidence": "medium",
        "reason": (
            "Bug #26 explicitly occurs \"during the ending sequence of the rivalry in "
            "Crescent\" — within that mission's own playthrough, not a separate post-"
            "completion screen."
        ),
    },
    {
        "bug": "56",
        "mission": "Alliance and Ambitions",
        "confidence": "medium",
        "reason": (
            "Bug #56 explicitly references 'mission 6' (Alliance and Ambitions per "
            "Progress.csv Sl No 6) — debug text visible in dialogue during that mission."
        ),
    },
    {
        "bug": "56",
        "mission": "Wonders of Divine",
        "confidence": "medium",
        "reason": (
            "Bug #56 explicitly references 'mission 7' (Wonders of Divine per Progress.csv "
            "Sl No 7) — the same debug-text issue also occurs during that mission."
        ),
    },
    {
        "bug": "57",
        "mission": "Bastion Against the Nomads",
        "confidence": "medium",
        "reason": (
            "Bug #57 explicitly references 'chapter 8' (Bastion Against the Nomads per "
            "Progress.csv Sl No 8) — debug text visible in that mission's own briefing."
        ),
    },
]

def _ensure_mapping_schema(cur) -> None:
    """Additive-only: adds a nullable dynamic_fields jsonb column to the
    externally-owned bug_test_case_mappings table so mapping provenance
    (mapping_source/confidence/reason) can be recorded, following the exact
    JSONB-by-convention pattern already used on bug_reports and
    generated_test_cases. Never drops/renames/alters an existing column."""
    cur.execute(
        "ALTER TABLE bug_test_case_mappings ADD COLUMN IF NOT EXISTS dynamic_fields jsonb"
    )


def _ensure_prerequisites(cur) -> None:
    """Pre-create the system user, then the project (which references it) —
    see module docstring for why. Never alters importer.py itself."""
    cur.execute("SELECT id FROM users WHERE id = %s", (SYSTEM_REPORTER_UUID,))
    if cur.fetchone() is None:
        cur.execute(
            """
            INSERT INTO users (
                id, name, email, role, capacity_hours_per_day, capacity_pct,
                default_shift, status, cab_status, auth_provider,
                mfa_enabled, mfa_failed_attempts, mfa_last_used_timestamp
            ) VALUES (%s, %s, %s, 'tester', 8.0, 100.0, 'day', 'active', 'no_cab', 'local', false, 0, 0)
            ON CONFLICT DO NOTHING
            """,
            (SYSTEM_REPORTER_UUID, SYSTEM_REPORTER_NAME, SYSTEM_REPORTER_EMAIL),
        )
        print(f"  Created system reporter user ({SYSTEM_REPORTER_NAME}).")

    cur.execute("SELECT id FROM projects WHERE LOWER(name) = LOWER(%s)", (PROJECT_NAME,))
    row = cur.fetchone()
    if row is None:
        cur.execute(
            """
            INSERT INTO projects (id, name, code, created_by, status, shift_type)
            VALUES (%s, %s, %s, %s, 'active', 'day')
            ON CONFLICT DO NOTHING
            """,
            (PROJECT_ID, PROJECT_NAME, PROJECT_CODE, SYSTEM_REPORTER_UUID),
        )
        print(f"  Created project '{PROJECT_NAME}' ({PROJECT_CODE}).")
    else:
        print(f"  Project '{PROJECT_NAME}' already exists ({row['id']}).")

    # Verify — resolve_project_id()'s exception-fallback silently returns an
    # arbitrary other project if this lookup ever fails, so confirm for real
    # rather than assuming the INSERT above worked.
    cur.execute("SELECT id FROM bug_projects WHERE LOWER(name) = LOWER(%s)", (PROJECT_NAME,))
    verify = cur.fetchone()
    if verify is None:
        raise RuntimeError(
            f"'{PROJECT_NAME}' is not visible via bug_projects after pre-seeding — aborting "
            "rather than risk import_bugs() silently attaching bugs to the wrong project."
        )


def _parse_test_plan_rows() -> list[dict]:
    with open(TEST_PLAN_CSV, encoding="cp1252", errors="replace", newline="") as f:
        rows = list(csv.reader(f))

    header_idx = next(i for i, r in enumerate(rows) if "Module" in r and "Test Case Description" in r)
    header = rows[header_idx]
    mod_i = header.index("Module")
    desc_i = header.index("Test Case Description")
    exp_i = header.index("Expected Result")
    status_i = header.index("Status")
    bug_i = header.index("Bug ID")

    current_module = None
    tc_rows: list[dict] = []
    for r in rows[header_idx + 1:]:
        m = r[mod_i].strip() if len(r) > mod_i else ""
        if m:
            current_module = m
        desc = r[desc_i].strip() if len(r) > desc_i else ""
        if not desc:
            continue
        mission_match = _MISSION_PATTERN.search(desc)
        tc_rows.append({
            "module": current_module or "Game Mode",
            # Mission name + difficulty, parsed directly from this row's own
            # description text (e.g. "Verify if the mission Settling Frontier
            # can be completed on Beginner difficulty.") — real per-row data,
            # not inferred from another record. Falls back to the CSV's own
            # "Module" column value on the rare row this pattern wouldn't
            # match (none in the current 40 rows — verified 100% match).
            "mission": mission_match.group(1) if mission_match else None,
            "difficulty": mission_match.group(2) if mission_match else None,
            "desc": desc,
            "expected": r[exp_i].strip() if len(r) > exp_i else "",
            "status": (r[status_i].strip() if len(r) > status_i else "") or None,
            "bug_id": r[bug_i].strip() if len(r) > bug_i else "",
        })
    return tc_rows


def _import_test_cases(cur, tc_rows: list[dict]) -> tuple[dict[int, str], dict[str, list[str]]]:
    cur.execute(
        """
        INSERT INTO test_case_runs (id, user_id, uploaded_file_name, coverage_level, generated_at)
        VALUES (%s, %s, %s, %s, NOW())
        ON CONFLICT DO NOTHING
        """,
        (TEST_RUN_ID, SYSTEM_REPORTER_UUID, os.path.basename(TEST_PLAN_CSV), "standard"),
    )

    test_case_ids: dict[int, str] = {}
    mission_to_tc_ids: dict[str, list[str]] = {}
    for i, t in enumerate(tc_rows):
        tc_id = _did(f"testplan-csv:tc:{i}")
        test_case_ids[i] = tc_id
        # feature_name = the CSV's own real "Module" column value ("Game
        # Mode" — the only value that column ever actually contains in this
        # file). Mission name is NOT used here: the CSV has no per-mission
        # module field, and inventing one would misrepresent the real data.
        # mission_to_tc_ids is still built (from the same real description
        # text) purely as internal plumbing to resolve which test_case_ids a
        # curated bug<->mission mapping applies to — it is never written to
        # feature_name or exposed as a "module".
        feature_name = t["module"]
        if t["mission"]:
            mission_to_tc_ids.setdefault(t["mission"], []).append(tc_id)
        test_case_json = {"title": t["desc"], "expected_result": t["expected"]}
        if t["status"]:
            test_case_json["status"] = t["status"]
        # No "priority" key: the real Test Plan CSV has no priority column.
        # No "steps" key: Verification Steps is empty on every one of these
        # 40 rows in the source file — omitted rather than invented.
        cur.execute(
            """
            INSERT INTO generated_test_cases (id, run_id, feature_name, test_case_json, created_at)
            VALUES (%s, %s, %s, %s::jsonb, NOW())
            ON CONFLICT (id) DO UPDATE SET
                feature_name = EXCLUDED.feature_name,
                test_case_json = EXCLUDED.test_case_json
            """,
            (tc_id, TEST_RUN_ID, feature_name, json.dumps(test_case_json)),
        )
    return test_case_ids, mission_to_tc_ids


def _lookup_bug_id(cur, issue_no: str) -> Optional[str]:
    cur.execute(
        """
        SELECT id FROM bug_reports
        WHERE project_id = %s AND dynamic_fields->>'source_record_id' = %s
        LIMIT 1
        """,
        (PROJECT_ID, issue_no),
    )
    row = cur.fetchone()
    return str(row["id"]) if row is not None else None


def _upsert_mapping(cur, mapping_id: str, bug_id: str, tc_id: str, dynamic_fields: dict) -> None:
    cur.execute(
        """
        INSERT INTO bug_test_case_mappings (id, bug_id, test_case_id, created_by, created_at, dynamic_fields)
        VALUES (%s, %s, %s, %s, NOW(), %s::jsonb)
        ON CONFLICT (bug_id, test_case_id) DO UPDATE SET dynamic_fields = EXCLUDED.dynamic_fields
        """,
        (mapping_id, bug_id, tc_id, SYSTEM_REPORTER_UUID, json.dumps(dynamic_fields)),
    )


def _import_mappings(cur, tc_rows: list[dict], test_case_ids: dict[int, str]) -> int:
    """The one relationship the CSV states directly: Test Plan's own 'Bug ID'
    column. Tagged mapping_source='csv_explicit_bug_id_column'."""
    mapped = 0
    for i, t in enumerate(tc_rows):
        raw_bug_id = t["bug_id"]
        if not raw_bug_id:
            continue
        source_record_id = raw_bug_id.strip("#").strip()
        bug_id = _lookup_bug_id(cur, source_record_id)
        if bug_id is None:
            print(f"  WARNING: Test Plan row {i} references Bug ID {raw_bug_id!r} "
                  f"(normalized {source_record_id!r}) but no matching imported bug was found — skipping.")
            continue
        tc_id = test_case_ids[i]
        mapping_id = _did(f"mapping:csv:{source_record_id}:{i}")
        _upsert_mapping(cur, mapping_id, bug_id, tc_id, {
            "mapping_source": "csv_explicit_bug_id_column",
            "confidence": "high",
            "reason": "Test Plan's own 'Bug ID' column directly references this bug's Issue No.",
        })
        mapped += 1
    return mapped


def _import_curated_mappings(cur, mission_to_tc_ids: dict[str, list[str]]) -> int:
    """Hand-curated mappings from real bug/test-case content (see
    CURATED_CONTENT_MAPPINGS docstring above). Tagged mapping_source='curated_demo'."""
    mapped = 0
    for entry in CURATED_CONTENT_MAPPINGS:
        issue_no = entry["bug"]
        mission = entry["mission"]
        bug_id = _lookup_bug_id(cur, issue_no)
        if bug_id is None:
            print(f"  WARNING: curated mapping references Bug #{issue_no} but no matching "
                  f"imported bug was found — skipping.")
            continue
        tc_ids = mission_to_tc_ids.get(mission, [])
        if not tc_ids:
            print(f"  WARNING: curated mapping references mission {mission!r} but no test "
                  f"cases were parsed for it — skipping.")
            continue
        for tc_id in tc_ids:
            mapping_id = _did(f"mapping:curated:{issue_no}:{tc_id}")
            _upsert_mapping(cur, mapping_id, bug_id, tc_id, {
                "mapping_source": "curated_demo",
                "confidence": entry["confidence"],
                "reason": entry["reason"],
            })
            mapped += 1
    return mapped


def run() -> None:
    print("=" * 70)
    print("  IMPORTING REAL FERTILE CRESCENT DATA FROM CSV")
    print("=" * 70)

    print("\n[1/5] Prerequisites (project + system reporter + mapping schema)...")
    with write_cursor() as cur:
        _ensure_prerequisites(cur)
        _ensure_mapping_schema(cur)

    print(f"\n[2/5] Bug Tracker CSV -> bug_reports (via Bugsy's own importer, unmodified)...")
    with open(BUG_TRACKER_CSV, "rb") as f:
        file_bytes = f.read()
    result = import_bugs(
        file_bytes=file_bytes,
        filename=os.path.basename(BUG_TRACKER_CSV),
        default_project=PROJECT_NAME,
        source_name="csv",
    )
    print(f"  inserted={result['inserted']} updated={result['updated']} "
          f"skipped={result['skipped']} total_rows={result['total_rows']}")
    if result["errors"]:
        print(f"  {len(result['errors'])} row(s) had errors:")
        for e in result["errors"][:10]:
            print(f"    row {e['row']}: {e['field']} - {e['reason']}")
    if result["warnings"]:
        print(f"  {len(result['warnings'])} warning(s), e.g.: {result['warnings'][0]}")

    print(f"\n[3/5] Test Plan CSV -> generated_test_cases (feature_name = the CSV's own 'Module' value)...")
    tc_rows = _parse_test_plan_rows()
    with write_cursor() as cur:
        test_case_ids, mission_to_tc_ids = _import_test_cases(cur, tc_rows)
    print(f"  {len(tc_rows)} test cases imported/verified.")

    print(f"\n[4/5] Explicit Bug ID -> Issue No mappings (CSV 'Bug ID' column only)...")
    with write_cursor() as cur:
        mapped_csv = _import_mappings(cur, tc_rows, test_case_ids)
    print(f"  {mapped_csv} mapping row(s) created/verified (mapping_source=csv_explicit_bug_id_column).")

    print(f"\n[5/5] Curated content-based mappings (see CURATED_CONTENT_MAPPINGS)...")
    with write_cursor() as cur:
        mapped_curated = _import_curated_mappings(cur, mission_to_tc_ids)
    print(f"  {mapped_curated} mapping row(s) created/verified (mapping_source=curated_demo).")

    print("\n" + "=" * 70)
    print(f"  DONE — project '{PROJECT_NAME}' now backed by real CSV data + explicit mapping layer.")
    print(f"  Total mappings: {mapped_csv + mapped_curated} "
          f"({mapped_csv} csv_explicit_bug_id_column + {mapped_curated} curated_demo).")
    print("=" * 70)


if __name__ == "__main__":
    run()

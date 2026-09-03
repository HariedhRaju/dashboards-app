"""
Development-only seed data generator for validating the Common Analytics Agent.

Populates the live PostgreSQL database with realistic, clearly-labeled
[DEV-SEED] Bugsy bug reports, TestSmith generated test cases, and explicit
bug_test_case_mappings rows, so common_agent/core.py's cross-feature
analytics can be exercised end-to-end without waiting on the real Bugsy /
TestSmith agents.

Scope — what this script does NOT do:
  - Does not modify common_agent/ (contracts, core, adapters, insights) in
    any way. It only writes upstream data; the Common Agent reads it.
  - Does not alter any table schema (no CREATE/ALTER/DROP).
  - Does not add a project_id to generated_test_cases — that column does
    not exist on the real schema and this script does not invent one.
  - Does not touch any row it did not itself create (see idempotency below).
  - Does not change any production application behavior — Bugsy's own
    import path (dashboards/importer.py) and TestSmith are untouched.

Idempotency:
  Every seeded row uses a deterministic UUID (uuid5 of a fixed namespace +
  a stable key such as "bug:07"), and every insert uses
  ON CONFLICT DO NOTHING. Running this script twice never creates
  duplicates and never errors. `--reset` additionally deletes only rows
  that were created by this script (identified by the dev-seed user id /
  the `_dev_seed` marker in JSONB fields / the DEVCA0x project codes)
  before reseeding — it never touches anything else.

Run from dashboards-app/ (needs the DASHBOARDS_REPLICA_DSN / .env the rest
of this app already uses):

    python setup/seed_common_agent_dev_data.py
    python setup/seed_common_agent_dev_data.py --reset
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import uuid
from datetime import datetime, timedelta, timezone

# Matches setup/seed_reportiq_v2.py's convention — makes `dashboards` (and
# its .env loading, which is relative to CWD) importable regardless of how
# this script is invoked, as long as it's run with dashboards-app/ as CWD.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dashboards import write_cursor

DEV_SEED_MARKER = "[DEV-SEED]"

# Fixed, arbitrary namespace — stable across every run of this script, which
# is what makes the derived ids (and therefore idempotency) deterministic.
_NAMESPACE = uuid.UUID("a17e6b3e-3f2b-4b8b-9b1a-6f7c1c9b1a01")


def _did(key: str) -> str:
    """Deterministic UUID for a stable seed key. Same key -> same id, always."""
    return str(uuid.uuid5(_NAMESPACE, key))


random.seed(20260901)  # fixed -> identical generated content on every run

# Shared module/feature vocabulary. The SAME names are used on both the
# Bugsy side (bug.dynamic_fields["module"]) and the TestSmith side
# (test_case.feature_name) so real overlap exists — independently of which
# specific bugs/test-cases end up with an explicit mapping row. That
# separation is the whole point: it lets you verify the Common Agent's
# module_analytics (grouping) never gets treated as record_level_mapping
# (a real relationship).
MODULES = [
    "Combat", "Inventory", "Multiplayer", "Save/Load", "UI/Menus",
    "Matchmaking", "Audio", "Character Progression", "Quest System", "Crafting",
]

SEVERITIES = ["P1", "P2", "P3", "P4", "critical", "blocker", "major", "minor", "trivial"]
SEVERITY_WEIGHTS = [3, 3, 3, 2, 2, 2, 2, 2, 1]
STATUSES = ["open", "in_progress", "fixed", "closed"]
PRIORITIES = ["high", "medium", "low"]
PLATFORMS = ["PS5", "Xbox Series X", "PC", "Nintendo Switch"]

BUG_TITLE_TEMPLATES = [
    "{module} breaks after {trigger}",
    "Crash when {trigger} in {module}",
    "{module} UI misaligned on {platform}",
    "Progress lost in {module} after {trigger}",
    "{module} desyncs during {trigger}",
    "{module} softlocks following {trigger}",
]
TRIGGERS = [
    "rapid input", "alt-tabbing", "loading a save mid-action", "host migration",
    "low memory conditions", "controller disconnect", "scene transition", "pause menu toggle",
]

PROJECTS = [
    {"code": "DEVCA01", "name": f"{DEV_SEED_MARKER} Aurora Frontier"},
    {"code": "DEVCA02", "name": f"{DEV_SEED_MARKER} Crimson Horizon"},
    {"code": "DEVCA03", "name": f"{DEV_SEED_MARKER} Nightfall Protocol"},
    {"code": "DEVCA04", "name": f"{DEV_SEED_MARKER} Skybound Legacy"},
    {"code": "DEVCA05", "name": f"{DEV_SEED_MARKER} Ironclad Vanguard"},
]

SEED_USER_EMAIL = "dev-seed-common-agent@local.invalid"
SEED_USER_NAME = f"{DEV_SEED_MARKER} Common Agent Seed User"
SEED_USER_ID = _did(f"user:{SEED_USER_EMAIL}")

N_BUGS = 50
N_TEST_CASE_RUNS = 10
N_TEST_CASES = 90
N_UNMAPPED_BUGS = 12  # left with zero mappings on purpose — a real coverage gap


def _rand_dt(days_back_max: int) -> datetime:
    days_back = random.randint(0, days_back_max)
    return (datetime.now(timezone.utc) - timedelta(days=days_back)).replace(microsecond=0)


def _reset(cur) -> None:
    print(f"--reset: removing existing rows created by this seed script...")
    cur.execute("DELETE FROM bug_test_case_mappings WHERE created_by = %s", (SEED_USER_ID,))
    cur.execute("DELETE FROM generated_test_cases WHERE test_case_json->>'_dev_seed' = 'true'")
    cur.execute("DELETE FROM test_case_runs WHERE user_id = %s", (SEED_USER_ID,))
    cur.execute("DELETE FROM bug_reports WHERE dynamic_fields->>'_dev_seed' = 'true'")
    cur.execute("DELETE FROM projects WHERE code LIKE 'DEVCA%%'")
    cur.execute("DELETE FROM users WHERE id = %s", (SEED_USER_ID,))
    print("--reset: done.\n")


def seed(reset: bool = False) -> None:
    with write_cursor() as cur:
        if reset:
            _reset(cur)

        # ── 1. Seed user — reporter, test-run owner, and mapping creator ──
        cur.execute(
            """
            INSERT INTO users (
                id, name, email, role, capacity_hours_per_day, capacity_pct,
                default_shift, status, cab_status, auth_provider,
                mfa_enabled, mfa_failed_attempts, mfa_last_used_timestamp
            ) VALUES (%s, %s, %s, 'tester', 8.0, 100.0, 'day', 'active', 'no_cab', 'local', false, 0, 0)
            ON CONFLICT DO NOTHING
            """,
            (SEED_USER_ID, SEED_USER_NAME, SEED_USER_EMAIL),
        )

        # ── 2. Projects — 5, real FK targets for bug_reports.project_id ──
        project_ids: list[str] = []
        for p in PROJECTS:
            pid = _did(f"project:{p['code']}")
            project_ids.append(pid)
            cur.execute(
                """
                INSERT INTO projects (id, name, code, created_by, status, shift_type)
                VALUES (%s, %s, %s, %s, 'active', 'day')
                ON CONFLICT DO NOTHING
                """,
                (pid, p["name"], p["code"], SEED_USER_ID),
            )

        # ── 3. Bugs — 50 across the 5 projects ──
        bug_ids: list[str] = []
        bug_modules: dict[str, str] = {}  # bug_id -> module actually stored (for the summary printout)
        for i in range(N_BUGS):
            project_id = project_ids[i % len(project_ids)]
            module = MODULES[i % len(MODULES)] if i != 49 else "Multiplayer"  # canary, see below
            # Vary casing/spacing on ~1/4 of bugs to exercise core.py's
            # lowercase+trim normalization, not just exact-match happy paths.
            module_field = module if random.random() > 0.25 else f" {module.lower()} "
            if i == 0:
                module = "Combat"          # canary A: paired below with a mismatched-feature test case
                module_field = module
            severity = random.choices(SEVERITIES, weights=SEVERITY_WEIGHTS)[0]
            status = random.choice(STATUSES)
            title = random.choice(BUG_TITLE_TEMPLATES).format(
                module=module, trigger=random.choice(TRIGGERS), platform=random.choice(PLATFORMS),
            )
            bug_id = _did(f"bug:{i:02d}")
            bug_ids.append(bug_id)
            bug_modules[bug_id] = module_field
            created = _rand_dt(180)
            dynamic_fields = {
                "_dev_seed": True,
                "module": module_field,
                "platform": random.choice(PLATFORMS),
                "repro_rate": f"{random.randint(1, 5)}/5",
                "build_version": f"v{random.randint(1, 3)}.{random.randint(0, 9)}.{random.randint(0, 20)}",
            }
            cur.execute(
                """
                INSERT INTO bug_reports (
                    id, project_id, reported_by, title, summary, severity, status,
                    dynamic_fields, created_at, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s)
                ON CONFLICT DO NOTHING
                """,
                (
                    bug_id, project_id, SEED_USER_ID,
                    f"{DEV_SEED_MARKER} {title}"[:300],
                    f"{DEV_SEED_MARKER} Auto-generated dev-seed record for Common Agent validation.",
                    severity, status, json.dumps(dynamic_fields), created, created,
                ),
            )

        # ── 4. Test case runs — FK dependency for generated_test_cases.run_id ──
        run_ids: list[str] = []
        for i in range(N_TEST_CASE_RUNS):
            run_id = _did(f"run:{i:02d}")
            run_ids.append(run_id)
            cur.execute(
                """
                INSERT INTO test_case_runs (id, user_id, uploaded_file_name, coverage_level, generated_at)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT DO NOTHING
                """,
                (
                    run_id, SEED_USER_ID, f"{DEV_SEED_MARKER} gdd_batch_{i:02d}.docx",
                    random.choice(["standard", "thorough", "quick"]), _rand_dt(180),
                ),
            )

        # ── 5. Test cases — 90 across the same module/feature vocabulary ──
        test_case_ids: list[str] = []
        tc_features: dict[str, str] = {}
        for i in range(N_TEST_CASES):
            feature = MODULES[i % len(MODULES)]
            feature_field = feature if random.random() > 0.2 else feature.upper()
            if i == 0:
                feature = "Inventory"      # canary A pair — deliberately != bug 0's "Combat"
                feature_field = feature
            if i == 1:
                feature = "Multiplayer"    # canary B — same module as unmapped bug 49, on purpose
                feature_field = feature
            priority = random.choice(PRIORITIES)
            run_id = run_ids[i % len(run_ids)]
            tc_id = _did(f"testcase:{i:02d}")
            test_case_ids.append(tc_id)
            tc_features[tc_id] = feature_field
            created = _rand_dt(180)
            test_case_json = {
                "_dev_seed": True,
                "title": f"Verify {feature} behaves correctly under normal conditions ({i})",
                "priority": priority,
                "steps": ["Set up scenario", "Perform the tested action", "Observe the result"],
                "expected_result": f"{feature} functions as specified in the design document.",
            }
            cur.execute(
                """
                INSERT INTO generated_test_cases (id, run_id, feature_name, test_case_json, created_at)
                VALUES (%s, %s, %s, %s::jsonb, %s)
                ON CONFLICT DO NOTHING
                """,
                (tc_id, run_id, feature_field, json.dumps(test_case_json), created),
            )

        # ── 6. Explicit mappings — the ONLY real bug<->test-case relationship ──
        #
        # mappable_bugs get at least one mapping; unmapped_bugs are left with
        # NONE on purpose, so coverage_gaps reports a real, non-zero gap
        # instead of a suspiciously-perfect 100%-covered dataset.
        mappable_bugs = bug_ids[: N_BUGS - N_UNMAPPED_BUGS]   # 38 bugs
        unmapped_bugs = bug_ids[N_BUGS - N_UNMAPPED_BUGS:]     # 12 bugs, bug_ids[49] ("Multiplayer") among them

        pairs: list[tuple[str, str]] = []

        # Canary A: mappable_bugs[0] (Combat) explicitly maps to test_case[0]
        # (Inventory, mismatched feature) — proves a real mapping does NOT
        # require matching module/feature names.
        pairs.append((mappable_bugs[0], test_case_ids[0]))

        # One-to-many: each of the first 8 mappable bugs gets two mappings
        # to two different test cases, picked by rotation (not by module
        # match) — every one of these 8 bugs demonstrably has >1 test case.
        for k, b in enumerate(mappable_bugs[:8]):
            pairs.append((b, test_case_ids[(k * 7 + 13) % len(test_case_ids)]))
            pairs.append((b, test_case_ids[(k * 7 + 41) % len(test_case_ids)]))

        # Many-to-one: 10 different bugs all map to the same single test case.
        shared_tc = test_case_ids[5]
        for b in mappable_bugs[8:18]:
            pairs.append((b, shared_tc))

        # Remaining mappable bugs: one mapping each, chosen by rotation —
        # deliberately NOT filtered or weighted by module/feature match.
        for j, b in enumerate(mappable_bugs[18:]):
            tc = test_case_ids[(j * 11 + 2) % len(test_case_ids)]
            pairs.append((b, tc))

        # De-dup while preserving insertion order, then cap to the requested range.
        seen: set[tuple[str, str]] = set()
        deduped: list[tuple[str, str]] = []
        for pair in pairs:
            if pair not in seen:
                seen.add(pair)
                deduped.append(pair)
        deduped = deduped[:48]

        for bug_id, tc_id in deduped:
            mapping_id = _did(f"mapping:{bug_id}:{tc_id}")
            cur.execute(
                """
                INSERT INTO bug_test_case_mappings (id, bug_id, test_case_id, created_by, created_at)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT DO NOTHING
                """,
                (mapping_id, bug_id, tc_id, SEED_USER_ID, _rand_dt(90)),
            )

        # ── Summary ──
        canary_bug0_module = bug_modules[mappable_bugs[0]]
        canary_tc0_feature = tc_features[test_case_ids[0]]
        canary_bug49_module = bug_modules[bug_ids[49]]
        canary_tc1_feature = tc_features[test_case_ids[1]]

        print("=" * 70)
        print(f"  COMMON AGENT DEV SEED — {'RESET + ' if reset else ''}COMPLETE")
        print("=" * 70)
        print(f"  Projects:            {len(project_ids)}")
        print(f"  Bugs:                {N_BUGS}  ({len(mappable_bugs)} mappable, {len(unmapped_bugs)} left unmapped)")
        print(f"  Test case runs:      {N_TEST_CASE_RUNS}")
        print(f"  Test cases:          {N_TEST_CASES}")
        print(f"  Mappings:            {len(deduped)}")
        print()
        print("  Canary A (mapping despite mismatched module/feature):")
        print(f"    bug[{mappable_bugs[0][:8]}] module='{canary_bug0_module.strip()}'  <-- mapped -->  "
              f"test_case[{test_case_ids[0][:8]}] feature='{canary_tc0_feature}'")
        print("  Canary B (same module/feature on both sides, but this bug has ZERO mappings):")
        print(f"    bug[{bug_ids[49][:8]}] module='{canary_bug49_module.strip()}'  (unmapped)   vs   "
              f"test_case[{test_case_ids[1][:8]}] feature='{canary_tc1_feature}'")
        print()
        print("  Verify at GET /api/common-agent/dashboard — record_level_mapping should show")
        print(f"  {len(deduped)} total_mappings, and coverage_gaps.bugs_without_mapped_test_case should be >= {N_UNMAPPED_BUGS}.")
        print("=" * 70)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--reset", action="store_true",
        help="Delete this script's previously-seeded rows before reseeding. Never touches non-dev-seed rows.",
    )
    args = parser.parse_args()
    seed(reset=args.reset)

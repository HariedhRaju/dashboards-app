"""
Rich multi-project dataset generator for Bugsy Bug Tracker.

Populates PostgreSQL database with 3 diverse game projects and 250+ realistic bugs
containing diverse dates, severities, statuses, reporters, and dynamic JSONB fields.
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta
from uuid import uuid4

from dashboards import write_cursor, replica_cursor
from dashboards.importer import ensure_import_infrastructure, resolve_project_id


def seed_rich_dataset():
    print("==========================================================")
    print("  SEEDING POSTGRESQL WITH RICH MULTI-PROJECT BUG DATASET  ")
    print("==========================================================\n")

    random.seed(42)  # Deterministic seed for reproducible rich dataset

    with write_cursor() as cur:
        system_user_id = ensure_import_infrastructure(cur)

        # 1. Projects Setup
        projects = [
            {"name": "The Fertile Crescent", "code": "TFC"},
            {"name": "CyberStrike 2099", "code": "CS2099"},
            {"name": "Mythic Realms Online", "code": "MRO"},
        ]

        proj_ids = {}
        for p in projects:
            p_id = resolve_project_id(cur, p["name"], system_user_id)
            proj_ids[p["code"]] = p_id
            print(f"   Project Ready: '{p['name']}' ({p['code']}) -> ID: {p_id}")

        # 2. QA Reporters Setup
        reporters = [
            ("Alex Mercer", "alex.mercer@qa.studio.com"),
            ("Sarah Connor", "sarah.connor@qa.studio.com"),
            ("David Chen", "david.chen@qa.studio.com"),
            ("Maria Garcia", "maria.garcia@qa.studio.com"),
            ("James Wilson", "james.wilson@qa.studio.com"),
            ("Excel Import", "excel.import@bugsy.internal"),
        ]

        user_ids = []
        for name, email in reporters:
            cur.execute("SELECT id FROM users WHERE email = %s", (email,))
            row = cur.fetchone()
            if row:
                user_ids.append(str(row["id"]))
            else:
                uid = str(uuid4())
                cur.execute(
                    """
                    INSERT INTO users (id, name, email, role, mfa_enabled, mfa_failed_attempts, mfa_last_used_timestamp, auth_provider)
                    VALUES (%s, %s, %s, 'tester', false, 0, 0, 'local')
                    """,
                    (uid, name, email)
                )
                user_ids.append(uid)

        print(f"   {len(user_ids)} QA Reporters Active.")

        # Clean existing test bugs to replace with fresh rich dataset
        cur.execute("DELETE FROM bug_reports;")
        print("   Cleared previous bug reports.\n")

        # 3. Bug Generation Logic
        now = datetime.now()
        bugs_to_insert = []

        # --- Project 1: The Fertile Crescent (RTS / Strategy) --- 100 Bugs
        tfc_issue_types = ["Gameplay", "Pathfinding", "UI", "AI Behavior", "Audio", "Networking", "Localization", "Graphics"]
        tfc_components = ["Fog of War", "Unit Control", "Resource Economy", "Minimap", "HUD", "Tech Tree", "Multiplayer Lobby"]
        tfc_builds = ["v1.2.0-b42", "v1.2.1-rc1", "v1.3.0-dev"]
        tfc_repro = ["5/5", "4/5", "3/5", "2/5", "1/5"]
        tfc_titles = [
            "Archers freeze near river crossing when ordered to attack",
            "Villager pathfinding gets stuck behind lumber mill",
            "Fog of War fails to update after tower destruction",
            "Minimap icons disappear when zooming out rapidly",
            "Resource count displays negative values during quick trade",
            "AI opponent stops recruiting cavalry after 20 minutes",
            "Multiplayer session desyncs when player 3 surrenders",
            "Localization text overlaps on 4K resolution displays",
            "Catapult projectile audio loops indefinitely",
            "Tech tree research button unresponsive during pause"
        ]

        for i in range(1, 101):
            created_days_ago = random.randint(1, 90)
            created_dt = now - timedelta(days=created_days_ago, hours=random.randint(0, 23))
            
            # Status & Resolution logic
            status = random.choices(["closed", "fixed", "in_progress", "open"], weights=[40, 25, 20, 15])[0]
            updated_dt = created_dt
            if status in ("closed", "fixed"):
                updated_dt = created_dt + timedelta(hours=random.randint(2, 120))

            severity = random.choices(["P1", "P2", "P3", "P4"], weights=[15, 35, 35, 15])[0]
            reporter_id = random.choice(user_ids)
            title = f"{random.choice(tfc_titles)} #{i}"
            issue_t = random.choice(tfc_issue_types)

            dynamic_fields = {
                "source": "excel",
                "source_record_id": f"TFC-{1000 + i}",
                "issue_type": issue_t,
                "repro_rate": random.choice(tfc_repro),
                "build_version": random.choice(tfc_builds),
                "component": random.choice(tfc_components),
                "platform": random.choice(["PC (Steam)", "Mac (App Store)"]),
                "steps": f"1. Launch TFC on {random.choice(tfc_builds)}\n2. Select {issue_t} module\n3. Observe behavior.",
                "actual_result": f"Unexpected behavior in {issue_t}.",
                "expected_result": "System should operate smoothly according to spec."
            }

            bugs_to_insert.append((
                str(uuid4()), proj_ids["TFC"], reporter_id, title,
                f"Automated bug report for {title}", severity, status,
                created_dt, updated_dt, dynamic_fields
            ))

        # --- Project 2: CyberStrike 2099 (Sci-Fi FPS / Action RPG) --- 90 Bugs
        cs_issue_types = ["Crash", "Physics", "VFX", "Weapon Balance", "RayTracing", "Save System", "Memory Leak", "Audio Distortion"]
        cs_gpus = ["NVIDIA GeForce RTX 4090", "NVIDIA GeForce RTX 3080", "AMD Radeon RX 7900 XT", "Intel Arc A770"]
        cs_platforms = ["PlayStation 5", "Xbox Series X", "PC (Windows 11)"]
        cs_builds = ["v2.0.4-live", "v2.1.0-ptb", "v2.2.0-nightly"]
        cs_titles = [
            "Crash to Desktop when equipping Plasma Rifle with RayTracing ON",
            "FPS drops from 120 to 15 in Neo-Tokyo Neon Alley",
            "Memory leak consumes 12GB VRAM after 45 minutes of combat",
            "Character falls through floor during dash ability near CyberTower",
            "Save game corruption when quitting during boss cutscene",
            "Grenade explosion VFX produces blinding white flash",
            "Audio distortion and static buzz in Cyberware Augmentation menu",
            "Smart Shotgun bullet tracking ignores flying drone enemies",
            "Holographic UI element stuck on screen after terminal hack",
            "DLSS 3 Frame Generation causes ghosting on weapon scopes"
        ]

        for i in range(1, 91):
            created_days_ago = random.randint(1, 90)
            created_dt = now - timedelta(days=created_days_ago, hours=random.randint(0, 23))

            status = random.choices(["closed", "fixed", "in_progress", "open"], weights=[30, 30, 25, 15])[0]
            updated_dt = created_dt
            if status in ("closed", "fixed"):
                updated_dt = created_dt + timedelta(hours=random.randint(1, 96))

            severity = random.choices(["P1", "P2", "P3", "P4"], weights=[25, 40, 25, 10])[0]
            reporter_id = random.choice(user_ids)
            title = f"{random.choice(cs_titles)} #{i}"
            issue_t = random.choice(cs_issue_types)

            dynamic_fields = {
                "source": "jira",
                "source_record_id": f"CS-{2000 + i}",
                "issue_type": issue_t,
                "repro_rate": random.choice(["5/5", "4/5", "2/5", "1/10"]),
                "build_version": random.choice(cs_builds),
                "gpu_vendor": random.choice(cs_gpus),
                "platform": random.choice(cs_platforms),
                "memory_leak_mb": str(random.choice([256, 512, 1024, 2048, 4096])),
                "dev_resolution": "Fixed shader compilation cache" if status == "closed" else "Investigating stack trace"
            }

            bugs_to_insert.append((
                str(uuid4()), proj_ids["CS2099"], reporter_id, title,
                f"Performance and graphics telemetry report: {title}", severity, status,
                created_dt, updated_dt, dynamic_fields
            ))

        # --- Project 3: Mythic Realms Online (Fantasy MMORPG) --- 80 Bugs
        mro_issue_types = ["Quest Blocker", "Economy Exploit", "Boss Mechanics", "Server Desync", "Guild System", "Inventory Duplication"]
        mro_regions = ["NA-East", "EU-Central", "AP-Southeast", "SA-East"]
        mro_builds = ["v3.4.1-live", "v3.5.0-ptr"]
        mro_titles = [
            "Main Questline blocked at Dragon Citadel due to NPC spawn timer",
            "Item duplication exploit using trade cancel feature during lag",
            "Guild Vault permission bypass allows non-officers to withdraw gold",
            "Raid Boss Dragon tail swipe hitbox extends outside visual arena",
            "Server desync disconnects all players in Auction House zone",
            "Mount speed bonus persists after dismounting in PvP zone",
            "Crafting recipes consume double materials when shift-clicking",
            "Chat channel filters fail to block spam URLs",
            "Potion cooldown timer resets when changing gear presets",
            "Achievement reward title not unlocking after completing dungeon"
        ]

        for i in range(1, 81):
            created_days_ago = random.randint(1, 90)
            created_dt = now - timedelta(days=created_days_ago, hours=random.randint(0, 23))

            status = random.choices(["closed", "fixed", "in_progress", "open"], weights=[50, 20, 15, 15])[0]
            updated_dt = created_dt
            if status in ("closed", "fixed"):
                updated_dt = created_dt + timedelta(hours=random.randint(4, 168))

            severity = random.choices(["P1", "P2", "P3", "P4"], weights=[20, 35, 30, 15])[0]
            reporter_id = random.choice(user_ids)
            title = f"{random.choice(mro_titles)} #{i}"
            issue_t = random.choice(mro_issue_types)

            dynamic_fields = {
                "source": "csv",
                "source_record_id": f"MRO-{5000 + i}",
                "issue_type": issue_t,
                "repro_rate": random.choice(["5/5", "3/5", "1/5"]),
                "build_version": random.choice(mro_builds),
                "region": random.choice(mro_regions),
                "server_cluster": f"Realm-0{random.randint(1, 9)}",
                "comments": f"Reported by community QA team on {random.choice(mro_regions)}."
            }

            bugs_to_insert.append((
                str(uuid4()), proj_ids["MRO"], reporter_id, title,
                f"MMO Live Operations issue: {title}", severity, status,
                created_dt, updated_dt, dynamic_fields
            ))

        # Batch insert into bug_reports
        insert_sql = """
            INSERT INTO bug_reports (
                id, project_id, reported_by, title, summary, severity, status,
                created_at, updated_at, dynamic_fields
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """

        import json
        for b in bugs_to_insert:
            b_list = list(b)
            b_list[9] = json.dumps(b_list[9])  # Serialize dict to JSON string for jsonb column
            cur.execute(insert_sql, b_list)

        print(f"   Successfully inserted {len(bugs_to_insert)} rich bug reports across 3 projects!")

    print("\n==========================================================")
    print("  DATASET SEEDING COMPLETED SUCCESSFULLY!                 ")
    print("==========================================================")


if __name__ == "__main__":
    seed_rich_dataset()

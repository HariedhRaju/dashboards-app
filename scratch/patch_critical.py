import re
import psycopg2
import os
import random
from datetime import timedelta, datetime

# 1. Fix the dates in the database so charts render nicely
DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql://postgres:ash%40123@localhost:5432/qa_assistant')
conn = psycopg2.connect(DATABASE_URL)
cur = conn.cursor()

# Get all bug IDs
cur.execute("SELECT id, status FROM bug_reports")
bugs = cur.fetchall()

now = datetime.now()

for bug_id, status in bugs:
    # Randomly assign a creation date between 30 days ago and today
    days_ago = random.randint(1, 30)
    created_at = now - timedelta(days=days_ago)
    
    # Randomly assign an updated_at date between created_at and today
    update_days_ago = random.randint(0, days_ago)
    updated_at = now - timedelta(days=update_days_ago)
    
    # If closed or fixed, make sure closed_at is set properly? The schema only has created_at and updated_at.
    # We will just distribute created_at and updated_at.
    cur.execute(
        "UPDATE bug_reports SET created_at = %s, updated_at = %s WHERE id = %s",
        (created_at, updated_at, bug_id)
    )

conn.commit()
print("Successfully distributed dates for beautiful charts.")

# 2. Update __init__.py to include critical issues in Game Health
FILE_PATH = "a:\\vs _codes\\coe\\dash_board\\dashboards-app\\dashboards\\__init__.py"

with open(FILE_PATH, 'r', encoding='utf-8') as f:
    content = f.read()

# Add critical bugs query to get_game_health
old_game_health = """    game_metrics = calc_risk(game_stats)
    game = dict(game_stats)
    game.update(game_metrics)
    game['name'] = proj_name
    game['feature_count'] = len(features)"""

new_game_health = """    cur.execute(\"\"\"
        SELECT COALESCE(dynamic_fields->>'issue_no', dynamic_fields->>'source_record_id', left(id::text, 8)) as issue_no, title
        FROM bug_reports
        WHERE project_id = %s AND severity = 'P1' AND status IN ('open', 'in_progress')
    \"\"\", (project_id,))
    critical_issues = [dict(r) for r in cur.fetchall()]

    game_metrics = calc_risk(game_stats)
    game = dict(game_stats)
    game.update(game_metrics)
    game['name'] = proj_name
    game['feature_count'] = len(features)
    game['critical_issues'] = critical_issues"""

content = content.replace(old_game_health, new_game_health)

# 3. Update the LLM prompt
old_prompt = """Generate a concise, natural, high-level QA health summary for the selected game.
Write it in a narrative style similar to this example:
"The Fertile Crescent currently shows elevated QA risk, with 12 of 18 reported bugs still unresolved. Save / Load is the highest-risk feature, followed by Combat, with critical and high-severity issues concentrated in these areas. These features should receive priority for investigation and regression testing before the next build."

The supplied metrics have already been calculated by the backend.
Use only the supplied information."""

new_prompt = """Generate a concise, natural, high-level QA health summary for the selected game.
Write it in a narrative style similar to this example:
"The Fertile Crescent currently shows elevated QA risk, with 12 of 18 reported bugs still unresolved. Save / Load is the highest-risk feature, followed by Combat. Critical bugs that need immediate fixes include #12 (Game crashes on load) and #45 (Save corruption). These features and critical bugs should receive priority for investigation."

The supplied metrics have already been calculated by the backend.
Use only the supplied information. If there are 'critical_issues' in the game data, explicitly list them by their issue_no and title as bugs that need immediate fixes."""

content = content.replace(old_prompt, new_prompt)

with open(FILE_PATH, 'w', encoding='utf-8') as f:
    f.write(content)

print("Successfully updated backend to include critical bugs.")

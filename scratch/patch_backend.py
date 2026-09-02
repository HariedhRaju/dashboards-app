import re

FILE_PATH = "a:\\vs _codes\\coe\\dash_board\\dashboards-app\\dashboards\\__init__.py"

with open(FILE_PATH, 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Update SQL query in get_game_health to include bug numbers
old_sql = """            SELECT 
                COALESCE(dynamic_fields->>'feature', 'Uncategorized') as name,
                COUNT(*) as total_bugs,
                COUNT(*) FILTER (WHERE status = 'open') as open_bugs,
                COUNT(*) FILTER (WHERE status = 'in_progress') as in_progress_bugs,
                COUNT(*) FILTER (WHERE status = 'closed' OR status = 'fixed') as closed_bugs,
                COUNT(*) FILTER (WHERE severity = 'P1') as critical_bugs,
                COUNT(*) FILTER (WHERE severity = 'P2') as high_bugs,
                COUNT(*) FILTER (WHERE severity = 'P3') as medium_bugs,
                COUNT(*) FILTER (WHERE severity = 'P4') as low_bugs
            FROM bug_reports
            WHERE project_id = %s
            GROUP BY name
            ORDER BY total_bugs DESC"""

new_sql = """            SELECT 
                COALESCE(dynamic_fields->>'feature', 'Uncategorized') as name,
                COUNT(*) as total_bugs,
                COUNT(*) FILTER (WHERE status = 'open') as open_bugs,
                COUNT(*) FILTER (WHERE status = 'in_progress') as in_progress_bugs,
                COUNT(*) FILTER (WHERE status = 'closed' OR status = 'fixed') as closed_bugs,
                COUNT(*) FILTER (WHERE severity = 'P1') as critical_bugs,
                COUNT(*) FILTER (WHERE severity = 'P2') as high_bugs,
                COUNT(*) FILTER (WHERE severity = 'P3') as medium_bugs,
                COUNT(*) FILTER (WHERE severity = 'P4') as low_bugs,
                array_agg('#' || issue_no ORDER BY issue_no) as bug_list
            FROM bug_reports
            WHERE project_id = %s
            GROUP BY name
            ORDER BY total_bugs DESC"""

content = content.replace(old_sql, new_sql)

# 2. Update generate_game_summary to use specific prompt and print
old_summary = """@router.post("/bugs/game-summary")
async def generate_game_summary(payload: dict):
    from .llm_client import LLMClient
    
    prompt = f\"\"\"You are a Gaming QA dashboard summary assistant."""

# We'll replace the entire function using regex
summary_regex = re.compile(r'@router\.post\("/bugs/game-summary"\).*?return {"summary": response\.strip\(\)}', re.DOTALL)

new_summary = """@router.post("/bugs/game-summary")
async def generate_game_summary(payload: dict):
    from .llm_client import LLMClient
    
    print("\\n" + "="*50)
    print("🤖 [LLM AGENT] Starting Overall Game Summary generation...")
    print("="*50)
    
    prompt = f\"\"\"You are a Gaming QA dashboard summary assistant.

Generate a concise, natural, high-level QA health summary for the selected game.
Write it in a narrative style similar to this example:
"The Fertile Crescent currently shows elevated QA risk, with 12 of 18 reported bugs still unresolved. Save / Load is the highest-risk feature, followed by Combat, with critical and high-severity issues concentrated in these areas. These features should receive priority for investigation and regression testing before the next build."

The supplied metrics have already been calculated by the backend.
Use only the supplied information.
Do not calculate or modify risk scores.
Do not calculate confidence scores.
Do not invent bugs, causes, deadlines, owners, release dates, test results, or unsupported information.

Return ONLY the final summary text.
Do not return reasoning.
Do not return JSON.

INPUT DATA:
{payload}
\"\"\"
    print(f"\\n📤 Sending prompt to LLM (length: {len(prompt)} chars)...")
    client = LLMClient()
    response = await client.generate(prompt)
    
    print(f"\\n📥 Received response from LLM:")
    print("-" * 40)
    print(response.strip())
    print("-" * 40 + "\\n")
    
    return {"summary": response.strip()}"""

content = summary_regex.sub(new_summary, content)

with open(FILE_PATH, 'w', encoding='utf-8') as f:
    f.write(content)
print("Updated __init__.py")

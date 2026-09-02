import re

TSX_PATH = "a:\\vs _codes\\coe\\dash_board\\dashboards-app\\dashboards-frontend\\src\\AgentDashboardRenderer.tsx"

with open(TSX_PATH, 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Remove the Analyse Action block
btn_regex = re.compile(r"\{\/\* Analyse Action \*\/\}.*?<\/div>\s*<\/div>", re.DOTALL)
content = btn_regex.sub("</div>", content)

# 2. Remove the AI Insights block
insights_regex = re.compile(r"\{\/\* AI Insights \*\/\}.*?\{isAnalyzedView \?\s*\(.*?\)\s*:\s*null\}", re.DOTALL)
content = insights_regex.sub("", content)

# 3. Fix the null projectId in BugDetailPanel (line 1158)
content = content.replace("projectId={projFilter}", "projectId={projFilter || null}")

with open(TSX_PATH, 'w', encoding='utf-8') as f:
    f.write(content)
print("Stripped AI from BugDetailPanel")

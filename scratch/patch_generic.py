import re

# 1. Update backend to return full bug details and generalize the LLM prompt
FILE_PATH = "a:\\vs _codes\\coe\\dash_board\\dashboards-app\\dashboards\\__init__.py"
with open(FILE_PATH, 'r', encoding='utf-8') as f:
    content = f.read()

old_sql = """                COUNT(*) FILTER (WHERE severity = 'P4') as low_bugs,
                array_agg('#' || COALESCE(dynamic_fields->>'issue_no', dynamic_fields->>'source_record_id', left(id::text, 8))) as bug_list
            FROM bug_reports
            WHERE project_id = %s
            GROUP BY name"""

new_sql = """                COUNT(*) FILTER (WHERE severity = 'P4') as low_bugs,
                json_agg(
                    json_build_object(
                        'id', '#' || COALESCE(dynamic_fields->>'issue_no', dynamic_fields->>'source_record_id', left(id::text, 8)),
                        'severity', severity,
                        'title', title
                    )
                ) as bug_list
            FROM bug_reports
            WHERE project_id = %s
            GROUP BY name"""
            
content = content.replace(old_sql, new_sql)

# Update prompt to be generic
old_prompt = """"The Fertile Crescent currently shows elevated QA risk, with 12 of 18 reported bugs still unresolved. Save / Load is the highest-risk feature, followed by Combat. Critical bugs that need immediate fixes include #12 (Game crashes on load) and #45 (Save corruption). These features and critical bugs should receive priority for investigation." """

new_prompt = """"The [Game Name] currently shows elevated QA risk, with [X] of [Y] reported bugs still unresolved. [Feature] is the highest-risk feature, followed by [Feature]. Critical bugs that need immediate fixes include #[ID] ([Title]). These features and critical bugs should receive priority for investigation." """

content = content.replace(old_prompt, new_prompt)

with open(FILE_PATH, 'w', encoding='utf-8') as f:
    f.write(content)

# 2. Update api.ts
API_PATH = "a:\\vs _codes\\coe\\dash_board\\dashboards-app\\dashboards-frontend\\src\\api.ts"
with open(API_PATH, 'r', encoding='utf-8') as f:
    api_content = f.read()

api_content = api_content.replace("bug_list?: string[];", "bug_list?: { id: string; severity: string; title: string; }[];")

with open(API_PATH, 'w', encoding='utf-8') as f:
    f.write(api_content)

# 3. Update AgentDashboardRenderer.tsx
TSX_PATH = "a:\\vs _codes\\coe\\dash_board\\dashboards-app\\dashboards-frontend\\src\\AgentDashboardRenderer.tsx"
with open(TSX_PATH, 'r', encoding='utf-8') as f:
    tsx = f.read()

old_modal = """          {feature.bug_list && feature.bug_list.length > 0 && (
            <div className="bg-neutral-800/50 rounded-xl p-4 border border-neutral-700/50">
              <div className="text-xs text-neutral-400 uppercase tracking-wider mb-3">Associated Bugs</div>
              <div className="flex flex-wrap gap-2 text-sm">
                 {feature.bug_list.map(bugId => (
                   <span key={bugId} className="px-2 py-1 bg-indigo-900/40 text-indigo-300 border border-indigo-800/60 rounded">
                     {bugId}
                   </span>
                 ))}
              </div>
            </div>
          )}"""

new_modal = """          {feature.bug_list && feature.bug_list.length > 0 && (
            <div className="bg-neutral-800/50 rounded-xl p-4 border border-neutral-700/50 max-h-64 overflow-y-auto">
              <div className="text-xs text-neutral-400 uppercase tracking-wider mb-3">Associated Bugs (Critical / High First)</div>
              <div className="flex flex-col gap-2">
                 {feature.bug_list
                    .sort((a, b) => a.severity.localeCompare(b.severity))
                    .map(b => (
                   <div key={b.id} className="flex items-center gap-3 px-3 py-2 bg-neutral-900/40 rounded border border-neutral-700/50 text-sm">
                     <span className={`w-2 h-2 rounded-full ${b.severity === 'P1' ? 'bg-rose-500' : b.severity === 'P2' ? 'bg-amber-500' : b.severity === 'P3' ? 'bg-indigo-500' : 'bg-neutral-500'}`}></span>
                     <span className="font-mono text-neutral-400 min-w-[3rem]">{b.id}</span>
                     <span className="text-neutral-200 truncate" title={b.title}>{b.title}</span>
                     {b.severity === 'P1' && <span className="ml-auto text-[10px] uppercase font-bold text-rose-400 bg-rose-400/10 px-2 py-0.5 rounded">Critical Fix</span>}
                   </div>
                 ))}
              </div>
            </div>
          )}"""

tsx = tsx.replace(old_modal, new_modal)

with open(TSX_PATH, 'w', encoding='utf-8') as f:
    f.write(tsx)

print("Successfully applied feature bug tracking generic updates.")

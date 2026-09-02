import re

API_PATH = "a:\\vs _codes\\coe\\dash_board\\dashboards-app\\dashboards-frontend\\src\\api.ts"

with open(API_PATH, 'r', encoding='utf-8') as f:
    content = f.read()

# Add bug_list to FeatureHealth interface
old_iface = """export interface FeatureHealth {
  name: string;
  total_bugs: number;
  open_bugs: number;
  in_progress_bugs: number;
  closed_bugs: number;
  critical_bugs: number;
  high_bugs: number;
  medium_bugs: number;
  low_bugs: number;
  risk_score: number;
  health_status: string;
  confidence_score: number;
}"""

new_iface = """export interface FeatureHealth {
  name: string;
  total_bugs: number;
  open_bugs: number;
  in_progress_bugs: number;
  closed_bugs: number;
  critical_bugs: number;
  high_bugs: number;
  medium_bugs: number;
  low_bugs: number;
  risk_score: number;
  health_status: string;
  confidence_score: number;
  bug_list?: string[];
}"""

content = content.replace(old_iface, new_iface)

with open(API_PATH, 'w', encoding='utf-8') as f:
    f.write(content)

# Update AgentDashboardRenderer.tsx to show bug list in FeatureAnalysisModal
TSX_PATH = "a:\\vs _codes\\coe\\dash_board\\dashboards-app\\dashboards-frontend\\src\\AgentDashboardRenderer.tsx"
with open(TSX_PATH, 'r', encoding='utf-8') as f:
    tsx_content = f.read()

# We will inject the bug list under Severity Distribution
old_modal = """          <div className="bg-neutral-800/50 rounded-xl p-4 border border-neutral-700/50">
            <div className="text-xs text-neutral-400 uppercase tracking-wider mb-3">Severity Distribution</div>
            <div className="flex gap-6 text-sm font-medium">
               <span className="text-rose-400">P1: {feature.critical_bugs}</span>
               <span className="text-amber-400">P2: {feature.high_bugs}</span>
               <span className="text-indigo-400">P3: {feature.medium_bugs}</span>
               <span className="text-neutral-400">P4: {feature.low_bugs}</span>
            </div>
          </div>"""

new_modal = """          <div className="bg-neutral-800/50 rounded-xl p-4 border border-neutral-700/50">
            <div className="text-xs text-neutral-400 uppercase tracking-wider mb-3">Severity Distribution</div>
            <div className="flex gap-6 text-sm font-medium">
               <span className="text-rose-400">P1: {feature.critical_bugs}</span>
               <span className="text-amber-400">P2: {feature.high_bugs}</span>
               <span className="text-indigo-400">P3: {feature.medium_bugs}</span>
               <span className="text-neutral-400">P4: {feature.low_bugs}</span>
            </div>
          </div>
          
          {feature.bug_list && feature.bug_list.length > 0 && (
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

tsx_content = tsx_content.replace(old_modal, new_modal)

with open(TSX_PATH, 'w', encoding='utf-8') as f:
    f.write(tsx_content)
    
print("Updated API and UI")

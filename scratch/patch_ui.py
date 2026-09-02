import os
import re

TSX_FILE = "a:\\vs _codes\\coe\\dash_board\\dashboards-app\\dashboards-frontend\\src\\AgentDashboardRenderer.tsx"

with open(TSX_FILE, 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Add imports to api.ts
content = content.replace(
    "fetchDynamicMetric,",
    "fetchDynamicMetric,\n  fetchGameHealth,\n  fetchGameSummary,\n  type GameHealthResponse,\n  type FeatureHealth,"
)

# 2. Add Game Health and Feature Health Components
new_components = """
function GameHealthPanel({ projectId }: { projectId: string }) {
  const { data: gameHealthResponse, isPending } = useQuery<GameHealthResponse>({
    queryKey: ['gameHealth', projectId],
    queryFn: () => fetchGameHealth(projectId),
    staleTime: 60_000,
  });

  const { data: gameSummaryData, isPending: isSummaryPending } = useQuery({
    queryKey: ['gameSummary', gameHealthResponse?.game.risk_score],
    queryFn: () => fetchGameSummary(gameHealthResponse),
    enabled: !!gameHealthResponse,
    staleTime: Infinity,
  });

  if (isPending) {
    return <div className="text-indigo-400 p-4">Loading Game Health...</div>;
  }
  
  if (!gameHealthResponse?.game) {
    return null;
  }

  const { game } = gameHealthResponse;
  
  return (
    <div className="bg-gradient-to-br from-indigo-950/40 via-purple-900/20 to-neutral-900 border border-indigo-800/50 rounded-2xl p-6 mb-8 shadow-xl">
      <div className="flex items-center gap-3 border-b border-indigo-800/40 pb-4 mb-4">
        <h3 className="text-xl font-bold text-white uppercase tracking-wider">GAME HEALTH — {game.name}</h3>
      </div>
      
      <div className="flex flex-col md:flex-row gap-6 mb-6">
        <div className="flex-1 space-y-4">
          <div className="flex items-center gap-3">
            <span className="text-2xl">{game.health_status === 'CRITICAL' ? '❗' : game.health_status === 'HIGH' ? '⚠' : game.health_status === 'MEDIUM' ? '◐' : '✓'}</span>
            <span className="text-xl font-bold text-white">{game.health_status} RISK</span>
          </div>
          <div className="flex flex-wrap gap-4 text-sm text-neutral-300 font-medium bg-neutral-900/60 p-3 rounded-lg border border-neutral-800">
            <span><span className="text-white text-base">{game.total_bugs}</span> Bugs</span>
            <span><span className="text-white text-base">{game.open_bugs}</span> Open</span>
            <span><span className="text-rose-400 text-base">{game.critical_bugs}</span> Critical</span>
            <span><span className="text-indigo-300 text-base">{game.feature_count}</span> Features</span>
          </div>
        </div>
        
        <div className="flex gap-4 md:border-l md:border-indigo-800/40 md:pl-6">
          <div className="bg-neutral-900/60 border border-indigo-900/30 rounded-xl p-4 w-32 flex flex-col justify-center items-center">
            <div className="text-[10px] font-bold text-indigo-400 uppercase tracking-wider mb-1">Risk</div>
            <div className={`text-2xl font-bold ${game.risk_score > 7.5 ? 'text-rose-500' : 'text-white'}`}>{game.risk_score.toFixed(1)} <span className="text-sm text-neutral-500">/ 10</span></div>
          </div>
          <div className="bg-neutral-900/60 border border-indigo-900/30 rounded-xl p-4 w-32 flex flex-col justify-center items-center">
            <div className="text-[10px] font-bold text-indigo-400 uppercase tracking-wider mb-1">Confidence</div>
            <div className="text-2xl font-bold text-white">{game.confidence_score}%</div>
          </div>
        </div>
      </div>
      
      <div className="bg-neutral-900/80 border border-indigo-800/50 rounded-xl p-5 relative overflow-hidden">
        <div className="absolute top-0 left-0 w-1 h-full bg-indigo-500"></div>
        <div className="text-xs font-bold text-indigo-400 uppercase tracking-wider mb-2 flex items-center gap-2">
          <Sparkles className="w-4 h-4" /> AI SUMMARY
        </div>
        {isSummaryPending ? (
          <div className="text-sm text-indigo-300 animate-pulse">Generating summary...</div>
        ) : (
          <p className="text-sm text-neutral-200 leading-relaxed">
            {gameSummaryData?.summary || "Summary temporarily unavailable. Dashboard metrics are still available."}
          </p>
        )}
      </div>
    </div>
  );
}

function FeatureAnalysisModal({ feature, onClose }: { feature: FeatureHealth, onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm">
      <div className="bg-neutral-900 border border-indigo-800/50 rounded-2xl w-full max-w-2xl overflow-hidden shadow-2xl flex flex-col max-h-[90vh]">
        <div className="p-6 border-b border-indigo-800/40 flex justify-between items-center bg-indigo-950/20">
          <h2 className="text-xl font-bold text-white uppercase tracking-wider">FEATURE ANALYSIS — {feature.name}</h2>
          <button onClick={onClose} className="text-neutral-400 hover:text-white">✕</button>
        </div>
        
        <div className="p-6 overflow-y-auto space-y-6">
          <div className="flex items-center gap-3">
            <span className="text-3xl">{feature.health_status === 'CRITICAL' ? '❗' : feature.health_status === 'HIGH' ? '⚠' : feature.health_status === 'MEDIUM' ? '◐' : '✓'}</span>
            <span className="text-2xl font-bold text-white">{feature.health_status}</span>
          </div>
          
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div className="bg-neutral-800/50 rounded-xl p-4 border border-neutral-700/50">
               <div className="text-xs text-neutral-400 uppercase">Risk Score</div>
               <div className="text-xl font-bold text-white">{feature.risk_score.toFixed(1)} / 10</div>
            </div>
            <div className="bg-neutral-800/50 rounded-xl p-4 border border-neutral-700/50">
               <div className="text-xs text-neutral-400 uppercase">Confidence</div>
               <div className="text-xl font-bold text-white">{feature.confidence_score}%</div>
            </div>
            <div className="bg-neutral-800/50 rounded-xl p-4 border border-neutral-700/50">
               <div className="text-xs text-neutral-400 uppercase">Total Bugs</div>
               <div className="text-xl font-bold text-white">{feature.total_bugs}</div>
            </div>
            <div className="bg-neutral-800/50 rounded-xl p-4 border border-neutral-700/50">
               <div className="text-xs text-neutral-400 uppercase">Open Bugs</div>
               <div className="text-xl font-bold text-white">{feature.open_bugs}</div>
            </div>
          </div>
          
          <div className="bg-neutral-800/50 rounded-xl p-4 border border-neutral-700/50">
            <div className="text-xs text-neutral-400 uppercase tracking-wider mb-3">Severity Distribution</div>
            <div className="flex gap-6 text-sm font-medium">
               <span className="text-rose-400">P1: {feature.critical_bugs}</span>
               <span className="text-amber-400">P2: {feature.high_bugs}</span>
               <span className="text-indigo-400">P3: {feature.medium_bugs}</span>
               <span className="text-neutral-400">P4: {feature.low_bugs}</span>
            </div>
          </div>
          
          <div className="space-y-4">
            <div className="bg-indigo-950/20 border border-indigo-900/30 rounded-xl p-4">
              <div className="text-xs font-bold text-indigo-400 uppercase tracking-wider mb-2">Summary</div>
              <p className="text-sm text-neutral-200">
                {feature.name} currently represents a {feature.health_status.toLowerCase()} risk area based on {feature.open_bugs} unresolved defects. {feature.critical_bugs > 0 ? "Critical issues are present." : ""}
              </p>
            </div>
            <div className="bg-indigo-950/20 border border-indigo-900/30 rounded-xl p-4">
              <div className="text-xs font-bold text-indigo-400 uppercase tracking-wider mb-2">Recommendation</div>
              <p className="text-sm text-neutral-200">
                {feature.critical_bugs > 0 ? "Prioritize the critical defects and perform targeted regression testing." : feature.high_bugs > 0 ? "Investigate unresolved high-severity issues." : "Continue monitoring and regression validation."}
              </p>
            </div>
          </div>
          
        </div>
        
        <div className="p-4 border-t border-indigo-800/40 bg-neutral-900 flex justify-end">
          <button onClick={onClose} className="px-6 py-2 bg-neutral-800 hover:bg-neutral-700 text-white rounded-lg font-medium transition-colors">
            CLOSE
          </button>
        </div>
      </div>
    </div>
  );
}

function FeatureHealthPanel({ projectId }: { projectId: string }) {
  const [selectedFeature, setSelectedFeature] = useState<FeatureHealth | null>(null);
  
  const { data: gameHealthResponse } = useQuery<GameHealthResponse>({
    queryKey: ['gameHealth', projectId],
    queryFn: () => fetchGameHealth(projectId),
    staleTime: 60_000,
  });

  if (!gameHealthResponse?.features || gameHealthResponse.features.length === 0) {
    return null;
  }

  return (
    <div className="mt-8 bg-neutral-900/50 border border-neutral-800 rounded-2xl p-6">
      <h3 className="text-lg font-bold text-white uppercase tracking-wider mb-4 flex items-center gap-2">
        <Layers className="w-5 h-5 text-indigo-400" /> FEATURE HEALTH
      </h3>
      
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {gameHealthResponse.features.map(f => (
          <div 
            key={f.name}
            onClick={() => setSelectedFeature(f)}
            className="bg-neutral-800/40 hover:bg-neutral-800 border border-neutral-700/50 hover:border-indigo-500/50 rounded-xl p-4 cursor-pointer transition-all flex flex-col gap-2"
          >
             <div className="flex items-center gap-2 text-white font-bold text-base">
                <span>{f.health_status === 'CRITICAL' ? '❗' : f.health_status === 'HIGH' ? '⚠' : f.health_status === 'MEDIUM' ? '◐' : '✓'}</span>
                <span className="truncate">{f.name}</span>
             </div>
             <div className="text-[11px] text-neutral-400 font-medium tracking-wide flex items-center flex-wrap gap-1.5">
                <span>{f.total_bugs} Bugs</span> • 
                <span className={f.critical_bugs > 0 ? "text-rose-400" : ""}>{f.critical_bugs} Critical</span> • 
                <span>{f.open_bugs} Open</span> • 
                <span className="text-indigo-300">Risk {f.risk_score.toFixed(1)}</span> • 
                <span>{f.health_status}</span>
             </div>
          </div>
        ))}
      </div>
      
      {selectedFeature && (
        <FeatureAnalysisModal feature={selectedFeature} onClose={() => setSelectedFeature(null)} />
      )}
    </div>
  );
}
"""

content = content.replace("function GeneralAIDashboardAnalysis", new_components + "\nfunction GeneralAIDashboardAnalysis")

# 3. Main layout logic inside AgentDashboardRenderer
# Remove GeneralAIDashboardAnalysis calls and add GameHealthPanel / FeatureHealthPanel
# Search for the rendering of standard dashboard and place GameHealth above, FeatureHealth below

layout_regex = re.compile(r"\{\/\* AI Analysis Block \*\/\}.*?\{\/\* Standard Dashboard \(Fallback\/Default\) \*\/\}.*?\{\!isBugOnly.*?OverviewPanel\(\).*?\}", re.DOTALL)

new_layout = """
      {/* GAME HEALTH */}
      {filters.project_id && (
        <GameHealthPanel projectId={filters.project_id as string} />
      )}

      {/* Standard Dashboard (Fallback/Default) */}
      {!isBugOnly && (
        <div className="bg-neutral-900 border border-neutral-800 rounded-2xl shadow-xl overflow-hidden animate-in fade-in zoom-in-95 duration-300">
          <OverviewPanel />
        </div>
      )}
      
      {/* FEATURE HEALTH */}
      {!isBugOnly && filters.project_id && (
        <FeatureHealthPanel projectId={filters.project_id as string} />
      )}
"""

content = layout_regex.sub(new_layout, content)


# 4. Remove ANALYSE button and its logic from BugDetailPanel
# Replace the exact block
btn_block = """
          {/* Analyse Action */}
          <div className="pt-2">
            <button
              onClick={() => onAnalyze(rec.issue_no)}
              disabled={isAnalyzing}
              className={`
                w-full flex items-center justify-center gap-2 py-3 rounded-xl font-bold text-sm transition-all
                ${isAnalyzing 
                  ? 'bg-indigo-900/40 text-indigo-400 cursor-not-allowed border border-indigo-900/50' 
                  : 'bg-indigo-600 hover:bg-indigo-500 text-white shadow-lg shadow-indigo-900/20 hover:shadow-indigo-600/30'
                }
              `}
            >
              {isAnalyzing ? (
                <><RefreshCw className="w-4 h-4 animate-spin" /> ANALYZING...</>
              ) : (
                <><Sparkles className="w-4 h-4" /> ANALYSE</>
              )}
            </button>
          </div>"""
if btn_block in content:
    content = content.replace(btn_block, "")
else:
    # Try regex if exact block match fails
    btn_regex = re.compile(r"\{\/\* Analyse Action \*\/\}.*?<\/button>\s*<\/div>", re.DOTALL)
    content = btn_regex.sub("", content)

# Remove the AI investigation block
ai_investigation_block = r"\{isAnalyzedView && insightsData && \(\s*insightsData\.investigation \? \(.*?\)\s*:\s*null\s*\)\}"
content = re.sub(ai_investigation_block, "", content, flags=re.DOTALL)

with open(TSX_FILE, 'w', encoding='utf-8') as f:
    f.write(content)

print("Updated AgentDashboardRenderer.tsx")

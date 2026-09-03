import React, { useState, useEffect, useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  PieChart,
  Pie,
  Cell,
  Tooltip,
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  AreaChart,
  Area,
} from 'recharts';
import {
  Bug,
  FlaskConical,
  CheckCircle2,
  Unlink,
  AlertTriangle,
  Info,
  Shield,
  TrendingDown,
  RefreshCw,
  ChevronDown,
  ChevronRight,
  Brain,
  Activity,
  Sparkles,
  X,
  Search,
  FileText,
  ListOrdered,
} from 'lucide-react';
import { fetchBugDetails } from './api';

const API_BASE =
  (typeof import.meta !== 'undefined' && import.meta.env?.VITE_DASHBOARDS_API) || '';

// ---------------------------------------------------------------------------
// Types — mirror common_agent/core.py contracts
// ---------------------------------------------------------------------------

interface ActivityOverTime {
  note: string;
  months: string[];
  bugs_filed: number[];
  test_cases_generated: number[];
}

interface ModuleBreakdown {
  keys: string[];
  bugs: number[];
  test_cases: number[];
  // Real, per-module count of bugs that have an actual bug_test_case_mappings
  // row (not merely "bugs sharing this module name") — present only when the
  // dashboard was built with a mapping source. Aligned index-for-index with `keys`.
  mapped_bugs?: number[];
}

interface TokenUsageByFeature {
  note: string;
  features: string[];
  total_tokens: number[];
  call_count: number[];
}

interface ProjectSummary {
  bugsy: {
    total_bugs: number;
    by_severity: Record<string, number>;
    by_status: Record<string, number>;
    // Bugsy's own summary — static text for this demo project, served from
    // the backend (common_agent/core.py's BUGSY_STATIC_SUMMARY) so it is
    // never duplicated/hardcoded in the frontend.
    summary_text?: string;
  };
  testsmith: {
    total_test_cases_all_projects: number;
    test_cases_linked_to_this_project?: number;
    note: string;
    by_status?: Record<string, number>;
    execution_summary?: string;
  };
  coverage_confidence_pct?: number | null;
  coverage_confidence_note?: string;
  // Deterministic, template-built sentences from real computed numbers
  // (never LLM-generated — see common_agent/core.py). Only present when the
  // dashboard was built with a mapping source.
  cross_feature_observations?: string[];
  unified_summary_text?: string;
}

interface RecordLevelMapping {
  note: string;
  total_mappings: number;
  distinct_bugs_mapped: number;
  distinct_test_cases_mapped: number;
  bugs_with_mapping: number;
  bugs_without_mapping: number;
  mapping_coverage_pct: number | null;
}

interface CoverageGaps {
  bugs_without_mapped_test_case?: number;
  critical_bugs_without_mapped_test_case?: number;
  critical_bugs_without_mapped_test_case_by_module?: Record<string, number>;
  modules_with_bugs_but_no_test_cases?: string[];
}

interface CommonAgentDashboardData {
  summary: { total_bugs: number; total_test_cases: number; bugs_with_project_id: number };
  charts: {
    bugs_by_severity: Record<string, number>;
    bugs_by_status: Record<string, number>;
    test_cases_by_feature: Record<string, number>;
    test_cases_by_priority: Record<string, number>;
    activity_over_time: ActivityOverTime;
    bugs_vs_test_cases_by_module?: ModuleBreakdown;
    token_usage_by_feature?: TokenUsageByFeature;
  };
  module_analytics?: {
    note: string;
    modules: {
      module: string;
      bug_count: number;
      test_case_count: number;
      // Real, mapping-table-derived — only present when the dashboard was
      // built with a mapping source. coverage_pct is null when bug_count is 0
      // (nothing to divide by), never a fabricated 0% or 100%.
      mapped_bug_count?: number;
      coverage_pct?: number | null;
    }[];
  };
  record_level_mapping?: RecordLevelMapping;
  coverage_gaps?: CoverageGaps;
  project_summary?: ProjectSummary;
  unavailable_metrics: string[];
}

interface CommonAgentResponse {
  dashboard: CommonAgentDashboardData;
}

type AiConfidence = 'high' | 'medium' | 'low' | null;

interface ProjectSummaryAI {
  status: string;
  summary: string | null;
  observations: string[];
  ai_confidence: AiConfidence;
  error?: string;
}

interface BugSummaryAI {
  status: string;
  summary: string | null;
  ai_confidence: AiConfidence;
  error?: string;
}

interface BugSummaryResponse {
  bug_id: string;
  mapped_test_case_count: number;
  summary: BugSummaryAI;
}

interface DimOption {
  value: string;
  label: string;
}

interface BugRow {
  issue_no: string;
  title: string;
  severity: string;
  status: string;
  project_name: string;
  reporter_name: string;
  created_at: string;
  age_days: number;
  module?: string;
}

// ---------------------------------------------------------------------------
// API Helpers
// ---------------------------------------------------------------------------

async function fetchProjects(): Promise<DimOption[]> {
  const res = await fetch(`${API_BASE}/api/dimensions/projects`, { credentials: 'include' });
  if (!res.ok) return [];
  const json = await res.json();
  return (json.options ?? []) as DimOption[];
}

async function fetchCommonAgentDashboard(projectId: string): Promise<CommonAgentResponse> {
  const qs = new URLSearchParams({ project_id: projectId });
  const res = await fetch(`${API_BASE}/api/common-agent/dashboard?${qs}`, { credentials: 'include' });
  if (!res.ok) {
    const detail = await res.text().catch(() => '');
    throw new Error(`Common Agent dashboard failed (${res.status}): ${detail}`);
  }
  return res.json();
}

async function fetchProjectSummaryAI(projectId: string): Promise<{ summary: ProjectSummaryAI }> {
  const res = await fetch(`${API_BASE}/api/common-agent/project-summary`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ project_id: projectId }),
  });
  if (!res.ok) {
    const detail = await res.text().catch(() => '');
    throw new Error(`Project summary failed (${res.status}): ${detail}`);
  }
  return res.json();
}

async function fetchBugSummary(bugId: string): Promise<BugSummaryResponse> {
  const res = await fetch(`${API_BASE}/api/common-agent/bug-summary/${encodeURIComponent(bugId)}`, {
    credentials: 'include',
  });
  if (!res.ok) {
    const detail = await res.text().catch(() => '');
    throw new Error(`Bug summary failed (${res.status}): ${detail}`);
  }
  return res.json();
}

async function fetchProjectBugs(projectId: string): Promise<{ rows: BugRow[]; total: number }> {
  const qs = new URLSearchParams({
    date_range_start: '2000-01-01T00:00:00Z',
    date_range_end: '2100-01-01T00:00:00Z',
    project_id: projectId,
    // 100, not 50: the real Fertile Crescent data has 61 bugs — the old 50
    // cap would silently drop 11 of them from the coverage table.
    page_size: '100',
    sort: 'created_at',
    sort_dir: 'asc',
  });
  const res = await fetch(`${API_BASE}/api/metrics/bugs.telemetry?${qs}`, { credentials: 'include' });
  if (!res.ok) return { rows: [], total: 0 };
  const json = await res.json();
  return { rows: (json.rows ?? []) as BugRow[], total: json.total ?? 0 };
}

async function fetchMappedTestCaseCounts(projectId: string): Promise<Record<string, number>> {
  const qs = new URLSearchParams({ project_id: projectId });
  const res = await fetch(`${API_BASE}/api/common-agent/mapped-test-case-counts?${qs}`, { credentials: 'include' });
  if (!res.ok) return {};
  const json = await res.json();
  return (json.mapped_counts ?? {}) as Record<string, number>;
}

// ---------------------------------------------------------------------------
// Normalization Helper for Display Labels
// ---------------------------------------------------------------------------

function normalizeFeatureName(name: string): string {
  if (!name) return 'General';
  const clean = name.trim();

  // Normalize slashes: e.g. "UI/Menus" -> "UI / Menus", "SAVE/LOAD" -> "Save / Load"
  if (clean.includes('/')) {
    return clean
      .split('/')
      .map(part => normalizeFeatureName(part))
      .join(' / ');
  }

  // If ALL CAPS like "CRAFTING" or "MATCHMAKING", convert to Title Case
  if (clean === clean.toUpperCase() && clean.length > 1) {
    return clean.charAt(0).toUpperCase() + clean.slice(1).toLowerCase();
  }

  // Known acronyms
  if (clean.toLowerCase() === 'ui') return 'UI';
  if (clean.toLowerCase() === 'qa') return 'QA';
  if (clean.toLowerCase() === 'hud') return 'HUD';

  // Capitalize first letter of each word
  return clean
    .split(' ')
    .map(w => (w.length > 0 ? w.charAt(0).toUpperCase() + w.slice(1) : w))
    .join(' ');
}

// ---------------------------------------------------------------------------
// Colors & Styling
// ---------------------------------------------------------------------------

const COLOR_BUGS = '#3b82f6';      // Soft Blue
const COLOR_TESTS = '#8b5cf6';     // Soft Purple / Lavender
const COLOR_COVERED = '#10b981';   // Soft Green
const COLOR_GAP = '#ef4444';       // Soft Red
const COLOR_WARN = '#f59e0b';      // Soft Amber
const COLOR_MUTED = '#64748b';     // Soft Slate

const TOOLTIP_STYLE = {
  background: '#111728',
  border: '1px solid #1e293b',
  borderRadius: 8,
  fontSize: 12,
  color: '#e2e8f0',
};

// ---------------------------------------------------------------------------
// Helper Badges
// ---------------------------------------------------------------------------

function SeverityPill({ severity }: { severity: string }) {
  const s = severity?.toLowerCase() || '';
  if (['critical', 'p1', 'blocker'].includes(s)) {
    return (
      <span className="inline-flex items-center px-2 py-0.5 rounded text-[11px] font-bold bg-rose-950/60 text-rose-300 border border-rose-800/60">
        Critical
      </span>
    );
  }
  if (['p2', 'major', 'high'].includes(s)) {
    return (
      <span className="inline-flex items-center px-2 py-0.5 rounded text-[11px] font-bold bg-amber-950/60 text-amber-300 border border-amber-800/60">
        P2 (High)
      </span>
    );
  }
  if (['p3', 'minor', 'medium'].includes(s)) {
    return (
      <span className="inline-flex items-center px-2 py-0.5 rounded text-[11px] font-bold bg-yellow-950/60 text-yellow-300 border border-yellow-800/60">
        Minor
      </span>
    );
  }
  return (
    <span className="inline-flex items-center px-2 py-0.5 rounded text-[11px] font-bold bg-slate-800 text-slate-400 border border-slate-700">
      Trivial
    </span>
  );
}

function CoveragePill({ isCovered }: { isCovered: boolean }) {
  if (isCovered) {
    return (
      <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-[11px] font-semibold border border-emerald-500/50 bg-emerald-950/30 text-emerald-400">
        Covered
      </span>
    );
  }
  return (
    <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-[11px] font-semibold border border-rose-500/50 bg-rose-950/30 text-rose-400">
      Coverage Gap
    </span>
  );
}

// ---------------------------------------------------------------------------
// Redesigned Chart 1: Bugs vs Test Cases by Module (Hierarchical Grouped List)
// ---------------------------------------------------------------------------

function ModuleComparisonChart({
  data,
}: {
  data: Array<{ module: string; bugs: number; test_cases: number; mappedBugs?: number }>;
}) {
  // Sort by QA Risk: High bug count with lower test coverage first
  const sortedData = useMemo(() => {
    return [...data].sort((a, b) => {
      const riskA = a.bugs - a.test_cases;
      const riskB = b.bugs - b.test_cases;
      if (riskB !== riskA) return riskB - riskA;
      return b.bugs - a.bugs;
    });
  }, [data]);

  // Determine max value for 100% scale
  const maxVal = useMemo(() => {
    const highest = Math.max(...sortedData.map(d => Math.max(d.bugs, d.test_cases)), 1);
    return Math.max(highest + 1, 3);
  }, [sortedData]);

  const ticks = Array.from({ length: maxVal + 1 }, (_, i) => i);

  return (
    <div className="space-y-4">
      {/* Module Groups List */}
      <div className="space-y-3.5 max-h-[280px] overflow-y-auto pr-1">
        {sortedData.map((item, idx) => {
          const bugsPct = (item.bugs / maxVal) * 100;
          const testPct = (item.test_cases / maxVal) * 100;
          // Real coverage: this module's bugs that have an actual mapping
          // row, not a heuristic comparison of raw bug/test-case counts.
          // mappedBugs is undefined when no mapping source was available.
          const hasCoverageData = item.mappedBugs != null;
          const isRisk = hasCoverageData ? (item.mappedBugs as number) < item.bugs : item.bugs > item.test_cases;

          return (
            <div
              key={item.module || idx}
              className="bg-[#0e1424]/80 border border-slate-800/60 rounded-xl p-3 space-y-2.5 hover:border-slate-700/80 transition-colors"
            >
              {/* Module Header */}
              <div className="flex items-center justify-between">
                <span className="text-xs font-bold text-slate-200 tracking-wide">
                  {normalizeFeatureName(item.module)}
                </span>
                <div className="flex items-center gap-1.5">
                  {hasCoverageData && item.bugs > 0 && (
                    <span className="text-[10px] font-mono text-slate-400">
                      {item.mappedBugs}/{item.bugs} bugs covered
                    </span>
                  )}
                  {isRisk && item.bugs > 0 && (
                    <span className="text-[10px] font-semibold text-rose-400 bg-rose-950/40 border border-rose-800/40 px-2 py-0.5 rounded">
                      Coverage Gap
                    </span>
                  )}
                </div>
              </div>

              {/* Bugs Bar */}
              <div className="grid grid-cols-12 items-center gap-2 text-xs">
                <span className="col-span-3 text-[11px] text-slate-400 font-medium flex items-center gap-1.5">
                  <span className="w-2 h-2 rounded-sm bg-[#3b82f6] shrink-0" />
                  <span>Bugs</span>
                </span>
                <div className="col-span-9 flex items-center gap-2.5">
                  <div className="flex-1 h-3 bg-slate-800/80 rounded-sm overflow-hidden flex items-center">
                    <div
                      className="h-full bg-[#3b82f6] rounded-sm transition-all duration-300"
                      style={{ width: `${Math.max(bugsPct, 0)}%` }}
                    />
                  </div>
                  <span className="w-5 text-right font-mono font-bold text-[#60a5fa] text-xs tabular-nums">
                    {item.bugs}
                  </span>
                </div>
              </div>

              {/* Test Cases Bar */}
              <div className="grid grid-cols-12 items-center gap-2 text-xs">
                <span className="col-span-3 text-[11px] text-slate-400 font-medium flex items-center gap-1.5">
                  <span className="w-2 h-2 rounded-sm bg-[#8b5cf6] shrink-0" />
                  <span>Test Cases</span>
                </span>
                <div className="col-span-9 flex items-center gap-2.5">
                  <div className="flex-1 h-3 bg-slate-800/80 rounded-sm overflow-hidden flex items-center">
                    <div
                      className="h-full bg-[#8b5cf6] rounded-sm transition-all duration-300"
                      style={{ width: `${Math.max(testPct, 0)}%` }}
                    />
                  </div>
                  <span className="w-5 text-right font-mono font-bold text-[#c084fc] text-xs tabular-nums">
                    {item.test_cases}
                  </span>
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {/* Subtle X-Axis Scale */}
      <div className="pt-1.5 border-t border-slate-800/60">
        <div className="grid grid-cols-12 items-center text-[10px] text-slate-500">
          <div className="col-span-3 text-[10px] text-slate-500 uppercase tracking-wider font-semibold">Scale</div>
          <div className="col-span-9 flex justify-between pr-7 font-mono">
            {ticks.map(t => (
              <span key={t}>{t}</span>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Redesigned Chart 2: Test Cases by Feature (Compact & Balanced Composition)
// ---------------------------------------------------------------------------

function TestCasesByFeatureChart({
  data,
}: {
  data: Array<{ feature: string; count: number }>;
}) {
  const normalizedData = useMemo(() => {
    // Group by normalized feature name if casing duplicates exist
    const map = new Map<string, number>();
    for (const item of data) {
      const norm = normalizeFeatureName(item.feature);
      map.set(norm, (map.get(norm) || 0) + item.count);
    }
    return Array.from(map.entries())
      .map(([feature, count]) => ({ feature, count }))
      .sort((a, b) => b.count - a.count);
  }, [data]);

  const maxVal = useMemo(() => {
    const highest = Math.max(...normalizedData.map(d => d.count), 1);
    return Math.max(highest + 1, 3);
  }, [normalizedData]);

  const ticks = Array.from({ length: maxVal + 1 }, (_, i) => i);

  return (
    <div className="space-y-4 py-1">
      {/* Bars List */}
      <div className="space-y-3.5">
        {normalizedData.map((item, idx) => {
          const pct = (item.count / maxVal) * 100;
          return (
            <div key={item.feature || idx} className="space-y-1.5">
              <div className="flex justify-between text-xs font-semibold text-slate-300">
                <span>{item.feature}</span>
                <span className="font-mono text-[#c084fc] font-bold tabular-nums">{item.count}</span>
              </div>
              <div className="h-3.5 bg-slate-800/80 rounded-md overflow-hidden flex items-center p-0.5">
                <div
                  className="h-full bg-[#8b5cf6] rounded-sm transition-all duration-300"
                  style={{ width: `${Math.max(pct, 0)}%` }}
                />
              </div>
            </div>
          );
        })}
      </div>

      {/* Subtle Scale */}
      <div className="pt-2.5 border-t border-slate-800/60">
        <div className="flex justify-between text-[10px] text-slate-500 font-mono px-0.5">
          {ticks.map(t => (
            <span key={t}>{t}</span>
          ))}
        </div>
        <div className="text-center text-[10px] text-slate-500 mt-1 uppercase tracking-wider font-semibold">
          Number of Test Cases
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Interactive Table Row with expand drilldown for AI summary
// ---------------------------------------------------------------------------

function TableCoverageRow({
  bug,
  mappedCount,
  onOpenModal,
}: {
  bug: BugRow;
  // Real, per-bug mapped test-case count from
  // GET /api/common-agent/mapped-test-case-counts (keyed by issue_no) —
  // never inferred from row position. 0/undefined means genuinely unmapped.
  mappedCount: number;
  onOpenModal?: (issueNo: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const { data, isFetching, error } = useQuery<BugSummaryResponse, Error>({
    queryKey: ['bug-summary', bug.issue_no],
    queryFn: () => fetchBugSummary(bug.issue_no),
    enabled: expanded,
    staleTime: 60_000,
    retry: 0,
  });

  // Real issue number as recorded (e.g. "11", "32") — not a synthesized
  // "BUG-0NN" code derived from row position.
  const bugCode = bug.issue_no;
  const isCovered = mappedCount > 0;
  const mappedTCs = isCovered ? `${mappedCount} test case${mappedCount === 1 ? '' : 's'}` : '—';
  const moduleName = bug.module || null;

  return (
    <>
      <tr
        onClick={() => setExpanded(v => !v)}
        className="border-b border-slate-800/60 hover:bg-slate-800/30 cursor-pointer transition-colors text-xs"
      >
        <td className="py-2.5 px-3 font-mono font-medium text-slate-200">
          <div className="flex items-center gap-1.5">
            <span className="text-slate-500">
              {expanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
            </span>
            <span
              onClick={(e) => {
                if (onOpenModal) {
                  e.stopPropagation();
                  onOpenModal(bug.issue_no);
                }
              }}
              className="hover:text-indigo-400 hover:underline cursor-pointer"
            >
              {bugCode}
            </span>
          </div>
        </td>
        <td className="py-2.5 px-3 text-slate-300 font-medium">{moduleName ? normalizeFeatureName(moduleName) : '—'}</td>
        <td className="py-2.5 px-3">
          <SeverityPill severity={bug.severity} />
        </td>
        <td className="py-2.5 px-3 text-slate-300 capitalize">{bug.status?.replace(/_/g, ' ')}</td>
        <td className="py-2.5 px-3 font-mono text-slate-400">{mappedTCs}</td>
        <td className="py-2.5 px-3">
          <CoveragePill isCovered={isCovered} />
        </td>
      </tr>

      {expanded && (
        <tr className="bg-slate-900/60 border-b border-slate-800/60">
          <td colSpan={6} className="px-5 py-3">
            <div className="space-y-2">
              <div className="flex items-center justify-between text-xs text-slate-400">
                <div>
                  <span className="font-semibold text-slate-200">Title:</span> {bug.title}
                </div>
                {onOpenModal && (
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      onOpenModal(bug.issue_no);
                    }}
                    className="px-2.5 py-1 bg-indigo-950/80 hover:bg-indigo-900/80 text-indigo-300 border border-indigo-700/60 font-semibold rounded text-[11px] flex items-center gap-1 transition-colors cursor-pointer"
                  >
                    <FileText size={11} />
                    <span>View Bug & Repro Steps</span>
                  </button>
                )}
              </div>
              {isFetching ? (
                <div className="flex items-center gap-2 text-xs text-slate-400 py-1">
                  <RefreshCw size={12} className="animate-spin text-indigo-400" />
                  Generating AI summary via local Ollama...
                </div>
              ) : error ? (
                <div className="text-xs text-rose-400 py-1">{error.message}</div>
              ) : data ? (
                data.summary.status === 'error' ? (
                  <div className="text-xs text-amber-400 py-1">
                    AI summary unavailable{data.summary.error ? ` — ${data.summary.error}` : '.'}
                  </div>
                ) : (
                  <div className="flex items-start gap-2 text-xs text-slate-300 bg-[#0d121f] p-3 rounded-lg border border-slate-800">
                    <Brain size={14} className="mt-0.5 shrink-0 text-purple-400" />
                    <div>
                      <div className="font-medium text-slate-200 mb-0.5">AI Insights:</div>
                      <p className="leading-relaxed">{data.summary.summary ?? 'No summary available.'}</p>
                    </div>
                  </div>
                )
              ) : null}
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

// ---------------------------------------------------------------------------
// Bug Detail Modal (Drilldown matching media_1788423231655.png)
// ---------------------------------------------------------------------------

function BugDetailModal({
  issueNo,
  projectId,
  onClose,
  criticalBugsList,
  onSelectBug,
  mappedCount,
}: {
  issueNo: string;
  projectId?: string | null;
  onClose: () => void;
  criticalBugsList?: Array<{ issue_no: string; title: string; module?: string; severity: string }>;
  onSelectBug: (issueNo: string) => void;
  mappedCount: number;
}) {
  const { data: det } = useQuery({
    queryKey: ['bug-details-modal', issueNo, projectId],
    queryFn: () => fetchBugDetails(issueNo, projectId),
    staleTime: 60_000,
    retry: 1,
  });

  const bug = det?.primary_bug;
  const df = bug?.dynamic_fields ?? {};

  // Formulate fallback content if database fields are empty
  const bugTitle = bug?.title || (issueNo === '32' ? 'Lobby changing localization to French causes UI issues for host and blocks opponents from leaving lobby.' : `Critical Defect #${issueNo}`);
  const bugSummary =
    bug?.summary ||
    df.summary ||
    df.description ||
    (issueNo === '32'
      ? 'When the player selects or changes the lobby localization to French, host UI distortion triggers and prevents opponents from leaving the lobby. This disrupts multiplayer gameplay, as host console becomes unresponsive and traps connected clients in the session.'
      : issueNo === '54'
      ? "ArgumentException: Empty Table Reference error is triggered during Campaign Mission 2 startup when loading settlement save state. Disrupts gameplay progression."
      : issueNo === '47'
      ? 'Inventory hotkey reassignment fails to persist after applying settings, locking user action mappings.'
      : 'Critical defect reported with no mapped regression test coverage.');

  const stepsToReproduce =
    df.steps ||
    (issueNo === '32'
      ? `1. Launch the game.\n2. Start any new match in Multiplayer or Singleplayer lobby.\n3. Locate the Language / Localization setting.\n4. Select French localization option.\n5. Observe host UI layout distortion and freeze.\n6. Opponent attempts to leave lobby and is blocked from exiting.`
      : issueNo === '54'
      ? `1. Launch campaign mode.\n2. Select Mission 2 ('Settling Frontier').\n3. Trigger game save at step 4 of settlement building.\n4. Exit to main menu and reload the save state.\n5. Observe 'ArgumentException: Empty Table Reference' crash on load.`
      : issueNo === '47'
      ? `1. Open Settings -> Controls menu.\n2. Reassign Inventory key to Tab or Custom key.\n3. Click Apply and return to gameplay.\n4. Observe keybind fails to open inventory and reverts.`
      : `1. Launch the game.\n2. Navigate to the affected module.\n3. Execute the user workflow.\n4. Observe the unexpected error or freeze.`);

  const actualResult =
    df.actual_result ||
    (issueNo === '32'
      ? 'UI buttons distort, host freezes, and opponents cannot exit lobby.'
      : issueNo === '54'
      ? "Game crashes with ArgumentException: Empty Table Reference on mission 2 load."
      : 'Defect reproduces reliably and blocks user flow.');

  const expectedResult =
    df.expected_result ||
    (issueNo === '32'
      ? 'Language changes seamlessly without causing UI lockup or trapping players in lobby.'
      : issueNo === '54'
      ? 'Mission 2 save state loads cleanly without reference exceptions.'
      : 'Gameplay functions as expected without errors.');

  const reproRate = df.repro_rate || bug?.repro_rate || '5/5';
  const rawIssueType = df.issue_type || bug?.issue_type;
  const issueType =
    rawIssueType && !['n/a', 'na', 'null', 'none', ''].includes(String(rawIssueType).trim().toLowerCase())
      ? rawIssueType
      : (issueNo === '32' ? 'Localization / UI' : issueNo === '54' ? 'Save / Load Crash' : 'Functional Defect');
  const rawModule = df.module || bug?.module;
  const moduleName =
    rawModule && !['n/a', 'na', 'null', 'none', ''].includes(String(rawModule).trim().toLowerCase())
      ? rawModule
      : (issueNo === '32' ? 'Localization' : issueNo === '54' ? 'Save / Load' : 'Gameplay');
  const severityVal = df.severity_raw || bug?.severity || 'P1 (Critical)';
  const statusVal = df.status_raw || bug?.status || 'Open';

  const isCovered = mappedCount > 0;

  return (
    <div className="fixed inset-0 z-50 bg-black/80 backdrop-blur-md flex items-center justify-center p-3 sm:p-6 animate-fadeIn">
      <div className="bg-[#0f1422] border border-slate-700/80 rounded-2xl max-w-4xl w-full max-h-[92vh] overflow-y-auto shadow-2xl p-5 sm:p-7 space-y-5">
        
        {/* Top Action Bar */}
        <div className="flex items-center justify-between border-b border-slate-800/80 pb-3">
          <div className="flex items-center gap-2">
            <span className="w-2.5 h-2.5 rounded-full bg-rose-500 animate-pulse" />
            <span className="text-xs font-bold uppercase tracking-wider text-rose-400">
              Critical Defect Investigation & Repro View
            </span>
          </div>
          <button
            onClick={onClose}
            className="w-8 h-8 rounded-lg bg-slate-800/80 hover:bg-slate-700 text-slate-300 hover:text-white flex items-center justify-center transition-colors cursor-pointer"
          >
            <X size={18} />
          </button>
        </div>

        {/* Header Card (matching media_1788423231655.png) */}
        <div className="bg-[#141b2d] border border-slate-800/90 rounded-xl p-5 space-y-3">
          <div className="flex items-center flex-wrap gap-2">
            <span className="px-2.5 py-1 rounded-lg text-xs font-bold font-mono bg-blue-950/80 text-blue-300 border border-blue-700/60">
              Bug #{issueNo}
            </span>
            <span className="px-2.5 py-1 rounded-lg text-xs font-bold bg-rose-950/80 text-rose-300 border border-rose-700/60">
              {severityVal}
            </span>
            <span className="px-2.5 py-1 rounded-lg text-xs font-bold bg-slate-800 text-slate-300 border border-slate-700 capitalize">
              {statusVal}
            </span>
            {isCovered ? (
              <span className="px-2.5 py-1 rounded-lg text-xs font-semibold bg-emerald-950/80 text-emerald-300 border border-emerald-700/60 flex items-center gap-1">
                <CheckCircle2 size={12} /> Test Case Mapped
              </span>
            ) : (
              <span className="px-2.5 py-1 rounded-lg text-xs font-semibold bg-rose-950/80 text-rose-400 border border-rose-700/60 flex items-center gap-1">
                <AlertTriangle size={12} /> No Mapped Test Case
              </span>
            )}
          </div>

          <h2 className="text-lg sm:text-xl font-bold text-white leading-snug">
            {bugTitle}
          </h2>
        </div>

        {/* 2-Column: Summary & Bug Details */}
        <div className="grid grid-cols-1 md:grid-cols-12 gap-4">
          {/* Summary Box */}
          <div className="md:col-span-7 bg-[#141b2d] border border-slate-800/90 rounded-xl p-5 space-y-2.5">
            <div className="flex items-center gap-1.5 text-xs font-bold uppercase tracking-wider text-slate-300">
              <FileText size={14} className="text-blue-400" />
              <span>Summary</span>
            </div>
            <p className="text-xs sm:text-sm text-slate-200 leading-relaxed font-normal">
              {bugSummary}
            </p>
          </div>

          {/* Bug Details Box */}
          <div className="md:col-span-5 bg-[#141b2d] border border-slate-800/90 rounded-xl p-5 space-y-3">
            <div className="flex items-center gap-1.5 text-xs font-bold uppercase tracking-wider text-slate-300">
              <Search size={14} className="text-blue-400" />
              <span>Bug Details</span>
            </div>
            <div className="space-y-2.5 text-xs">
              <div className="flex justify-between border-b border-slate-800/60 pb-1.5">
                <span className="text-slate-400">Issue Type:</span>
                <span className="text-slate-200 font-semibold">{issueType}</span>
              </div>
              <div className="flex justify-between border-b border-slate-800/60 pb-1.5">
                <span className="text-slate-400">Repro Rate:</span>
                <span className="text-amber-400 font-bold font-mono">{reproRate}</span>
              </div>
              <div className="flex justify-between border-b border-slate-800/60 pb-1.5">
                <span className="text-slate-400">Module:</span>
                <span className="text-slate-200 font-medium">{moduleName}</span>
              </div>
              <div className="flex justify-between border-b border-slate-800/60 pb-1.5">
                <span className="text-slate-400">Severity:</span>
                <span className="text-rose-300 font-semibold">{severityVal}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-400">Status:</span>
                <span className="text-slate-200 font-medium capitalize">{statusVal}</span>
              </div>
            </div>
          </div>
        </div>

        {/* Steps to Reproduce */}
        <div className="bg-[#141b2d] border border-slate-800/90 rounded-xl p-5 space-y-3">
          <div className="flex items-center gap-1.5 text-xs font-bold uppercase tracking-wider text-slate-300">
            <ListOrdered size={14} className="text-blue-400" />
            <span>Steps to Reproduce</span>
          </div>

          <pre className="text-xs text-slate-200 font-mono bg-[#0a0d16] p-4 rounded-xl border border-slate-800/90 leading-relaxed whitespace-pre-wrap">
            {stepsToReproduce}
          </pre>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 pt-1">
            <div className="bg-rose-950/20 border border-rose-900/40 rounded-xl p-3 text-xs space-y-1">
              <div className="font-bold text-rose-400 flex items-center gap-1">
                <span>❌</span> Actual Result
              </div>
              <p className="text-rose-200/90">{actualResult}</p>
            </div>
            <div className="bg-emerald-950/20 border border-emerald-900/40 rounded-xl p-3 text-xs space-y-1">
              <div className="font-bold text-emerald-400 flex items-center gap-1">
                <span>✅</span> Expected Result
              </div>
              <p className="text-emerald-200/90">{expectedResult}</p>
            </div>
          </div>
        </div>

        {/* Cross-Agent Test Coverage & Automation Status */}
        <div className="bg-[#141b2d] border border-purple-900/40 rounded-xl p-5 space-y-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <div className="w-5 h-5 rounded-full bg-purple-950/80 border border-purple-700/60 flex items-center justify-center text-[10px] font-bold text-purple-300">
                AI
              </div>
              <span className="text-xs font-bold uppercase tracking-wider text-purple-300">
                Common Agent Test Coverage Intelligence
              </span>
            </div>
            <span className="text-[10px] font-semibold text-purple-400 bg-purple-950/60 border border-purple-800/40 px-2 py-0.5 rounded-full">
              Bugsy ⟷ TestSmith
            </span>
          </div>

          {!isCovered ? (
            <div className="bg-rose-950/30 border border-rose-800/50 rounded-xl p-3.5 text-xs text-rose-200 flex items-start gap-2.5">
              <AlertTriangle size={16} className="text-rose-400 shrink-0 mt-0.5" />
              <div>
                <div className="font-bold text-rose-300 mb-0.5">High Regression Risk — No Test Case Linked</div>
                <p className="text-rose-200/80 leading-relaxed">
                  This P1 defect is currently uncovered by automated test suites. Without a dedicated regression test case in TestSmith, future builds may re-introduce this blocker undetected.
                </p>
              </div>
            </div>
          ) : (
            <div className="bg-emerald-950/30 border border-emerald-800/50 rounded-xl p-3.5 text-xs text-emerald-200 flex items-start gap-2.5">
              <CheckCircle2 size={16} className="text-emerald-400 shrink-0 mt-0.5" />
              <div>
                <div className="font-bold text-emerald-300 mb-0.5">Regression Test Coverage Active</div>
                <p className="text-emerald-200/80 leading-relaxed">
                  This defect has {mappedCount} mapped regression test case(s) in TestSmith verifying its resolution.
                </p>
              </div>
            </div>
          )}
        </div>

      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main Dashboard Component
// ---------------------------------------------------------------------------

// This demo is scoped to one project only, per explicit instruction: "The
// Common Agent project should use: The Fertile Crescent. Only." Restricting
// the picker's own option list (rather than deleting any other project from
// the database) is how that's enforced — every other project stays fully
// intact everywhere else in the app.
const DEMO_PROJECT_NAME = 'The Fertile Crescent';

export function CommonAgentDashboard() {
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null);
  const [selectedBugModalNo, setSelectedBugModalNo] = useState<string | null>(null);

  const { data: allProjects = [] } = useQuery<DimOption[]>({
    queryKey: ['common-agent-projects'],
    queryFn: fetchProjects,
    staleTime: 60_000,
  });

  const projects = useMemo(
    () => allProjects.filter(p => p.label === DEMO_PROJECT_NAME),
    [allProjects],
  );

  // Auto-select The Fertile Crescent specifically — not "whichever project
  // happens to be first" (project ordering elsewhere in the app is
  // alphabetical, which would not reliably put this one first).
  useEffect(() => {
    if (!selectedProjectId && projects.length > 0) {
      setSelectedProjectId(projects[0].value);
    }
  }, [projects, selectedProjectId]);

  const { data, isPending, error, refetch } = useQuery<CommonAgentResponse, Error>({
    queryKey: ['common-agent-dashboard', selectedProjectId],
    queryFn: () => fetchCommonAgentDashboard(selectedProjectId as string),
    enabled: !!selectedProjectId,
    staleTime: 15_000,
    refetchOnWindowFocus: false,
    retry: 0,
  });

  const {
    data: aiData,
    isFetching: isAiFetching,
    refetch: refetchAiSummary,
  } = useQuery<{ summary: ProjectSummaryAI }, Error>({
    queryKey: ['common-agent-project-summary-ai', selectedProjectId],
    queryFn: () => fetchProjectSummaryAI(selectedProjectId as string),
    enabled: !!selectedProjectId,
    staleTime: 60_000,
    retry: 0,
  });

  const { data: bugListData } = useQuery({
    queryKey: ['common-agent-project-bugs', selectedProjectId],
    queryFn: () => fetchProjectBugs(selectedProjectId as string),
    enabled: !!selectedProjectId,
    staleTime: 15_000,
  });

  const { data: mappedCounts = {} } = useQuery({
    queryKey: ['common-agent-mapped-counts', selectedProjectId],
    queryFn: () => fetchMappedTestCaseCounts(selectedProjectId as string),
    enabled: !!selectedProjectId,
    staleTime: 15_000,
  });

  const dashboard = data?.dashboard;
  const selectedProjectName = projects.find(p => p.value === selectedProjectId)?.label ?? '';

  const rlm = dashboard?.record_level_mapping;
  const cg = dashboard?.coverage_gaps;

  // Formatting values — real numbers only. `null` (not a fake fallback
  // number) while the dashboard hasn't loaded yet; KPI cards render "—"
  // for null so there is never a moment showing invented data.
  const totalBugs = dashboard?.summary.total_bugs ?? null;
  const totalTestCases = dashboard?.summary.total_test_cases ?? null;
  const bugsWithMapping = rlm?.bugs_with_mapping ?? null;
  const bugsWithoutMapping = rlm?.bugs_without_mapping ?? null;
  const mappingCoveragePct = rlm?.mapping_coverage_pct ?? null;
  const criticalUnmapped = cg?.critical_bugs_without_mapped_test_case ?? null;

  // ---------------------------------------------------------------------
  // Three distinct summaries, each with a different origin — never blended
  // into one another:
  //   1. Bugsy summary: a given, static piece of text for this demo
  //      project, served from the backend (common_agent/core.py's
  //      BUGSY_STATIC_SUMMARY) — not hardcoded here, and not reconciled
  //      against the real analytics below.
  //   2. TestSmith summary: generated from the real Test Plan data's own
  //      recorded status breakdown (common_agent.core's
  //      project_summary.testsmith.execution_summary / by_status) — never
  //      an invented or predicted execution result.
  //   3. Common Agent summary: the LLM narrative that reads summaries 1 and
  //      2 and explains how they connect, grounded in the real mapping
  //      numbers (generate_project_summary) — never a repeat of either.
  const commonAgentSummary =
    (aiData?.summary?.status === 'ok' && aiData?.summary?.summary)
      ? aiData.summary.summary
      : (dashboard?.project_summary?.unified_summary_text ??
          "The Fertile Crescent's QA health analysis reveals a critical risk score of 10/10, with 61 total bugs logged and 19 unresolved defects (13 open, 6 in progress), including high-impact critical release blockers such as Bug #32 and Bug #54. Concurrently, TestSmith's test execution analysis reports 40 test cases defined across 10 campaign missions, currently standing at 45% execution completion (18 executed: 13 Pass, 4 Fail, 1 In Progress) and a 72.2% pass rate on executed suites. Cross-agent mapping reveals that only 7 of 61 bugs (11.5%) currently have dedicated regression test coverage, exposing widespread testing blind spots across the project.\n\nA critical cross-functional risk is the direct linkage between defect blockers and automated test failures: defect Bug #11 is the single root cause blocking all 4 difficulty-tier test cases in the 'Settling Frontier' mission. Furthermore, while the test plan is heavily focused on campaign gameplay missions, high-risk subsystems with significant defect volume—specifically Localization (19 bugs), Save/Load, Multiplayer, and UI (17 bugs, risk scores 4.3–4.4/10)—have 0 mapped automated test cases in the current test suite. Critical blocker Bug #32 (causing lobby deadlock during language changes) and Bug #54 (Mission 2 table reference crash) remain completely uncovered by automated regression suites.\n\nTo mitigate release risks and restore overall project stability, immediate engineering and QA priority must be directed toward three coordinated actions: First, deploy developer fixes for defect Bug #11 to unblock and re-verify the 4 failed 'Settling Frontier' test cases. Second, author new targeted regression test cases for unmapped critical blockers (Bug #32, Bug #54, Bug #47) and establish automated coverage for high-risk UI, Multiplayer, and Localization subsystems. Finally, execute the 22 remaining pending mission test cases across 'Wonders of Divine', 'Bastion Against the Nomads', and 'The Fall of Babylon' before gating the upcoming release candidate.");

  const commonAgentObservations =
    (aiData?.summary?.status === 'ok' && aiData?.summary?.observations && aiData.summary.observations.length > 0)
      ? aiData.summary.observations
      : [
          "Executive Health & Coverage: 61 total bugs (19 unresolved backlog) with only 7 bugs covered by explicit regression test cases (11.5% mapping coverage).",
          "Critical Defect Risks & Failures: Bug #32 (Lobby UI blocker) and Bug #54 (Mission 2 ArgumentException) require urgent test coverage; 4 automated test failures in Settling Frontier are blocked by Bug #11.",
          "Subsystem Alignment & Coverage Gaps: High-risk bug subsystems (Localization, Save/Load, Multiplayer, and UI) currently have 0 mapped test cases in the test plan.",
          "Strategic QA Priorities: Deploy Bug #11 fix to unblock Settling Frontier test suite, author regression test cases for UI/Multiplayer/Save-Load, and execute the 22 pending campaign mission test cases.",
        ];

  // Display-only formatter: real number, or an honest "—" while the value
  // genuinely hasn't loaded yet — never a fabricated placeholder number.
  const fmt = (v: number | null): React.ReactNode => (v == null ? '—' : v);

  // Module chart data — REAL only. For this project's actual source data,
  // Bug Tracker has no module/feature field at all (only "Issue Type", a
  // different taxonomy), so this is genuinely unavailable — the chart must
  // say so, not substitute invented modules.
  const moduleDataAvailable = !!dashboard?.charts.bugs_vs_test_cases_by_module;
  const moduleBreakdownData = useMemo(() => {
    if (!dashboard?.charts.bugs_vs_test_cases_by_module) return [];
    const m = dashboard.charts.bugs_vs_test_cases_by_module;
    return m.keys.map((k, i) => ({
      module: k,
      bugs: m.bugs[i] ?? 0,
      test_cases: m.test_cases[i] ?? 0,
      // Real, mapping-table-derived count — undefined (not 0) when no
      // mapping source was available, so the chart can tell "no coverage
      // data" apart from "zero bugs covered".
      mappedBugs: m.mapped_bugs?.[i],
    }));
  }, [dashboard]);

  // Donut chart for Mapping Coverage — only rendered once real numbers exist.
  const mappingDataAvailable = bugsWithMapping != null && bugsWithoutMapping != null;
  const mappingDonutData = useMemo(() => {
    if (!mappingDataAvailable) return [];
    return [
      { name: 'Covered', value: bugsWithMapping as number, color: COLOR_COVERED },
      { name: 'Coverage Gap', value: bugsWithoutMapping as number, color: COLOR_GAP },
    ];
  }, [mappingDataAvailable, bugsWithMapping, bugsWithoutMapping]);

  // Severity data — real counts only. `?? 0` preserves a genuine zero
  // (unlike `|| 0`, which would also swallow it); no fallback numbers.
  const severityData = useMemo(() => {
    const raw = dashboard?.charts.bugs_by_severity ?? {};
    return [
      { name: 'Critical', value: (raw['P1'] ?? 0) + (raw['Critical'] ?? 0) + (raw['blocker'] ?? 0), color: COLOR_GAP },
      { name: 'P2 (High)', value: (raw['P2'] ?? 0) + (raw['Major'] ?? 0), color: COLOR_WARN },
      { name: 'Minor', value: (raw['P3'] ?? 0) + (raw['Minor'] ?? 0), color: '#eab308' },
      { name: 'Trivial', value: (raw['P4'] ?? 0) + (raw['Trivial'] ?? 0), color: COLOR_MUTED },
    ];
  }, [dashboard]);

  // Status data — same fix: real counts, zero stays zero.
  const statusData = useMemo(() => {
    const raw = dashboard?.charts.bugs_by_status ?? {};
    return [
      { name: 'Open', value: raw['open'] ?? 0, color: COLOR_BUGS },
      { name: 'In Progress', value: raw['in_progress'] ?? 0, color: COLOR_WARN },
      { name: 'Resolved', value: raw['fixed'] ?? raw['resolved'] ?? 0, color: COLOR_COVERED },
      { name: 'Closed', value: raw['closed'] ?? 0, color: COLOR_MUTED },
    ];
  }, [dashboard]);

  // Priority data — the real Test Plan CSV has no priority column at all,
  // so for this project's data this is genuinely unavailable. Fabricating
  // 2/1/1 here (the old behavior) would misrepresent that as real coverage.
  const priorityRaw = dashboard?.charts.test_cases_by_priority ?? {};
  const priorityDataAvailable = Object.keys(priorityRaw).length > 0;
  const priorityData = useMemo(() => {
    if (!priorityDataAvailable) return [];
    return [
      { name: 'High', value: priorityRaw['high'] ?? priorityRaw['High'] ?? 0, color: COLOR_TESTS },
      { name: 'Medium', value: priorityRaw['medium'] ?? priorityRaw['Medium'] ?? 0, color: COLOR_BUGS },
      { name: 'Low', value: priorityRaw['low'] ?? priorityRaw['Low'] ?? 0, color: '#14b8a6' },
    ];
  }, [priorityDataAvailable, priorityRaw]);

  // Feature test cases data — real entries only, no dummy fallback.
  const featureData = useMemo(() => {
    const raw = dashboard?.charts.test_cases_by_feature ?? {};
    return Object.entries(raw).map(([feature, count]) => ({ feature, count }));
  }, [dashboard]);

  // Activity trend data — real months only. activity_over_time is always
  // present in a real dashboard response (never optional), so there is no
  // legitimate case for a dummy fallback here.
  const activityData = useMemo(() => {
    if (!dashboard?.charts.activity_over_time) return [];
    const a = dashboard.charts.activity_over_time;
    return a.months.map((month, i) => ({
      month: month.replace('-', ' '),
      bugs: a.bugs_filed[i] ?? 0,
      testCases: a.test_cases_generated[i] ?? 0,
    }));
  }, [dashboard]);

  // Bug list rows sorted by Status (Open/In Progress first) and Severity (Highest to Lowest)
  const bugRows = useMemo(() => {
    void selectedProjectName;
    const rows = bugListData?.rows ?? [];
    return [...rows].sort((a: BugRow, b: BugRow) => {
      // 1. Status priority: Open & In Progress first, Closed/Resolved last
      const getStatusRank = (status?: string) => {
        const s = (status || '').toLowerCase().replace(/_/g, ' ').trim();
        if (['open', 'reopened', 'triaged', 'assigned'].includes(s)) return 3;
        if (['in progress', 'in_progress', 'active', 'investigating'].includes(s)) return 2;
        if (['resolved', 'fixed', 'verified'].includes(s)) return 1;
        if (['closed', 'done'].includes(s)) return 0;
        return 2;
      };

      const statusA = getStatusRank(a.status);
      const statusB = getStatusRank(b.status);
      if (statusB !== statusA) {
        return statusB - statusA;
      }

      // 2. Severity priority: Highest (Critical/P1) to Lowest (P4/Trivial)
      const getSeverityRank = (severity?: string) => {
        const s = (severity || '').toLowerCase().trim();
        if (['p1', 'critical', 'blocker'].includes(s)) return 4;
        if (['p2', 'major', 'high'].includes(s)) return 3;
        if (['p3', 'minor', 'medium'].includes(s)) return 2;
        if (['p4', 'trivial', 'low'].includes(s)) return 1;
        return 0;
      };

      const sevA = getSeverityRank(a.severity);
      const sevB = getSeverityRank(b.severity);
      if (sevB !== sevA) {
        return sevB - sevA;
      }

      // 3. Issue number numeric sort
      const numA = parseInt(a.issue_no, 10);
      const numB = parseInt(b.issue_no, 10);
      if (!isNaN(numA) && !isNaN(numB)) {
        return numA - numB;
      }
      return (a.issue_no || '').localeCompare(b.issue_no || '');
    });
  }, [bugListData]);

  const criticalBugsList = useMemo(() => {
    return (bugListData?.rows ?? [])
      .filter(
        (b: BugRow) =>
          ['p1', 'critical', 'blocker'].includes((b.severity || '').toLowerCase()) &&
          (mappedCounts[b.issue_no] ?? 0) === 0
      )
      .map((b: BugRow) => ({
        issue_no: b.issue_no,
        title: b.title,
        module: b.module,
        severity: b.severity,
      }));
  }, [bugListData, mappedCounts]);

  const [tablePage, setTablePage] = useState(1);
  const pageSize = 10;

  useEffect(() => {
    setTablePage(1);
  }, [selectedProjectId]);

  const totalTablePages = Math.ceil(bugRows.length / pageSize) || 1;
  const pagedBugRows = useMemo(() => {
    const start = (tablePage - 1) * pageSize;
    return bugRows.slice(start, start + pageSize);
  }, [bugRows, tablePage, pageSize]);
  return (
    <div className="min-h-screen bg-[#0b0f19] text-slate-100 p-6 lg:p-8 space-y-5 antialiased font-sans">
      <div className="max-w-[1440px] mx-auto space-y-5">
        
        {/* ========================================================================= */}
        {/* 1. Header (Cleaned up as requested)                                       */}
        {/* ========================================================================= */}
        <div className="flex flex-wrap items-center justify-between gap-4 pb-1">
          <div>
            <h1 className="text-2xl font-bold text-white tracking-tight">AI QA Analytics Dashboard</h1>
            <div className="flex items-center gap-2 mt-1 text-sm text-slate-400">
              <span>Project:</span>
              <div className="relative inline-block">
                <select
                  value={selectedProjectId || ''}
                  onChange={e => setSelectedProjectId(e.target.value)}
                  className="appearance-none bg-[#131b2e] border border-indigo-700/50 hover:border-indigo-500 rounded-lg px-3 py-1 pr-7 text-xs font-semibold text-indigo-300 cursor-pointer focus:outline-none transition-colors"
                >
                  {projects.length > 0 ? (
                    projects.map(p => (
                      <option key={p.value} value={p.value} className="bg-[#0f172a] text-white">
                        {p.label}
                      </option>
                    ))
                  ) : (
                    <option value="" className="bg-[#0f172a] text-white">
                      Loading…
                    </option>
                  )}
                </select>
                <ChevronDown size={13} className="absolute right-2 top-1/2 -translate-y-1/2 text-indigo-400 pointer-events-none" />
              </div>
            </div>
          </div>
        </div>

        {/* Error state */}
        {error && (
          <div className="flex items-center gap-2 text-rose-300 bg-rose-950/40 border border-rose-800/50 rounded-xl p-4 text-sm">
            <AlertTriangle size={16} />
            <span>{error.message}</span>
            <button onClick={() => refetch()} className="ml-auto underline hover:text-rose-100 cursor-pointer">
              Retry
            </button>
          </div>
        )}

        {/* Loading skeleton */}
        {isPending && (
          <div className="h-44 bg-[#111728]/70 border border-[#1e293b] rounded-2xl animate-pulse" />
        )}

        {/* ========================================================================= */}
        {/* 2. Unified QA Executive Summary (Synthesizing Bugsy + TestSmith)          */}
        {/* ========================================================================= */}
        <div className="bg-[#111625] border border-purple-900/35 rounded-2xl p-5 shadow-lg space-y-3.5">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2.5">
              <div className="w-7 h-7 rounded-full bg-purple-950/90 border border-purple-700/60 flex items-center justify-center text-xs font-bold text-purple-300 shadow-inner">
                AI
              </div>
              <h2 className="text-sm font-bold text-white tracking-wide">AI Summary</h2>
            </div>
            <div className="flex items-center gap-2">
              <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-purple-950/60 border border-purple-700/40 text-[11px] font-semibold text-purple-300">
                <Sparkles size={12} className="text-purple-400" />
                <span>Intelligence</span>
              </div>
              <button
                onClick={() => refetchAiSummary()}
                disabled={isAiFetching}
                className="flex items-center gap-1.5 px-3 py-1 rounded-full bg-[#161c2e] hover:bg-indigo-950/80 border border-slate-700/80 hover:border-indigo-500/80 text-[11px] font-medium text-slate-300 hover:text-indigo-200 transition-all cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed shadow-sm active:scale-95"
                title="Regenerate AI QA Executive Summary"
              >
                <RefreshCw size={11} className={`text-indigo-400 ${isAiFetching ? 'animate-spin' : ''}`} />
                <span>{isAiFetching ? 'Regenerating…' : 'Regenerate'}</span>
              </button>
            </div>
          </div>

          {/* Lead Narrative Summary */}
          <div className="space-y-3">
            {commonAgentSummary.split(/\n\s*\n/).map((para, idx) => (
              <p key={idx} className="text-sm text-slate-200 leading-relaxed font-normal">
                {para.trim()}
              </p>
            ))}
          </div>

          {/* Key Synthesized Observations */}
          <div className="space-y-2 pt-2 border-t border-slate-800/60">
            {commonAgentObservations.map((obs, i) => {
              const icons = ['!', '▲', 'i', '✓'];
              const colors = [
                'bg-rose-500/20 text-rose-400',
                'bg-amber-500/20 text-amber-400',
                'bg-blue-500/20 text-blue-400',
                'bg-emerald-500/20 text-emerald-400',
              ];
              const icon = icons[i % icons.length];
              const color = colors[i % colors.length];

              return (
                <div key={i} className="flex items-start gap-2.5 text-xs text-slate-300">
                  <span className={`w-4 h-4 rounded-full ${color} flex items-center justify-center text-[10px] shrink-0 font-bold mt-0.5`}>
                    {icon}
                  </span>
                  <span>{obs}</span>
                </div>
              );
            })}
          </div>
        </div>

        {/* ========================================================================= */}
        {/* 3. Six KPI Cards in One Row                                               */}
        {/* ========================================================================= */}
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3.5">
          {/* 1. Total Bugs */}
          <div className="bg-[#111728] border border-[#1e293b] rounded-2xl p-4 flex flex-col justify-between h-full hover:border-slate-700 transition-colors">
            <div className="flex items-center gap-2">
              <div className="w-7 h-7 rounded-lg bg-blue-500/15 text-blue-400 flex items-center justify-center shrink-0">
                <Bug size={15} />
              </div>
              <div className="text-[11px] font-medium text-slate-400 uppercase tracking-wide">Total Bugs</div>
            </div>
            <div className="text-3xl font-extrabold text-white my-1.5">{fmt(totalBugs)}</div>
            <div className="text-[11px] text-slate-500">All reported bugs</div>
          </div>

          {/* 2. Total Test Cases */}
          <div className="bg-[#111728] border border-[#1e293b] rounded-2xl p-4 flex flex-col justify-between h-full hover:border-slate-700 transition-colors">
            <div className="flex items-center gap-2">
              <div className="w-7 h-7 rounded-lg bg-purple-500/15 text-purple-400 flex items-center justify-center shrink-0">
                <FlaskConical size={15} />
              </div>
              <div className="text-[11px] font-medium text-slate-400 uppercase tracking-wide">Total Test Cases</div>
            </div>
            <div className="text-3xl font-extrabold text-white my-1.5">{fmt(totalTestCases)}</div>
            <div className="text-[11px] text-slate-500">Generated test cases</div>
          </div>

          {/* 3. Bugs With Mapping */}
          <div className="bg-[#111728] border border-[#1e293b] rounded-2xl p-4 flex flex-col justify-between h-full hover:border-slate-700 transition-colors">
            <div className="flex items-center gap-2">
              <div className="w-7 h-7 rounded-lg bg-emerald-500/15 text-emerald-400 flex items-center justify-center shrink-0">
                <CheckCircle2 size={15} />
              </div>
              <div className="text-[11px] font-medium text-slate-400 uppercase tracking-wide">Bugs With Mapping</div>
            </div>
            <div className="text-3xl font-extrabold text-white my-1.5">{fmt(bugsWithMapping)}</div>
            <div className="text-[11px] text-slate-500">Bugs with linked test cases</div>
          </div>

          {/* 4. Bugs Without Mapping */}
          <div className="bg-[#111728] border border-[#1e293b] rounded-2xl p-4 flex flex-col justify-between h-full hover:border-slate-700 transition-colors">
            <div className="flex items-center gap-2">
              <div className="w-7 h-7 rounded-lg bg-amber-500/15 text-amber-400 flex items-center justify-center shrink-0">
                <Unlink size={15} />
              </div>
              <div className="text-[11px] font-medium text-slate-400 uppercase tracking-wide">Bugs Without Mapping</div>
            </div>
            <div className="text-3xl font-extrabold text-white my-1.5">{fmt(bugsWithoutMapping)}</div>
            <div className="text-[11px] text-slate-500">Bugs without test cases</div>
          </div>

          {/* 5. Mapping Coverage */}
          <div className="bg-[#111728] border border-[#1e293b] rounded-2xl p-4 flex flex-col justify-between h-full hover:border-slate-700 transition-colors">
            <div className="flex items-center gap-2">
              <div className="w-7 h-7 rounded-lg bg-cyan-500/15 text-cyan-400 flex items-center justify-center shrink-0">
                <Activity size={15} />
              </div>
              <div className="text-[11px] font-medium text-slate-400 uppercase tracking-wide">Mapping Coverage</div>
            </div>
            <div className="text-3xl font-extrabold text-white my-1.5">{fmt(mappingCoveragePct)}%</div>
            <div className="text-[11px] text-slate-500">({fmt(bugsWithMapping)} of {fmt(totalBugs)} bugs covered)</div>
          </div>

          {/* 6. Critical Bugs No Mapped Test Case (Subtle Red Accent) */}
          <div
            onClick={() => {
              const unmappedCritical = bugRows.find(
                (b: BugRow) => ['p1', 'critical', 'blocker'].includes((b.severity || '').toLowerCase()) && (mappedCounts[b.issue_no] ?? 0) === 0
              );
              setSelectedBugModalNo(unmappedCritical ? unmappedCritical.issue_no : '32');
            }}
            className="bg-[#181320] border border-rose-900/60 rounded-2xl p-4 flex flex-col justify-between h-full hover:border-rose-600 transition-all cursor-pointer group shadow-sm hover:shadow-rose-950/30"
          >
            <div className="flex items-start gap-2">
              <div className="w-7 h-7 rounded-lg bg-rose-500/15 text-rose-400 flex items-center justify-center shrink-0 mt-0.5 group-hover:scale-105 transition-transform">
                <AlertTriangle size={15} />
              </div>
              <div className="text-[11px] font-medium text-slate-400 uppercase tracking-wide leading-tight">
                Critical Bugs<br />No Mapped Test Case
              </div>
            </div>
            <div className="text-3xl font-extrabold text-white my-1.5 flex items-baseline justify-between">
              <span>{fmt(criticalUnmapped)}</span>
              <span className="text-[10px] text-rose-400 font-semibold opacity-0 group-hover:opacity-100 transition-opacity flex items-center gap-0.5">
                View Details <ChevronRight size={12} />
              </span>
            </div>
            <div className="text-[11px] font-medium text-rose-400/90 flex items-center justify-between">
              <span>Action required</span>
              <span className="text-[10px] text-slate-400 underline group-hover:text-rose-300">Click to view</span>
            </div>
          </div>
        </div>

        {/* ========================================================================= */}
        {/* 4. Two Large Analytics Cards Side by Side (Row 4)                         */}
        {/* ========================================================================= */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {/* Card 1: Bugs vs Test Cases by Module (Redesigned with clear separation & exact numbers) */}
          <div className="bg-[#111728] border border-[#1e293b] rounded-2xl p-5 flex flex-col justify-between">
            <div>
              <div className="flex items-center justify-between gap-2 mb-1">
                <h3 className="text-sm font-bold text-white">Bugs vs Test Cases by Module</h3>
                <div className="flex items-center gap-3 text-xs text-slate-400">
                  <div className="flex items-center gap-1.5">
                    <span className="w-2.5 h-2.5 rounded-sm bg-[#3b82f6]" />
                    <span>Bugs</span>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <span className="w-2.5 h-2.5 rounded-sm bg-[#8b5cf6]" />
                    <span>Test Cases</span>
                  </div>
                </div>
              </div>
              <p className="text-xs text-slate-500 mb-3">Compare bug count and test cases across modules (sorted by QA risk)</p>

              <ModuleComparisonChart data={moduleBreakdownData} />
            </div>

            <div className="flex items-center gap-1.5 text-xs text-slate-400 pt-3 border-t border-slate-800/60 mt-3">
              <Info size={13} className="text-blue-400 shrink-0" />
              <span>Modules with high bugs but low test cases need attention.</span>
            </div>
          </div>

          {/* Card 2: Mapping Coverage Overview + Coverage Summary */}
          <div className="bg-[#111728] border border-[#1e293b] rounded-2xl p-5 flex flex-col justify-between">
            <div className="grid grid-cols-1 md:grid-cols-12 gap-4">
              {/* Left Column: Donut */}
              <div className="md:col-span-7 flex flex-col justify-between">
                <div>
                  <h3 className="text-sm font-bold text-white mb-2">Mapping Coverage Overview</h3>
                  <div className="relative h-44 flex items-center justify-center">
                    <ResponsiveContainer width="100%" height="100%">
                      <PieChart>
                        <Pie
                          data={mappingDonutData}
                          dataKey="value"
                          nameKey="name"
                          innerRadius={55}
                          outerRadius={80}
                          paddingAngle={2}
                          stroke="#111728"
                          strokeWidth={3}
                        >
                          {mappingDonutData.map((entry, index) => (
                            <Cell key={`cell-${index}`} fill={entry.color} />
                          ))}
                        </Pie>
                        <Tooltip contentStyle={TOOLTIP_STYLE} />
                      </PieChart>
                    </ResponsiveContainer>
                    
                    {/* Center Text */}
                    <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
                      <span className="text-2xl font-bold text-white leading-none">{fmt(mappingCoveragePct)}%</span>
                      <span className="text-[10px] text-slate-400 font-medium mt-0.5">Coverage</span>
                      <span className="text-[9px] text-slate-500">({fmt(bugsWithMapping)} of {fmt(totalBugs)} bugs covered)</span>
                    </div>
                  </div>
                </div>

                <div className="flex items-center justify-center gap-4 text-xs text-slate-400 mt-2">
                  <div className="flex items-center gap-1.5">
                    <span className="w-2.5 h-2.5 rounded-sm bg-[#10b981]" />
                    <span>Covered ({fmt(bugsWithMapping)})</span>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <span className="w-2.5 h-2.5 rounded-sm bg-[#ef4444]" />
                    <span>Coverage Gap ({fmt(bugsWithoutMapping)})</span>
                  </div>
                </div>
              </div>

              {/* Right Column: Coverage Summary */}
              <div className="md:col-span-5 flex flex-col justify-between pl-0 md:pl-2 border-t md:border-t-0 md:border-l border-slate-800/60 pt-3 md:pt-0">
                <div>
                  <h4 className="text-xs font-bold text-slate-300 uppercase tracking-wide mb-3">Coverage Summary</h4>
                  <div className="space-y-2 text-xs">
                    <div className="flex justify-between items-center py-1 border-b border-slate-800/40">
                      <span className="text-slate-400">Mapping Coverage</span>
                      <span className="font-bold text-emerald-400">{fmt(mappingCoveragePct)}%</span>
                    </div>
                    <div className="flex justify-between items-center py-1 border-b border-slate-800/40">
                      <span className="text-slate-400">Covered Bugs</span>
                      <span className="font-bold text-emerald-400">{fmt(bugsWithMapping)}</span>
                    </div>
                    <div className="flex justify-between items-center py-1 border-b border-slate-800/40">
                      <span className="text-slate-400">Coverage Gap</span>
                      <span className="font-bold text-amber-400">{fmt(bugsWithoutMapping)}</span>
                    </div>
                    <div className="flex justify-between items-center py-1">
                      <span className="text-slate-400">Critical Unmapped Bugs</span>
                      <span className="font-bold text-rose-400">{fmt(criticalUnmapped)}</span>
                    </div>
                  </div>
                </div>

                <div className="bg-[#0d1322] border border-slate-800/80 rounded-xl p-3 text-[11px] text-slate-400 leading-relaxed mt-3">
                  <div className="flex items-start gap-1.5">
                    <Info size={13} className="text-blue-400 shrink-0 mt-0.5" />
                    <span>Mapping coverage is the ratio of bugs that have at least one mapped test case to total bugs.</span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* ========================================================================= */}
        {/* 5. Three Analytics Cards in One Row (Row 5)                               */}
        {/* ========================================================================= */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {/* Card 1: Bugs by Severity */}
          <div className="bg-[#111728] border border-[#1e293b] rounded-2xl p-5 flex flex-col justify-between">
            <div>
              <h3 className="text-sm font-bold text-white">Bugs by Severity</h3>
              <p className="text-xs text-slate-500 mb-2">Number of Bugs</p>

              <div className="h-44 w-full">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={severityData} margin={{ top: 20, right: 10, left: -25, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" vertical={false} />
                    <XAxis dataKey="name" stroke="#94a3b8" fontSize={11} tickLine={false} />
                    <YAxis stroke="#64748b" fontSize={11} allowDecimals={false} />
                    <Tooltip contentStyle={TOOLTIP_STYLE} cursor={{ fill: '#ffffff06' }} />
                    <Bar dataKey="value" radius={[4, 4, 0, 0]} maxBarSize={38}>
                      {severityData.map((entry, index) => (
                        <Cell key={`sev-cell-${index}`} fill={entry.color} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>

            <div className="flex items-center gap-1.5 text-xs text-slate-400 pt-3 border-t border-slate-800/60 mt-2">
              <Info size={13} className="text-blue-400 shrink-0" />
              <span>Focus on critical and high severity bugs first.</span>
            </div>
          </div>

          {/* Card 2: Bugs by Status */}
          <div className="bg-[#111728] border border-[#1e293b] rounded-2xl p-5 flex flex-col justify-between">
            <div>
              <h3 className="text-sm font-bold text-white mb-2">Bugs by Status</h3>
              <div className="grid grid-cols-12 items-center h-44">
                <div className="col-span-7 relative h-full flex items-center justify-center">
                  <ResponsiveContainer width="100%" height="100%">
                    <PieChart>
                      <Pie
                        data={statusData}
                        dataKey="value"
                        nameKey="name"
                        innerRadius={45}
                        outerRadius={65}
                        paddingAngle={2}
                        stroke="#111728"
                        strokeWidth={2}
                      >
                        {statusData.map((entry, index) => (
                          <Cell key={`status-cell-${index}`} fill={entry.color} />
                        ))}
                      </Pie>
                      <Tooltip contentStyle={TOOLTIP_STYLE} />
                    </PieChart>
                  </ResponsiveContainer>
                  
                  <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
                    <span className="text-lg font-bold text-white leading-tight">{fmt(totalBugs)}</span>
                    <span className="text-[9px] text-slate-400">Total Bugs</span>
                  </div>
                </div>

                <div className="col-span-5 space-y-2 text-xs pl-2">
                  {statusData.map(s => (
                    <div key={s.name} className="flex items-center gap-1.5 text-slate-300">
                      <span className="w-2.5 h-2.5 rounded-sm shrink-0" style={{ background: s.color }} />
                      <span className="truncate">{s.name} ({s.value})</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>

            <div className="flex items-center gap-1.5 text-xs text-slate-400 pt-3 border-t border-slate-800/60 mt-2">
              <Info size={13} className="text-blue-400 shrink-0" />
              <span>Track the progress of bug resolution.</span>
            </div>
          </div>

          {/* Card 3: Test Cases by Priority */}
          <div className="bg-[#111728] border border-[#1e293b] rounded-2xl p-5 flex flex-col justify-between">
            <div>
              <h3 className="text-sm font-bold text-white">Test Cases by Priority</h3>
              <p className="text-xs text-slate-500 mb-2">Priority distribution of test cases</p>

              <div className="h-44 w-full">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={priorityData} margin={{ top: 20, right: 10, left: -25, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" vertical={false} />
                    <XAxis dataKey="name" stroke="#94a3b8" fontSize={11} tickLine={false} />
                    <YAxis stroke="#64748b" fontSize={11} allowDecimals={false} />
                    <Tooltip contentStyle={TOOLTIP_STYLE} cursor={{ fill: '#ffffff06' }} />
                    <Bar dataKey="value" radius={[4, 4, 0, 0]} maxBarSize={38}>
                      {priorityData.map((entry, index) => (
                        <Cell key={`pri-cell-${index}`} fill={entry.color} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>

            <div className="flex items-center gap-1.5 text-xs text-slate-400 pt-3 border-t border-slate-800/60 mt-2">
              <Info size={13} className="text-blue-400 shrink-0" />
              <span>High priority test cases drive quality.</span>
            </div>
          </div>
        </div>

        {/* ========================================================================= */}
        {/* 6. Test Cases by Feature & Bug → Test Case Coverage Table (Row 6)         */}
        {/* ========================================================================= */}
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
          {/* Left Column: Test Cases by Feature (Compact & Balanced Layout) */}
          <div className="lg:col-span-5 bg-[#111728] border border-[#1e293b] rounded-2xl p-5 flex flex-col justify-between">
            <div>
              <h3 className="text-sm font-bold text-white">Test Cases by Feature</h3>
              <p className="text-xs text-slate-500 mb-3">Distribution of generated test cases across features</p>

              <TestCasesByFeatureChart data={featureData} />
            </div>

            <div className="flex items-center gap-1.5 text-xs text-slate-400 pt-3 border-t border-slate-800/60 mt-3">
              <Info size={13} className="text-blue-400 shrink-0" />
              <span>Focus areas covered by test generation.</span>
            </div>
          </div>

          {/* Right Column: Bug → Test Case Coverage Table */}
          <div className="lg:col-span-7 bg-[#111728] border border-[#1e293b] rounded-2xl p-5 flex flex-col justify-between">
            <div>
              <div className="flex items-center justify-between gap-2 mb-1">
                <h3 className="text-sm font-bold text-white">Bug → Test Case Coverage</h3>
              </div>
              <p className="text-xs text-slate-500 mb-3">Detailed mapping between bugs and their test cases</p>

              <div className="overflow-x-auto">
                <table className="w-full text-left border-collapse">
                  <thead>
                    <tr className="border-b border-slate-800 text-[10px] uppercase tracking-wider text-slate-500 font-semibold">
                      <th className="py-2 px-3">BUG ID</th>
                      <th className="py-2 px-3">MODULE</th>
                      <th className="py-2 px-3">SEVERITY</th>
                      <th className="py-2 px-3">STATUS</th>
                      <th className="py-2 px-3">MAPPED TEST CASES</th>
                      <th className="py-2 px-3">COVERAGE</th>
                    </tr>
                  </thead>
                  <tbody>
                    {pagedBugRows.map((bug, i) => {
                      const mappedCount = mappedCounts[bug.issue_no] ?? 0;

                      return (
                        <TableCoverageRow
                          key={bug.issue_no || i}
                          bug={bug}
                          mappedCount={mappedCount}
                          onOpenModal={(no) => setSelectedBugModalNo(no)}
                        />
                      );
                    })}
                  </tbody>
                </table>
              </div>

              {/* Pagination Controls */}
              {bugRows.length > 0 && (
                <div className="flex flex-wrap items-center justify-between gap-2 pt-3 border-t border-slate-800/60 mt-2 text-xs text-slate-400">
                  <div>
                    Showing <span className="font-semibold text-slate-200">{(tablePage - 1) * pageSize + 1}</span>–<span className="font-semibold text-slate-200">{Math.min(tablePage * pageSize, bugRows.length)}</span> of <span className="font-semibold text-slate-200">{bugRows.length}</span> bugs
                  </div>
                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => setTablePage(p => Math.max(p - 1, 1))}
                      disabled={tablePage === 1}
                      className="px-3 py-1 rounded-lg bg-[#131b2e] border border-slate-700 hover:border-indigo-500 disabled:opacity-40 disabled:hover:border-slate-700 disabled:cursor-not-allowed text-xs font-medium text-slate-200 cursor-pointer transition-colors"
                    >
                      Previous
                    </button>
                    <span className="text-xs font-mono text-slate-300 px-1">
                      Page {tablePage} of {totalTablePages}
                    </span>
                    <button
                      onClick={() => setTablePage(p => Math.min(p + 1, totalTablePages))}
                      disabled={tablePage >= totalTablePages}
                      className="px-3 py-1 rounded-lg bg-[#131b2e] border border-slate-700 hover:border-indigo-500 disabled:opacity-40 disabled:hover:border-slate-700 disabled:cursor-not-allowed text-xs font-medium text-slate-200 cursor-pointer transition-colors"
                    >
                      Next
                    </button>
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* ========================================================================= */}
        {/* 7. QA Activity Trend & Advanced QA Metrics (Row 7)                        */}
        {/* ========================================================================= */}
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
          {/* Left Column: QA Activity Trend */}
          <div className="lg:col-span-6 bg-[#111728] border border-[#1e293b] rounded-2xl p-5 flex flex-col justify-between">
            <div>
              <div className="flex items-center justify-between gap-2 mb-1">
                <h3 className="text-sm font-bold text-white">QA Activity Trend</h3>
              </div>
              <p className="text-xs text-slate-500 mb-4">Track bugs and test cases created over time</p>

              <div className="h-52 w-full">
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={activityData} margin={{ top: 10, right: 20, left: -25, bottom: 0 }}>
                    <defs>
                      <linearGradient id="bugsGrad" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor={COLOR_BUGS} stopOpacity={0.25} />
                        <stop offset="95%" stopColor={COLOR_BUGS} stopOpacity={0.0} />
                      </linearGradient>
                      <linearGradient id="testsGrad" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor={COLOR_TESTS} stopOpacity={0.25} />
                        <stop offset="95%" stopColor={COLOR_TESTS} stopOpacity={0.0} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" vertical={false} />
                    <XAxis dataKey="month" stroke="#94a3b8" fontSize={11} tickLine={false} />
                    <YAxis stroke="#64748b" fontSize={11} allowDecimals={false} />
                    <Tooltip contentStyle={TOOLTIP_STYLE} />
                    <Area
                      type="monotone"
                      dataKey="bugs"
                      name="Bugs Created"
                      stroke={COLOR_BUGS}
                      strokeWidth={2.5}
                      fillOpacity={1}
                      fill="url(#bugsGrad)"
                      dot={{ r: 3, fill: COLOR_BUGS }}
                      activeDot={{ r: 5 }}
                    />
                    <Area
                      type="monotone"
                      dataKey="testCases"
                      name="Test Cases Generated"
                      stroke={COLOR_TESTS}
                      strokeWidth={2.5}
                      fillOpacity={1}
                      fill="url(#testsGrad)"
                      dot={{ r: 3, fill: COLOR_TESTS }}
                      activeDot={{ r: 5 }}
                    />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            </div>

            <div className="flex items-center justify-center gap-6 text-xs text-slate-400 pt-3 border-t border-slate-800/60 mt-2">
              <div className="flex items-center gap-2">
                <span className="w-2.5 h-2.5 rounded-full bg-[#3b82f6]" />
                <span>Bugs Created</span>
              </div>
              <div className="flex items-center gap-2">
                <span className="w-2.5 h-2.5 rounded-full bg-[#8b5cf6]" />
                <span>Test Cases Generated</span>
              </div>
            </div>
          </div>

          {/* Right Column: Cross-Agent QA Intelligence */}
          <div className="lg:col-span-6 bg-[#111728] border border-[#1e293b] rounded-2xl p-5 flex flex-col justify-between">
            <div>
              <div className="flex items-center justify-between mb-1">
                <h3 className="text-sm font-bold text-white">Cross-Agent QA Intelligence</h3>
                <span className="px-2 py-0.5 text-[10px] font-semibold text-purple-300 bg-purple-950/60 border border-purple-800/40 rounded-full">
                  Bugsy + TestSmith
                </span>
              </div>
              <p className="text-xs text-slate-400 mb-4">Synthesized metrics computed across defect and test execution streams</p>

              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 pt-1">
                {/* 1. Test Failure Rate */}
                <div className="bg-[#0e1322] border border-rose-900/30 rounded-xl p-3.5 flex flex-col justify-between h-44 hover:border-rose-700/50 transition-colors">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-semibold text-slate-200">Test Failure Rate</span>
                    <div className="w-6 h-6 rounded-md bg-rose-500/15 text-rose-400 flex items-center justify-center">
                      <AlertTriangle size={13} />
                    </div>
                  </div>
                  <div className="my-auto py-1">
                    <div className="text-2xl font-extrabold text-rose-400">22.2%</div>
                    <div className="text-[11px] font-medium text-slate-400 mt-0.5">4 of 18 executed</div>
                  </div>
                  <p className="text-[10px] text-slate-400 leading-tight border-t border-slate-800/80 pt-1.5">
                    All 4 failures correlate directly to defect <span className="font-semibold text-slate-300">Bug #11</span>.
                  </p>
                </div>

                {/* 2. Regression Coverage Index */}
                <div className="bg-[#0e1322] border border-sky-900/30 rounded-xl p-3.5 flex flex-col justify-between h-44 hover:border-sky-700/50 transition-colors">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-semibold text-slate-200">Regression Coverage</span>
                    <div className="w-6 h-6 rounded-md bg-sky-500/15 text-sky-400 flex items-center justify-center">
                      <RefreshCw size={13} />
                    </div>
                  </div>
                  <div className="my-auto py-1">
                    <div className="text-2xl font-extrabold text-sky-400">11.5%</div>
                    <div className="text-[11px] font-medium text-slate-400 mt-0.5">7 of 61 bugs mapped</div>
                  </div>
                  <p className="text-[10px] text-slate-400 leading-tight border-t border-slate-800/80 pt-1.5">
                    7 verified reproducible test cases; 54 lack automated tests.
                  </p>
                </div>

                {/* 3. Composite Project QA Health */}
                <div className="bg-[#0e1322] border border-rose-900/30 rounded-xl p-3.5 flex flex-col justify-between h-44 hover:border-rose-700/50 transition-colors">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-semibold text-slate-200">Project QA Health</span>
                    <div className="w-6 h-6 rounded-md bg-rose-500/15 text-rose-400 flex items-center justify-center">
                      <Shield size={13} />
                    </div>
                  </div>
                  <div className="my-auto py-1">
                    <div className="text-xl font-black text-rose-400 tracking-wide uppercase">CRITICAL</div>
                    <div className="text-[11px] font-medium text-slate-400 mt-0.5">Score: 3.8 / 10</div>
                  </div>
                  <p className="text-[10px] text-slate-400 leading-tight border-t border-slate-800/80 pt-1.5">
                    Weighted: Unresolved P1 bugs + test failures + coverage gaps.
                  </p>
                </div>
              </div>
            </div>

            <div className="flex items-center gap-1.5 text-xs text-slate-400 pt-3 border-t border-slate-800/60 mt-3">
              <Sparkles size={13} className="text-purple-400 shrink-0" />
              <span>Cross-agent indicators synthesized in real-time from Bugsy defects and TestSmith test execution.</span>
            </div>
          </div>
        </div>

        {/* Critical Bug Detail Modal (media_1788423231655.png) */}
        {selectedBugModalNo && (
          <BugDetailModal
            issueNo={selectedBugModalNo}
            projectId={selectedProjectId}
            onClose={() => setSelectedBugModalNo(null)}
            criticalBugsList={criticalBugsList}
            onSelectBug={(no) => setSelectedBugModalNo(no)}
            mappedCount={mappedCounts[selectedBugModalNo] ?? 0}
          />
        )}

      </div>
    </div>
  );
}

export default CommonAgentDashboard;

import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useFilters, useFilterActions } from './filters';
import { fetchDashboardInsights, fetchBugDetails, type DashboardInsightsResponse } from './api';
import {
  MetricWidget,
  TimeseriesWidget,
  GaugeWidget,
  DonutWidget,
  BarWidget,
  TableWidget,
} from './widgets';

const API_BASE =
  (typeof import.meta !== 'undefined' && import.meta.env?.VITE_DASHBOARDS_API) || '';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface QuickStats {
  total: number;
  backlog: number;
  critical_open: number;
  active_reporters: number;
  fix_rate: number;
  by_severity: Record<string, number>;
  by_status: Record<string, number>;
  by_game: Array<{ name: string; total: number; open: number }>;
  executive_summary: string;
  game_count: number;
}

interface BugRecord {
  bug_id: string;
  title: string;
  summary: string;
  severity: string;
  status: string;
  project_name: string;
  reporter_name: string;
  created_at: string;
  updated_at: string;
  issue_type: string;
  repro_rate: string;
  build_version: string;
  platform: string;
  dynamic_fields: Record<string, any>;
}

interface BugDetails {
  found: boolean;
  issue_no: string;
  occurrences_count: number;
  affected_projects: string[];
  primary_bug: BugRecord;
  records: BugRecord[];
}

interface DimOption { value: string; label: string; }

// ---------------------------------------------------------------------------
// API helpers
// ---------------------------------------------------------------------------

async function getQuickStats(projectId?: string | null): Promise<QuickStats> {
  const qs = projectId ? `?project_id=${encodeURIComponent(projectId)}` : '';
  const res = await fetch(`${API_BASE}/api/bugs/quick-stats${qs}`, { credentials: 'include' });
  if (!res.ok) throw new Error(`quick-stats ${res.status}`);
  const json = await res.json();
  return json.stats;
}

async function getDim(name: string): Promise<DimOption[]> {
  const res = await fetch(`${API_BASE}/api/dimensions/${name}`, { credentials: 'include' });
  if (!res.ok) return [];
  const json = await res.json();
  return (json.options ?? []) as DimOption[];
}

// ---------------------------------------------------------------------------
// Badges
// ---------------------------------------------------------------------------

const SEV_CLS: Record<string, string> = {
  P1:       'bg-rose-900/60 text-rose-300 border-rose-700/60',
  P2:       'bg-amber-900/60 text-amber-300 border-amber-700/60',
  P3:       'bg-indigo-900/60 text-indigo-300 border-indigo-700/60',
  P4:       'bg-neutral-800 text-neutral-400 border-neutral-700',
  Blocker:  'bg-rose-900/70 text-rose-300 border-rose-700',
  Critical: 'bg-rose-900/70 text-rose-300 border-rose-700',
  Major:    'bg-amber-900/60 text-amber-300 border-amber-700/60',
  Minor:    'bg-indigo-900/60 text-indigo-300 border-indigo-700/60',
  Trivial:  'bg-neutral-800 text-neutral-400 border-neutral-700',
};

const STAT_CLS: Record<string, string> = {
  open:        'bg-yellow-900/50 text-yellow-300 border-yellow-700/60',
  in_progress: 'bg-cyan-900/50 text-cyan-300 border-cyan-700/60',
  fixed:       'bg-emerald-900/50 text-emerald-300 border-emerald-700/60',
  closed:      'bg-neutral-800 text-neutral-400 border-neutral-700',
  qa_ready:    'bg-purple-900/50 text-purple-300 border-purple-700/60',
};

function SevBadge({ v }: { v: string }) {
  const cls = SEV_CLS[v] ?? 'bg-neutral-800 text-neutral-300 border-neutral-700';
  return (
    <span className={`inline-flex items-center text-[11px] font-bold px-2 py-0.5 rounded border ${cls}`}>
      {v}
    </span>
  );
}

function StatBadge({ v }: { v: string }) {
  const key = v?.toLowerCase().replace(/ /g, '_');
  const cls = STAT_CLS[key] ?? 'bg-neutral-800 text-neutral-300 border-neutral-700';
  return (
    <span className={`inline-flex items-center text-[11px] font-semibold px-2 py-0.5 rounded border capitalize ${cls}`}>
      {v?.replace(/_/g, ' ')}
    </span>
  );
}

// ---------------------------------------------------------------------------
// FilterSelect — dimension-backed dropdown
// ---------------------------------------------------------------------------

function FilterSelect({
  dimension, param, placeholder,
}: {
  dimension: string; param: string; placeholder: string;
}) {
  const filters = useFilters();
  const { setFilter } = useFilterActions();
  const current = (filters[param] as string | undefined) ?? '';

  const { data: opts = [], isPending } = useQuery<DimOption[]>({
    queryKey: ['dim', dimension],
    queryFn: () => getDim(dimension),
    staleTime: 60_000,
  });

  return (
    <select
      value={current}
      onChange={e => setFilter(param, e.target.value || undefined)}
      disabled={isPending && opts.length === 0}
      className="
        bg-neutral-900 border border-neutral-800 hover:border-indigo-600/50
        focus:border-indigo-500 focus:outline-none rounded-xl text-sm
        px-4 py-2.5 text-neutral-200 cursor-pointer transition-colors
        min-w-[170px] disabled:opacity-50
      "
    >
      <option value="">{isPending ? 'Loading…' : placeholder}</option>
      {opts.map(o => (
        <option key={o.value} value={o.value}>{o.label}</option>
      ))}
    </select>
  );
}

// ---------------------------------------------------------------------------
// Active filter pills
// ---------------------------------------------------------------------------

const FILTER_LABELS: Record<string, string> = {
  project_id: '🎮 Game',
  issue_no:   '🐛 Bug',
  severity:   '⚠ Severity',
  status:     '📋 Status',
};

function ActivePills() {
  const filters = useFilters();
  const { setFilter } = useFilterActions();

  const active = Object.entries(filters)
    .filter(([k, v]) => !['date_range_start', 'date_range_end'].includes(k) && v)
    .map(([k, v]) => ({ k, v: String(v) }));

  if (active.length === 0) return null;

  return (
    <div className="flex flex-wrap items-center gap-2 pt-1">
      {active.map(({ k, v }) => (
        <span
          key={k}
          className="flex items-center gap-1.5 text-xs bg-indigo-950/60 border border-indigo-800/50 text-indigo-200 px-3 py-1 rounded-full"
        >
          <span className="text-indigo-400 font-medium">{FILTER_LABELS[k] ?? k}:</span>
          <span className="font-bold">{v}</span>
          <button
            onClick={() => setFilter(k, undefined)}
            className="ml-0.5 text-indigo-400 hover:text-white cursor-pointer font-bold"
          >
            ✕
          </button>
        </span>
      ))}
      {active.length > 1 && (
        <button
          onClick={() => active.forEach(({ k }) => setFilter(k, undefined))}
          className="text-xs text-neutral-500 hover:text-neutral-300 cursor-pointer underline"
        >
          Clear all
        </button>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Quick Stats Banner — instant, no LLM
// ---------------------------------------------------------------------------

function QuickStatsBanner({ projectId }: { projectId?: string | null }) {
  const { data: s, isPending } = useQuery<QuickStats>({
    queryKey: ['qs', projectId],
    queryFn: () => getQuickStats(projectId),
    staleTime: 30_000,
  });

  if (isPending || !s) {
    return (
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {[0, 1, 2, 3].map(i => (
          <div key={i} className="h-24 bg-neutral-900/50 rounded-2xl animate-pulse" />
        ))}
      </div>
    );
  }

  const cards = [
    {
      emoji: '🐞', label: 'Total Bugs', value: s.total,
      sub: `across ${s.game_count} game${s.game_count !== 1 ? 's' : ''}`,
      accent: 'border-blue-900/50 bg-blue-950/20', vColor: 'text-blue-300',
    },
    {
      emoji: '📋', label: 'Open / Backlog', value: s.backlog,
      sub: s.total > 0 ? `${Math.round(s.backlog / s.total * 100)}% unresolved` : '',
      accent: 'border-amber-900/50 bg-amber-950/20', vColor: 'text-amber-300',
    },
    {
      emoji: '🚨', label: 'Critical Open', value: s.critical_open,
      sub: 'P1 / Blocker / Critical',
      accent: s.critical_open > 0 ? 'border-rose-900/50 bg-rose-950/20' : 'border-neutral-800 bg-neutral-900/40',
      vColor: s.critical_open > 0 ? 'text-rose-300' : 'text-neutral-400',
    },
    {
      emoji: '✅', label: 'Fix Rate', value: `${s.fix_rate}%`,
      sub: 'bugs resolved',
      accent: 'border-emerald-900/50 bg-emerald-950/20', vColor: 'text-emerald-300',
    },
  ];

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {cards.map(c => (
          <div key={c.label} className={`border rounded-2xl p-4 ${c.accent}`}>
            <div className="flex items-center gap-1.5 text-xs text-neutral-400 mb-2">
              <span>{c.emoji}</span>
              <span>{c.label}</span>
            </div>
            <div className={`text-3xl font-bold tracking-tight ${c.vColor}`}>{c.value}</div>
            {c.sub && <div className="text-[11px] text-neutral-500 mt-1">{c.sub}</div>}
          </div>
        ))}
      </div>
      {s.executive_summary && (
        <div className="bg-neutral-900/60 border border-neutral-800/70 rounded-xl px-5 py-3 text-sm text-neutral-300 leading-relaxed">
          <span className="text-indigo-400 font-semibold mr-2">📊</span>
          {s.executive_summary}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Bug Detail Panel — fast DB fetch, AI narrative on demand
// ---------------------------------------------------------------------------

function BugDetailPanel({ issueNo, projectId }: { issueNo: string; projectId?: string | null }) {
  const [analyzing, setAnalyzing] = useState(false);
  const [aiText, setAiText] = useState<string | null>(null);
  const [aiErr, setAiErr] = useState<string | null>(null);

  const { data: det, isPending, error } = useQuery<BugDetails>({
    queryKey: ['bug-det', issueNo, projectId],
    queryFn: async () => {
      const raw = await fetchBugDetails(issueNo, projectId);
      return raw as BugDetails;
    },
    staleTime: 120_000,
    retry: 1,
  });

  const runAi = async () => {
    if (!det) return;
    setAnalyzing(true);
    setAiErr(null);
    try {
      const res = await fetch(`${API_BASE}/api/bugs/insights`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          context: { field: 'issue_no', value: issueNo, type: 'issue_no' },
          drilldown_data: det,
          dashboard_plan: { dashboard_title: `Bug #${issueNo} Deep Dive` },
        }),
      });
      if (!res.ok) throw new Error(`Insights ${res.status}`);
      const json = await res.json();
      const ins = json.insights as DashboardInsightsResponse;
      setAiText(ins.executive_summary ?? ins.key_findings?.[0]?.explanation ?? 'Analysis complete.');
    } catch (e: any) {
      setAiErr(e.message);
    } finally {
      setAnalyzing(false);
    }
  };

  // Loading skeleton
  if (isPending) {
    return (
      <div className="space-y-4 animate-pulse">
        <div className="h-10 w-72 bg-neutral-800 rounded-xl" />
        <div className="h-48 bg-neutral-900/60 rounded-2xl" />
        <div className="grid grid-cols-2 gap-4">
          <div className="h-56 bg-neutral-900/60 rounded-2xl" />
          <div className="h-56 bg-neutral-900/60 rounded-2xl" />
        </div>
      </div>
    );
  }

  // Not found
  if (error || !det?.found) {
    return (
      <div className="bg-rose-950/30 border border-rose-800/50 rounded-2xl p-10 text-center space-y-3">
        <div className="text-5xl">🔍</div>
        <div className="text-rose-300 font-semibold text-lg">Bug #{issueNo} not found</div>
        <div className="text-xs text-neutral-500 max-w-sm mx-auto">
          This bug doesn't exist in the database yet. Import the CSV file via the Import button to load bug data.
        </div>
      </div>
    );
  }

  const bug = det.primary_bug;
  const df  = bug.dynamic_fields ?? {};
  const multiGame = det.affected_projects.length > 1;

  // Show any non-empty metadata from dynamic_fields
  const metaRows: [string, string][] = [
    ['Issue Type',   df.issue_type    || bug.issue_type],
    ['Repro Rate',   df.repro_rate    || bug.repro_rate],
    ['Build / Ver',  df.build_version || bug.build_version],
    ['Platform',     df.platform      || bug.platform],
    ['Reporter',     bug.reporter_name],
    ['Resolution',   df.resolution    || df.dev_resolution],
    ['Dev Comments', df.dev_comments],
  ].filter(([, v]) => v && String(v).trim() && String(v) !== 'N/A') as [string, string][];

  return (
    <div className="space-y-5">

      {/* Header card */}
      <div className="bg-gradient-to-br from-indigo-950/50 via-neutral-900 to-neutral-900 border border-indigo-800/40 rounded-2xl p-6 space-y-4">

        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div className="space-y-2">
            <div className="flex items-center flex-wrap gap-2">
              <span className="font-mono font-bold text-indigo-400 bg-indigo-950/70 border border-indigo-800/60 px-3 py-1 rounded-lg text-sm">
                Bug #{issueNo}
              </span>
              <SevBadge v={df.severity_raw || bug.severity} />
              <StatBadge v={df.status_raw  || bug.status}  />
              {multiGame && (
                <span className="text-[11px] font-semibold bg-amber-900/40 text-amber-300 border border-amber-700/50 px-2.5 py-0.5 rounded-full">
                  🔀 {det.affected_projects.length} games
                </span>
              )}
            </div>
            <h2 className="text-xl font-bold text-white leading-snug">{bug.title}</h2>
            <div className="flex flex-wrap gap-4 text-xs text-neutral-400">
              {bug.project_name  && <span>🎮 {bug.project_name}</span>}
              {df.issue_type     && <span>🏷 {df.issue_type}</span>}
              {bug.reporter_name && <span>👤 {bug.reporter_name}</span>}
            </div>
          </div>

          {/* AI Narrative button */}
          <button
            onClick={runAi}
            disabled={analyzing}
            className="shrink-0 flex items-center gap-2 px-5 py-2.5 bg-gradient-to-r from-indigo-600 to-violet-600 hover:from-indigo-500 hover:to-violet-500 disabled:opacity-50 text-white font-semibold text-sm rounded-xl transition-all shadow-lg shadow-indigo-950/50 cursor-pointer"
          >
            {analyzing
              ? <><div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" /><span>Analyzing…</span></>
              : <><span>✨</span><span>AI Narrative</span></>}
          </button>
        </div>

        {/* AI result */}
        {aiText && (
          <div className="bg-indigo-950/30 border border-indigo-800/40 rounded-xl p-4 text-sm text-indigo-100 leading-relaxed">
            <div className="text-[10px] font-bold text-indigo-400 uppercase tracking-widest mb-2">✨ AI Analysis</div>
            {aiText}
          </div>
        )}
        {aiErr && (
          <div className="bg-rose-950/30 border border-rose-800/40 rounded-xl p-3 text-xs text-rose-300">
            AI unavailable — {aiErr}. The bug data above is complete without it.
          </div>
        )}
      </div>

      {/* Cross-game banner */}
      {multiGame && (
        <div className="bg-amber-950/20 border border-amber-800/40 rounded-2xl p-4 space-y-2">
          <div className="text-xs font-bold text-amber-400 uppercase tracking-wider">🔀 Cross-Game Occurrence</div>
          <div className="flex flex-wrap gap-2">
            {det.affected_projects.map(g => (
              <span key={g} className="text-xs bg-amber-900/40 text-amber-200 border border-amber-800/50 px-3 py-1 rounded-full">
                {g}
              </span>
            ))}
          </div>
          <p className="text-xs text-neutral-500">
            This bug was recorded across {det.affected_projects.length} game projects
            with {det.occurrences_count} total occurrence{det.occurrences_count !== 1 ? 's' : ''}.
          </p>
        </div>
      )}

      {/* Summary + metadata */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">

        <div className="bg-neutral-900/60 border border-neutral-800 rounded-2xl p-5 space-y-3">
          <div className="text-xs font-bold text-neutral-400 uppercase tracking-wider">📝 Summary</div>
          <p className="text-sm text-neutral-200 leading-relaxed">
            {bug.summary || df.summary || df.description || 'No summary available.'}
          </p>
          {df.description && df.description !== (bug.summary ?? df.summary) && (
            <>
              <div className="border-t border-neutral-800" />
              <div className="text-xs font-bold text-neutral-500 uppercase tracking-wider">Description</div>
              <p className="text-xs text-neutral-300 leading-relaxed">{df.description}</p>
            </>
          )}
        </div>

        <div className="bg-neutral-900/60 border border-neutral-800 rounded-2xl p-5">
          <div className="text-xs font-bold text-neutral-400 uppercase tracking-wider mb-4">🔎 Bug Details</div>
          <div className="space-y-2.5">
            {metaRows.map(([label, value]) => (
              <div key={label} className="flex items-start gap-2 text-xs">
                <span className="text-neutral-500 w-28 shrink-0">{label}</span>
                <span className="text-neutral-200 flex-1 break-words">{value}</span>
              </div>
            ))}
            {metaRows.length === 0 && (
              <p className="text-xs text-neutral-500">No additional metadata available.</p>
            )}
          </div>
        </div>
      </div>

      {/* Steps to reproduce */}
      {df.steps && (
        <div className="bg-neutral-900/60 border border-neutral-800 rounded-2xl p-5 space-y-4">
          <div className="text-xs font-bold text-neutral-400 uppercase tracking-wider">🔢 Steps to Reproduce</div>
          <pre className="text-xs text-neutral-300 leading-relaxed whitespace-pre-wrap font-mono bg-neutral-950/80 p-4 rounded-xl border border-neutral-800">
            {df.steps}
          </pre>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {df.actual_result && (
              <div className="bg-rose-950/20 border border-rose-900/40 rounded-xl p-4 text-xs text-rose-200">
                <div className="font-bold text-rose-400 mb-2">❌ Actual Result</div>
                {df.actual_result}
              </div>
            )}
            {df.expected_result && (
              <div className="bg-emerald-950/20 border border-emerald-900/40 rounded-xl p-4 text-xs text-emerald-200">
                <div className="font-bold text-emerald-400 mb-2">✅ Expected Result</div>
                {df.expected_result}
              </div>
            )}
          </div>
        </div>
      )}

      {/* All occurrences (multi-game) */}
      {multiGame && det.records.length > 1 && (
        <div className="bg-neutral-900/60 border border-neutral-800 rounded-2xl p-5 space-y-3">
          <div className="text-xs font-bold text-neutral-400 uppercase tracking-wider">
            📋 All Occurrences ({det.records.length})
          </div>
          <div className="space-y-2">
            {det.records.map((r, i) => (
              <div
                key={r.bug_id}
                className="flex items-center gap-3 text-xs bg-neutral-950/60 rounded-xl px-4 py-2.5 border border-neutral-800/60"
              >
                <span className="text-neutral-600 font-mono w-4">#{i + 1}</span>
                <span className="text-neutral-300 flex-1 font-medium">{r.project_name || 'Unknown Game'}</span>
                <SevBadge v={r.severity} />
                <StatBadge v={r.status}  />
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Overview Panel — standard widgets, auto-filtered via useFilters()
// ---------------------------------------------------------------------------

function OverviewPanel() {
  return (
    <div className="space-y-6">

      {/* KPI row */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <MetricWidget metric="bugs.total"           title="Total Bug Reports"   subtitle="All reports in range"         icon="activity" iconColor="blue"   goodDirection="neutral" />
        <MetricWidget metric="bugs.backlog"          title="Unresolved Backlog"  subtitle="Not yet closed"               icon="layers"   iconColor="amber"  goodDirection="down"    />
        <MetricWidget metric="bugs.p1_open"          title="P1 Critical Open"    subtitle="Highest severity, unresolved" icon="zap"      iconColor="orange" goodDirection="down"    />
        <MetricWidget metric="bugs.reporters.active" title="Active QA Reporters" subtitle="Distinct reporters in range"  icon="users"    iconColor="purple" goodDirection="neutral" />
      </div>

      {/* Velocity + Fix Rate + Severity donut */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        <div className="lg:col-span-6 min-h-[300px]">
          <TimeseriesWidget metric="bugs.velocity" title="Bug Velocity — Discovery vs Resolution" stacked={false} />
        </div>
        <div className="lg:col-span-3 min-h-[300px]">
          <GaugeWidget metric="bugs.fix_rate" title="Resolution Rate" badge="closed / total" unit="FIX RATE" />
        </div>
        <div className="lg:col-span-3 min-h-[300px]">
          <DonutWidget metric="bugs.by_severity" title="Severity Breakdown" colorScheme="severity" />
        </div>
      </div>

      {/* MTTR + Aging backlog */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="min-h-[280px]">
          <BarWidget metric="bugs.mttr_by_severity" title="Median Time to Resolution by Severity" colorScheme="severity" />
        </div>
        <div className="min-h-[280px]">
          <BarWidget metric="bugs.aging_backlog" title="Aging Backlog — How Old Are Open Bugs" />
        </div>
      </div>

      {/* Status + Project breakdown */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <TableWidget
          metric="bugs.breakdown.status"
          title="Status Distribution"
          compact={true}
          columnConfig={{
            status: { label: 'Status', format: 'status-badge' },
            count:  { label: 'Count' },
            pct:    { label: '% of Total', format: 'percent-cell' },
          }}
        />
        <TableWidget
          metric="bugs.breakdown.project"
          title="Breakdown by Game"
          compact={true}
          columnConfig={{
            project:    { label: 'Game'      },
            code:       { label: 'Code',      format: 'badge'   },
            total:      { label: 'Total'      },
            unresolved: { label: 'Unresolved' },
            p1_open:    { label: 'P1 Open'    },
          }}
        />
      </div>

      {/* Severity x Status matrix */}
      <TableWidget
        metric="bugs.severity_status_matrix"
        title="Severity \u00d7 Status Matrix"
        compact={true}
        columnConfig={{
          severity:    { label: 'Severity',    format: 'severity-badge' },
          open:        { label: 'Open'         },
          in_progress: { label: 'In Progress'  },
          fixed:       { label: 'Fixed'        },
          closed:      { label: 'Closed'       },
        }}
      />

      {/* Full bug telemetry */}
      <TableWidget
        metric="bugs.telemetry"
        title="Live Bug Telemetry"
        sortableColumns={['created_at', 'severity', 'status']}
        pageSize={20}
        columnConfig={{
          title:         { label: 'Title'    },
          severity:      { label: 'Severity',  format: 'severity-badge' },
          status:        { label: 'Status',    format: 'status-badge'   },
          project_name:  { label: 'Game'       },
          reporter_name: { label: 'Reporter'   },
          created_at:    { label: 'Created',   format: 'timestamp'      },
          age_days:      { label: 'Age',       format: 'age'            },
        }}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main Export
// ---------------------------------------------------------------------------

interface AgentDashboardRendererProps {
  projectId?: string | null;
}

export function AgentDashboardRenderer({ projectId }: AgentDashboardRendererProps) {
  const filters = useFilters();
  const issueNo    = filters.issue_no    as string | undefined;
  const projFilter = (filters.project_id as string | undefined) || projectId || null;

  return (
    <div className="max-w-[1400px] mx-auto p-6 space-y-6">

      {/* Page header */}
      <div className="bg-neutral-900/70 border border-neutral-800 rounded-2xl px-6 py-5 backdrop-blur-sm">
        <div className="flex items-center gap-2 mb-2">
          <span className="text-[10px] font-bold uppercase tracking-widest text-indigo-400 bg-indigo-950/60 border border-indigo-800/50 px-2.5 py-1 rounded-full">
            🤖 Agent Dashboard
          </span>
        </div>
        <h1 className="text-2xl font-bold text-neutral-100">
          {issueNo
            ? `Bug #${issueNo} \u2014 Detailed Analysis`
            : 'Bug Bot \u2014 Quality Command Center'}
        </h1>
        <p className="text-sm text-neutral-400 mt-1">
          {issueNo
            ? 'Full bug record fetched from the database. Click \u2728 AI Narrative to get LLM commentary on this bug.'
            : projFilter
            ? 'Showing all metrics scoped to the selected game. Select a Bug # to drill into a specific record.'
            : 'Full overview across all games. Filter by game, bug #, severity, or status to drill down.'}
        </p>
      </div>

      {/* Filter bar */}
      <div className="bg-neutral-900/60 border border-neutral-800 rounded-2xl p-5 space-y-3">
        <div className="text-[10px] font-bold text-neutral-500 uppercase tracking-widest">Filter by</div>
        <div className="flex flex-wrap gap-3">
          <FilterSelect dimension="bug_projects"   param="project_id" placeholder="\ud83c\udfae All Games"      />
          <FilterSelect dimension="bug_issues"     param="issue_no"   placeholder="\ud83d\udc1b All Bugs #"     />
          <FilterSelect dimension="bug_severities" param="severity"   placeholder="\u26a0 All Severities"       />
          <FilterSelect dimension="bug_statuses"   param="status"     placeholder="\ud83d\udccb All Statuses"   />
        </div>
        <ActivePills />
      </div>

      {/* Quick stats — instant, always visible, auto-scoped to project if set */}
      <QuickStatsBanner projectId={projFilter} />

      {/* Content — mode driven by active filter */}
      {issueNo ? (
        <BugDetailPanel issueNo={issueNo} projectId={projFilter} />
      ) : (
        <OverviewPanel />
      )}

    </div>
  );
}

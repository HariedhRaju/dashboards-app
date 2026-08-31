import React, { useState, useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useFilters, useFilterActions } from './filters';
import {
  fetchDashboardInsights,
  fetchBugDetails,
  fetchDashboardAnalysis,
  fetchDynamicMetric,
  type DashboardInsightsResponse,
  type DashboardAnalysis,
  type VisualizationPlan,
} from './api';
import {
  MetricWidget,
  TimeseriesWidget,
  GaugeWidget,
  DonutWidget,
  BarWidget,
  TableWidget,
} from './widgets';
import {
  PieChart, Pie, Cell, Tooltip, ResponsiveContainer
} from 'recharts';
import {
  Sparkles, Brain, CheckCircle2, AlertTriangle, RefreshCw, ChevronRight, Activity, Zap, Layers, ShieldAlert,
  HelpCircle, Play, RotateCcw, AlertOctagon
} from 'lucide-react';

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
  const { data: det, isPending, error } = useQuery<BugDetails>({
    queryKey: ['bug-det', issueNo, projectId],
    queryFn: async () => {
      const raw = await fetchBugDetails(issueNo, projectId);
      return raw as BugDetails;
    },
    staleTime: 120_000,
    retry: 1,
  });

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
        </div>
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
          issue_no:      { label: 'Bug #',     format: 'badge'          },
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
// Dynamic AI-Generated Visualizations
// ---------------------------------------------------------------------------

function evaluateKPI(data: Array<{ label: string; value: number }>, calculation: string) {
  const cleanCalc = (calculation || '').toLowerCase();
  if (cleanCalc.includes("count of") || cleanCalc.includes("=")) {
    const match = cleanCalc.match(/['"]([^'"]+)['"]/);
    if (match) {
      const targetVal = match[1];
      const found = data.find(d => (d.label || '').toLowerCase() === targetVal);
      return found ? found.value : 0;
    }
  }
  return data.reduce((sum, d) => sum + d.value, 0);
}

function DynamicChart({
  viz,
  filters,
  projFilter,
}: {
  viz: VisualizationPlan;
  filters: any;
  projFilter: string | null;
}) {
  const fieldName = viz.group_by?.[0] || viz.fields?.[0] || '';
  const { data: res, isPending, error } = useQuery({
    queryKey: ['dynamic-metric', fieldName, projFilter, filters, viz.aggregation],
    queryFn: () =>
      fetchDynamicMetric({
        field_name: fieldName,
        project_id: projFilter,
        metric: viz.aggregation,
        filters: filters,
      }),
    enabled: !!fieldName,
  });

  if (isPending) {
    return (
      <div className="h-44 flex items-center justify-center">
        <div className="w-5 h-5 border-2 border-indigo-600/30 border-t-indigo-500 rounded-full animate-spin" />
      </div>
    );
  }

  if (error || !res || !res.data) {
    return (
      <div className="h-44 flex items-center justify-center text-xs text-neutral-500">
        No metric data available for {fieldName}
      </div>
    );
  }

  const chartData = res.data;

  if (viz.type === 'donut' || viz.type === 'pie') {
    const COLORS = ['#818CF8', '#34D399', '#FBBF24', '#F472B6', '#22D3EE', '#F87171'];
    return (
      <div className="flex flex-col justify-between h-44">
        <div className="flex-1 flex items-center justify-center min-h-[110px]">
          <ResponsiveContainer width="100%" height={110}>
            <PieChart>
              <Pie
                data={chartData}
                dataKey="value"
                nameKey="label"
                innerRadius={25}
                outerRadius={45}
                paddingAngle={1}
                stroke="none"
              >
                {chartData.map((entry, index) => (
                  <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                ))}
              </Pie>
              <Tooltip
                contentStyle={{
                  fontSize: 11,
                  background: '#171717',
                  border: '1px solid #404040',
                  borderRadius: 6,
                  color: '#e5e5e5',
                }}
              />
            </PieChart>
          </ResponsiveContainer>
        </div>
        <div className="text-[10px] grid grid-cols-2 gap-1 overflow-y-auto max-h-[50px] border-t border-neutral-800/40 pt-1">
          {chartData.map((d, i) => (
            <div key={d.label || i} className="flex items-center gap-1 truncate text-neutral-400">
              <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ background: COLORS[i % COLORS.length] }} />
              <span className="truncate">{d.label || 'N/A'}:</span>
              <span className="font-semibold text-neutral-200 tabular-nums">{d.value}</span>
            </div>
          ))}
        </div>
      </div>
    );
  }

  if (viz.type === 'kpi') {
    const kpiValue = evaluateKPI(chartData, viz.aggregation);
    return (
      <div className="h-44 flex flex-col justify-between p-2">
        <div>
          <div className="text-[10px] font-semibold text-neutral-500 uppercase tracking-wider">Calculation</div>
          <div className="text-xs text-neutral-300 font-mono mt-0.5 truncate">{viz.aggregation || 'count'}</div>
        </div>
        <div>
          <div className="text-4xl font-extrabold text-indigo-400 tracking-tight tabular-nums">{kpiValue.toLocaleString()}</div>
          <div className="text-[10px] text-neutral-500 mt-1 italic line-clamp-2">{viz.reason}</div>
        </div>
      </div>
    );
  }

  if (viz.type === 'table') {
    return (
      <div className="h-44 overflow-y-auto pr-1">
        <table className="w-full text-[11px] text-left border-collapse">
          <thead>
            <tr className="text-[9px] uppercase tracking-wider text-neutral-500 font-bold border-b border-neutral-855">
              <th className="py-1 px-2">Dimension</th>
              <th className="py-1 px-2 text-right">Count</th>
            </tr>
          </thead>
          <tbody>
            {chartData.map((d, i) => (
              <tr key={d.label || i} className="border-b border-neutral-900/40 last:border-b-0 hover:bg-neutral-800/10">
                <td className="py-1.5 px-2 text-neutral-300 font-medium truncate max-w-[120px]">{d.label || 'N/A'}</td>
                <td className="py-1.5 px-2 text-right text-neutral-400 font-bold tabular-nums">{d.value.toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }

  // Fallback to bar list for bar/horizontal_bar/etc.
  const maxVal = Math.max(...chartData.map(d => d.value), 1);
  return (
    <div className="h-44 overflow-y-auto space-y-2 pr-1 pt-1">
      {chartData.map((d, i) => {
        const pct = (d.value / maxVal) * 100;
        return (
          <div key={d.label || i} className="text-[11px]">
            <div className="flex justify-between mb-0.5 text-neutral-300">
              <span className="truncate max-w-[150px]">{d.label || 'N/A'}</span>
              <span className="font-semibold text-neutral-400 tabular-nums">{d.value}</span>
            </div>
            <div className="h-1.5 bg-neutral-800 rounded-full overflow-hidden">
              <div
                className="h-full bg-gradient-to-r from-indigo-500 to-violet-500 rounded-full"
                style={{ width: `${pct}%` }}
              />
            </div>
          </div>
        );
      })}
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
  const { setFilter } = useFilterActions();
  const issueNo    = filters.issue_no    as string | undefined;
  const projFilter = (filters.project_id as string | undefined) || projectId || null;

  // AI states
  const [isAnalyzedView, setIsAnalyzedView] = useState(false);
  const [loadingAnalysis, setLoadingAnalysis] = useState(false);
  const [analysisData, setAnalysisData] = useState<DashboardAnalysis | null>(null);
  const [insightsData, setInsightsData] = useState<DashboardInsightsResponse | null>(null);
  const [analysisError, setAnalysisError] = useState<string | null>(null);

  // Fetch games dimensions to map UUID to game name in the taskbar
  const { data: projectOpts = [] } = useQuery<DimOption[]>({
    queryKey: ['dim', 'bug_projects'],
    queryFn: () => getDim('bug_projects'),
    staleTime: 60_000,
  });

  const activeFilters = {
    severity: filters.severity,
    status: filters.status,
    issue_no: issueNo,
  };

  // Reset analysis view and data when filters change
  useEffect(() => {
    setIsAnalyzedView(false);
    setAnalysisData(null);
    setInsightsData(null);
    setAnalysisError(null);
  }, [issueNo, projFilter, filters.severity, filters.status]);

  const handleAnalyzeClick = async () => {
    setLoadingAnalysis(true);
    setAnalysisError(null);

    try {
      let bugDetailsData = null;
      if (issueNo) {
        bugDetailsData = await fetchBugDetails(issueNo, projFilter);
      }

      // Step 1: Fetch dynamic dashboard visualizations plan from AI
      const plan = await fetchDashboardAnalysis({
        project_id: projFilter,
        filters: activeFilters,
        context: issueNo ? { field: 'issue_no', value: issueNo } : undefined,
      });
      setAnalysisData(plan);

      // Step 2: Fetch grounding insights and reasoning from AI
      const insights = await fetchDashboardInsights({
        project_id: projFilter,
        filters: activeFilters,
        dashboard_plan: plan,
        drilldown_data: bugDetailsData,
        context: issueNo ? { field: 'issue_no', value: issueNo, type: 'issue_no' } : undefined,
      });
      setInsightsData(insights);
      setIsAnalyzedView(true);
    } catch (err: any) {
      setAnalysisError(err.message || 'Failed to generate AI analysis.');
    } finally {
      setLoadingAnalysis(false);
    }
  };

  // Compile human readable description of the selected filters
  const selectedProjOpt = projectOpts.find(o => o.value === projFilter);
  const projLabel = selectedProjOpt ? selectedProjOpt.label : null;

  let taskbarText = 'Displaying dashboard for ';
  const filterDescParts: string[] = [];
  if (issueNo) filterDescParts.push(`Bug #${issueNo}`);
  if (projLabel) filterDescParts.push(`${projLabel} game`);
  if (filters.severity) filterDescParts.push(`severity ${filters.severity}`);
  if (filters.status) filterDescParts.push(`status ${filters.status}`);

  if (filterDescParts.length > 0) {
    taskbarText += filterDescParts.join(' and ');
  } else {
    taskbarText += 'all games and bugs';
  }

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
            ? 'Full bug record fetched from the database. Click ✨ Analyze to trigger LLM reasoning and custom dashboard.'
            : projFilter
            ? 'Showing all metrics scoped to the selected game. Select a Bug # to drill into a specific record.'
            : 'Full overview across all games. Filter by game, bug #, severity, or status to drill down.'}
        </p>
      </div>

      {/* Filter bar */}
      <div className="bg-neutral-900/60 border border-neutral-800 rounded-2xl p-5 space-y-3">
        <div className="text-[10px] font-bold text-neutral-500 uppercase tracking-widest">Filter by</div>
        <div className="flex flex-wrap gap-3">
          <FilterSelect dimension="bug_projects"   param="project_id" placeholder="🎮 All Games"      />
          <FilterSelect dimension="bug_issues"     param="issue_no"   placeholder="🐛 All Bugs #"     />
          <FilterSelect dimension="bug_severities" param="severity"   placeholder="⚠ All Severities"       />
          <FilterSelect dimension="bug_statuses"   param="status"     placeholder="📋 All Statuses"   />
        </div>
        <ActivePills />
      </div>

      {/* Interactive taskbar with Analyze button */}
      <div className="bg-gradient-to-r from-neutral-900/90 to-neutral-950/90 border border-neutral-800 rounded-2xl px-5 py-4 flex items-center justify-between flex-wrap gap-4 shadow-lg backdrop-blur-sm">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-xl bg-indigo-500/10 border border-indigo-500/25 flex items-center justify-center text-indigo-400">
            <Activity size={16} />
          </div>
          <div>
            <div className="text-[10px] font-bold text-neutral-500 uppercase tracking-wider">Dashboard Scope</div>
            <div className="text-sm text-neutral-200 font-medium capitalize mt-0.5">{taskbarText}</div>
          </div>
        </div>
        
        <div className="flex items-center gap-3">
          {isAnalyzedView && (
            <button
              onClick={() => setIsAnalyzedView(false)}
              className="flex items-center gap-1.5 px-4 py-2 bg-neutral-800 hover:bg-neutral-700/80 text-neutral-300 font-semibold text-xs rounded-xl border border-neutral-700 transition-all cursor-pointer"
            >
              <RotateCcw size={13} />
              <span>Basic View</span>
            </button>
          )}

          <button
            onClick={handleAnalyzeClick}
            disabled={loadingAnalysis}
            className="flex items-center gap-2 px-5 py-2 bg-gradient-to-r from-indigo-600 to-violet-600 hover:from-indigo-500 hover:to-violet-500 disabled:opacity-50 text-white font-semibold text-xs rounded-xl transition-all shadow-md shadow-indigo-950/40 cursor-pointer"
          >
            {loadingAnalysis ? (
              <>
                <div className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                <span>Running Agent...</span>
              </>
            ) : (
              <>
                <Sparkles size={13} />
                <span>Analyze</span>
              </>
            )}
          </button>
        </div>
      </div>

      {/* Error state */}
      {analysisError && (
        <div className="bg-rose-950/30 border border-rose-900/50 rounded-2xl p-4 flex items-start gap-3">
          <AlertOctagon className="text-rose-400 shrink-0 mt-0.5" size={16} />
          <div className="text-xs text-rose-300 leading-relaxed">
            <span className="font-bold">AI Analysis Offline:</span> {analysisError}. You can still use the Basic View below.
          </div>
        </div>
      )}

      {/* Main Content Area */}
      {!isAnalyzedView ? (
        <div className="space-y-6">
          <QuickStatsBanner projectId={projFilter} />
          {issueNo ? (
            <BugDetailPanel issueNo={issueNo} projectId={projFilter} />
          ) : (
            <OverviewPanel />
          )}
        </div>
      ) : (
        <div className="space-y-6 animate-fadeIn">
          {/* AI Analyzed Reasoning Header */}
          {insightsData && (
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
              
              {/* Executive Summary */}
              <div className="lg:col-span-2 bg-gradient-to-br from-indigo-950/40 via-neutral-900 to-neutral-900 border border-indigo-900/35 rounded-2xl p-5 space-y-3 shadow-md">
                <div className="flex items-center gap-2 text-indigo-400">
                  <Brain size={18} strokeWidth={2.5} />
                  <h3 className="text-sm font-bold uppercase tracking-wider">AI Executive Analysis</h3>
                </div>
                <p className="text-sm text-indigo-100/90 leading-relaxed font-normal">
                  {insightsData.executive_summary}
                </p>
              </div>

              {/* Scope Card */}
              <div className="bg-neutral-900 border border-neutral-850 rounded-2xl p-5 flex flex-col justify-between">
                <div>
                  <div className="text-xs font-semibold text-neutral-500 uppercase tracking-wider mb-2">Scope Summary</div>
                  <div className="text-xs text-neutral-300 space-y-2">
                    <div className="flex justify-between">
                      <span className="text-neutral-500">Selected Game:</span>
                      <span className="font-semibold text-neutral-200">{projLabel || 'All Games'}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-neutral-500">Selected Bug:</span>
                      <span className="font-semibold text-neutral-200">{issueNo ? `#${issueNo}` : 'All'}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-neutral-500">Filter Scope:</span>
                      <span className="font-mono text-neutral-200">{insightsData.data_scope}</span>
                    </div>
                  </div>
                </div>
                {insightsData.recommendations?.[0] && (
                  <div className="border-t border-neutral-800/60 pt-3 mt-3 text-[11px] text-neutral-400">
                    <span className="text-amber-400 font-bold mr-1">💡 Key Action:</span>
                    {insightsData.recommendations[0].action}
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Bug Investigation Deep-Dive (Visible when a specific bug is analyzed) */}
          {insightsData?.investigation && (
            <div className="bg-gradient-to-br from-neutral-900 via-neutral-900 to-indigo-950/15 border border-neutral-800 rounded-2xl p-6 space-y-5 shadow-lg">
              <div className="flex items-center gap-2 border-b border-neutral-800 pb-3">
                <span className="text-xs font-bold uppercase tracking-widest text-indigo-400 bg-indigo-950/60 border border-indigo-800/40 px-3 py-1 rounded-lg">
                  🔍 Bug Root Cause & Prevention Analysis
                </span>
              </div>

              {/* Dynamic stats */}
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <div className="bg-neutral-950/40 border border-neutral-850 rounded-xl p-3.5">
                  <div className="text-[10px] font-bold text-neutral-500 uppercase tracking-wider">Total Repeats</div>
                  <div className="text-xl font-bold text-neutral-200 tabular-nums mt-1">{insightsData.investigation.total_bugs_in_scope} times</div>
                </div>
                <div className="bg-neutral-950/40 border border-neutral-850 rounded-xl p-3.5">
                  <div className="text-[10px] font-bold text-neutral-500 uppercase tracking-wider">Unresolved Occurrences</div>
                  <div className="text-xl font-bold text-neutral-200 tabular-nums mt-1">{insightsData.investigation.unresolved_count} open</div>
                </div>
                <div className="bg-neutral-950/40 border border-neutral-850 rounded-xl p-3.5">
                  <div className="text-[10px] font-bold text-neutral-500 uppercase tracking-wider">Reproduction Rate</div>
                  <div className="text-xl font-bold text-indigo-400 mt-1">{insightsData.investigation.reproduction_rate_info || 'N/A'}</div>
                </div>
                <div className="bg-neutral-950/40 border border-neutral-850 rounded-xl p-3.5">
                  <div className="text-[10px] font-bold text-neutral-500 uppercase tracking-wider">Affected Games</div>
                  <div className="text-sm font-semibold text-neutral-200 mt-2 truncate">
                    {insightsData.investigation.affected_projects?.join(', ') || 'N/A'}
                  </div>
                </div>
              </div>

              {/* Root Cause Details */}
              <div className="grid grid-cols-1 md:grid-cols-3 gap-6 pt-2">
                <div className="md:col-span-2 bg-neutral-950/30 border border-neutral-850 rounded-xl p-4 space-y-2">
                  <div className="text-xs font-bold text-neutral-450 uppercase tracking-wider">Root Cause Reasoning</div>
                  <p className="text-xs text-neutral-300 leading-relaxed whitespace-pre-line">
                    {insightsData.investigation.summary}
                  </p>
                </div>

                <div className="bg-neutral-950/30 border border-neutral-850 rounded-xl p-4 space-y-3">
                  <div className="text-xs font-bold text-neutral-450 uppercase tracking-wider">Actionable Prevention Measures</div>
                  <ul className="space-y-2">
                    {insightsData.investigation.key_observations?.map((obs, index) => {
                      const isObsRoot = obs.startsWith("Root Cause:");
                      const isObsSev = obs.startsWith("Severity:");
                      const isObsMeas = obs.startsWith("Measures to avoid:");

                      return (
                        <li key={index} className="text-xs text-neutral-300 leading-relaxed flex items-start gap-2">
                          {isObsRoot ? <span className="text-indigo-400 shrink-0">🔬</span> : 
                           isObsSev ? <span className="text-rose-400 shrink-0">🚨</span> : 
                           isObsMeas ? <span className="text-emerald-400 shrink-0">✅</span> : 
                           <span className="text-neutral-500 shrink-0">•</span>}
                          <span>
                            <strong className="text-neutral-200">{obs.split(':')[0]}:</strong>
                            {obs.split(':').slice(1).join(':')}
                          </span>
                        </li>
                      );
                    })}
                    {(!insightsData.investigation.key_observations || insightsData.investigation.key_observations.length === 0) && (
                      <p className="text-xs text-neutral-500">No key observations available.</p>
                    )}
                  </ul>
                </div>
              </div>
            </div>
          )}

          {/* Actionable Recommendations list */}
          {insightsData?.recommendations && insightsData.recommendations.length > 0 && (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {insightsData.recommendations.map((rec, i) => (
                <div key={i} className="bg-neutral-900 border border-neutral-800 rounded-xl p-4 space-y-2">
                  <div className="flex items-center gap-2">
                    <span className="w-5 h-5 rounded-full bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 flex items-center justify-center text-[10px] font-bold">
                      {i + 1}
                    </span>
                    <h4 className="text-xs font-bold text-neutral-200">{rec.title}</h4>
                  </div>
                  <p className="text-xs text-neutral-300 leading-relaxed pl-7">{rec.action}</p>
                  <p className="text-[10px] text-neutral-500 italic pl-7">Rationale: {rec.rationale}</p>
                </div>
              ))}
            </div>
          )}

          {/* Adaptive Dynamic Dashboard Visualizations */}
          {analysisData && analysisData.visualizations && analysisData.visualizations.length > 0 && (
            <div className="space-y-4">
              <div className="flex flex-col gap-1 border-b border-neutral-800 pb-2">
                <h2 className="text-lg font-bold text-neutral-100 flex items-center gap-2">
                  <Layers size={18} className="text-indigo-400" />
                  <span>📊 AI Adaptive Visualizations</span>
                </h2>
                <p className="text-xs text-neutral-400">{analysisData.dashboard_purpose}</p>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                {analysisData.visualizations.map((viz) => (
                  <div key={viz.id} className="bg-neutral-900 border border-neutral-800 rounded-xl p-4 flex flex-col justify-between hover:border-neutral-700 transition-colors">
                    <div>
                      <div className="flex justify-between items-start gap-2 mb-2">
                        <h3 className="text-xs font-bold text-neutral-200 line-clamp-1">{viz.title}</h3>
                        <span className="text-[9px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded bg-neutral-800 text-neutral-400 border border-neutral-700/60 shrink-0">
                          {viz.type}
                        </span>
                      </div>
                      <p className="text-[10px] text-neutral-500 leading-snug mb-3 line-clamp-2">{viz.insight_goal}</p>
                    </div>

                    <div className="bg-neutral-950/40 border border-neutral-900 rounded-lg p-2.5">
                      <DynamicChart
                        viz={viz}
                        filters={activeFilters}
                        projFilter={projFilter}
                      />
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

    </div>
  );
}

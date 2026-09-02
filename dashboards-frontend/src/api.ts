import { useQuery, type UseQueryResult } from '@tanstack/react-query';
import { useFilters } from './filters';
import type { Format, MetricResponse } from './types';

// ---------------------------------------------------------------------------
// API base URL — override via VITE_DASHBOARDS_API or fall back to same-origin.
// ---------------------------------------------------------------------------

const API_BASE =
  (typeof import.meta !== 'undefined' && import.meta.env?.VITE_DASHBOARDS_API) ||
  '';

async function fetchMetric<T extends MetricResponse>(
  id: string,
  params: Record<string, unknown>,
  signal?: AbortSignal,
): Promise<T> {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v == null || v === '') continue;
    qs.set(k, typeof v === 'object' ? JSON.stringify(v) : String(v));
  }

  const res = await fetch(`${API_BASE}/api/metrics/${id}?${qs}`, {
    credentials: 'include',    // Send session cookies to the main app
    signal,
  });

  if (!res.ok) {
    const detail = await res.text().catch(() => '');
    throw new Error(`metric ${id} failed (${res.status}): ${detail}`);
  }
  return res.json() as Promise<T>;
}

// ---------------------------------------------------------------------------
// Bug Import API — upload Excel/CSV bug file
// ---------------------------------------------------------------------------

export interface ImportResultError {
  row: number;
  field: string;
  value: any;
  reason: string;
}

export interface ImportResult {
  inserted: number;
  updated: number;
  skipped: number;
  errors: ImportResultError[];
  warnings?: string[];
  total_rows?: number;
}

export async function uploadBugsFile(file: File, defaultProject?: string): Promise<ImportResult> {
  const formData = new FormData();
  formData.append('file', file);
  if (defaultProject) {
    formData.append('default_project', defaultProject);
  }

  const res = await fetch(`${API_BASE}/api/bugs/import`, {
    method: 'POST',
    body: formData,
    credentials: 'include',
  });

  if (!res.ok) {
    const errorJson = await res.json().catch(() => null);
    const message = errorJson?.detail || `Upload failed with status ${res.status}`;
    throw new Error(message);
  }

  return res.json();
}

// ---------------------------------------------------------------------------
// AI Dashboard Analyst & Dynamic Metric API
// ---------------------------------------------------------------------------

export interface KPIPlan {
  id: string;
  title: string;
  value_source: string;
  calculation: string;
  why_it_matters: string;
  priority: 'high' | 'medium' | 'low';
}

export interface VisualizationPlan {
  id: string;
  title: string;
  type: string;
  fields: string[];
  aggregation: string;
  group_by: string[];
  filters: string[];
  reason: string;
  insight_goal: string;
  priority: 'high' | 'medium' | 'low';
  drilldown?: {
    enabled: boolean;
    available_dimensions: string[];
    analysis_questions: string[];
  };
}

export interface Insight {
  type: string;
  severity: 'high' | 'medium' | 'low';
  title: string;
  explanation: string;
  supporting_fields: string[];
}

export interface FilterRecommendation {
  field: string;
  label: string;
  reason: string;
}

export interface DrilldownCapability {
  dimension: string;
  description: string;
  suggested_questions: string[];
}

export interface DashboardAnalysis {
  dashboard_title: string;
  dashboard_purpose: string;
  executive_summary: string;
  kpis: KPIPlan[];
  visualizations: VisualizationPlan[];
  insights: Insight[];
  recommended_filters: FilterRecommendation[];
  drilldown_capabilities: DrilldownCapability[];
}

export async function fetchDashboardAnalysis(payload: {
  project_id?: string | null;
  filters?: Record<string, any>;
  context?: Record<string, any>;
}): Promise<DashboardAnalysis> {
  const res = await fetch(`${API_BASE}/api/bugs/analyze`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
    credentials: 'include',
  });

  if (!res.ok) {
    const errorJson = await res.json().catch(() => null);
    const message = errorJson?.detail || `Analysis failed with status ${res.status}`;
    throw new Error(message);
  }

  const json = await res.json();
  return json.analysis;
}

// ---------------------------------------------------------------------------
// Step 2.4 Data Insights Interfaces & API Calls
// ---------------------------------------------------------------------------

export interface DataInsight {
  title: string;
  category: string;
  explanation: string;
  importance: 'high' | 'medium' | 'low';
  supporting_fields: string[];
  supporting_values: Record<string, any>;
  recommended_action?: string | null;
}

export interface VisualizationInsight {
  visualization_id: string;
  summary: string;
  key_finding: string;
  why_it_matters: string;
}

export interface AnomalyFinding {
  title: string;
  description: string;
  severity: 'high' | 'medium' | 'low';
  affected_field: string;
}

export interface TrendFinding {
  title: string;
  description: string;
  direction: 'increasing' | 'decreasing' | 'stable';
  field: string;
}

export interface ActionableRecommendation {
  title: string;
  action: string;
  priority: 'high' | 'medium' | 'low';
  rationale: string;
}

export interface SelectedEntityInvestigation {
  risk_rating?: { score: number; level: string; rating_deduction?: number } | null;
  confidence?: { score: number; level: string } | null;
  root_cause: string;
  why_this_rating: string;
  future_impact: string;
  recommendation: string;
}

export interface DashboardInsightsResponse {
  executive_summary: string;
  key_findings: DataInsight[];
  visualization_explanations: VisualizationInsight[];
  anomalies: AnomalyFinding[];
  trends: TrendFinding[];
  recommendations: ActionableRecommendation[];
  investigation?: SelectedEntityInvestigation | null;
  data_scope: string;
}

export async function fetchDashboardInsights(payload: {
  project_id?: string | null;
  filters?: Record<string, any>;
  context?: Record<string, any>;
  dashboard_plan?: Record<string, any>;
  drilldown_data?: Record<string, any>;
}): Promise<DashboardInsightsResponse> {
  const res = await fetch(`${API_BASE}/api/bugs/insights`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
    credentials: 'include',
  });

  if (!res.ok) {
    const errorJson = await res.json().catch(() => null);
    const message = errorJson?.detail || `Insights request failed with status ${res.status}`;
    throw new Error(message);
  }

  const json = await res.json();
  return json.insights;
}

export async function fetchBugDetails(issueNo: string, projectId?: string | null): Promise<any> {
  const qs = new URLSearchParams();
  qs.set('issue_no', issueNo);
  if (projectId) qs.set('project_id', projectId);

  const res = await fetch(`${API_BASE}/api/bugs/details?${qs}`, {
    credentials: 'include',
  });

  if (!res.ok) {
    const errorJson = await res.json().catch(() => null);
    const message = errorJson?.detail || `Failed to fetch bug details for ${issueNo}`;
    throw new Error(message);
  }

  const json = await res.json();
  return json.details;
}

export async function fetchDynamicMetric(params: {
  field_name: string;
  project_id?: string | null;
  metric?: string;
  filters?: Record<string, any>;
}): Promise<{ field: string; metric: string; data: Array<{ label: string; value: number }> }> {
  const qs = new URLSearchParams();
  qs.set('field_name', params.field_name);
  if (params.project_id) qs.set('project_id', params.project_id);
  if (params.metric) qs.set('metric', params.metric);

  if (params.filters) {
    for (const [k, v] of Object.entries(params.filters)) {
      if (v == null || v === '') continue;
      qs.set(k, typeof v === 'object' ? JSON.stringify(v) : String(v));
    }
  }

  const res = await fetch(`${API_BASE}/api/bugs/dynamic-metric?${qs}`, {
    credentials: 'include',
  });

  if (!res.ok) {
    const detail = await res.text().catch(() => '');
    throw new Error(`dynamic metric failed (${res.status}): ${detail}`);
  }
  return res.json();
}

// ---------------------------------------------------------------------------
// useMetric — the one hook every widget uses.
// ---------------------------------------------------------------------------

export function useMetric<T extends MetricResponse>(
  metricId: string,
  extra?: Record<string, unknown>,
  options?: { refetchInterval?: number },
): UseQueryResult<T, Error> {
  const filters = useFilters();
  const merged = { ...filters, ...(extra ?? {}) };

  return useQuery<T, Error>({
    queryKey: ['metric', metricId, merged],
    queryFn: ({ signal }) => fetchMetric<T>(metricId, merged, signal),
    refetchInterval: options?.refetchInterval ?? 7000,
    staleTime: 3000,
    refetchOnWindowFocus: true,
    retry: 1,
  });
}

// ---------------------------------------------------------------------------
// Number formatting — one place, called everywhere.
// ---------------------------------------------------------------------------

const compactFormatter = new Intl.NumberFormat('en-US', {
  notation: 'compact',
  maximumFractionDigits: 1,
});
const standardFormatter = new Intl.NumberFormat('en-US');
const percentFormatter = new Intl.NumberFormat('en-US', {
  style: 'percent',
  maximumFractionDigits: 1,
});
const currencyFormatter = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  maximumFractionDigits: 0,
});

export function formatValue(value: number, format: Format, compact = false): string {
  if (format === 'currency') return currencyFormatter.format(value);
  if (format === 'percent')  return percentFormatter.format(value);
  if (format === 'percent_whole') return `${value.toFixed(1)}%`;   // value already 0-100
  if (format === 'hours') {
    // Render hours human-friendly: <48h as hours, else days.
    if (value < 48) return `${value.toFixed(1)}h`;
    return `${(value / 24).toFixed(1)}d`;
  }
  return compact ? compactFormatter.format(value) : standardFormatter.format(value);
}

export function formatDelta(current: number, previous: number | null): {
  pct: number | null;
  text: string;
  direction: 'up' | 'down' | 'flat';
} {
  if (previous == null || previous === 0) {
    return { pct: null, text: '—', direction: 'flat' };
  }
  const pct = ((current - previous) / previous) * 100;
  const direction = pct > 0.5 ? 'up' : pct < -0.5 ? 'down' : 'flat';
  const sign = pct > 0 ? '+' : '';
  return { pct, text: `${sign}${pct.toFixed(1)}%`, direction };
}


export interface FeatureHealth {
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
  confidence_score: number;
  health_status: 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'SAFE';
  bug_list?: { id: string; severity: string; title: string; }[];
}

export interface CriticalIssue {
  issue_no: string;
  title: string;
  severity: string;
  status: string;
  feature?: string;
}

export interface GameHealth {
  project_id: string;
  name: string;
  total_bugs: number;
  open_bugs: number;
  in_progress_bugs: number;
  closed_bugs: number;
  critical_bugs: number;
  high_bugs: number;
  medium_bugs: number;
  low_bugs: number;
  feature_count: number;
  risk_score: number;
  confidence_score: number;
  health_status: 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'SAFE';
  critical_issues?: CriticalIssue[];
}

export interface GameHealthResponse {
  game: GameHealth;
  features: FeatureHealth[];
  data_signature?: string;
  top_critical_bugs?: CriticalIssue[];
}

export async function fetchGameHealth(projectId: string): Promise<GameHealthResponse> {
  const res = await fetch(`${API_BASE}/api/bugs/game-health?project_id=${projectId}`, {
    credentials: 'include',
  });
  if (!res.ok) {
    throw new Error('Failed to fetch game health');
  }
  return res.json();
}

export async function fetchGameSummary(gameHealth: any, forceRefresh: boolean = false): Promise<{ summary: string }> {
  const payload = {
    ...gameHealth,
    force_refresh: forceRefresh,
  };
  const res = await fetch(`${API_BASE}/api/bugs/game-summary`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
    credentials: 'include',
  });
  if (!res.ok) {
    throw new Error('Failed to fetch game summary');
  }
  return res.json();
}

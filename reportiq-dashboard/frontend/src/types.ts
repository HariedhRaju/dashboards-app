// Response shapes returned by the backend metrics API.
// These mirror the Python models shapes exactly.

export type Format = 'number' | 'currency' | 'percent' | 'percent_whole' | 'hours';

export interface ScalarResponse {
  kind: 'scalar';
  value: number;
  previous: number | null;
  format: Format;
}

export interface SeriesPoint { t: string; v: number; }
export interface Series      { name: string; points: SeriesPoint[]; }
export interface SeriesResponse {
  kind: 'series';
  series: Series[];
  format: Format;
}

export interface GroupItem { key: string; value: number; }
export interface GroupResponse {
  kind: 'group';
  groups: GroupItem[];
  format: Format;
}

export interface TableResponse {
  kind: 'table';
  columns: string[];
  rows: Record<string, unknown>[];
  total: number;
  format: Format;
}

export type MetricResponse =
  | ScalarResponse
  | SeriesResponse
  | GroupResponse
  | TableResponse;

// ---------------------------------------------------------------------------
// Dashboard config types
// ---------------------------------------------------------------------------

export type Widget =
  | {
      type: 'metric';
      metric: string;
      title: string;
      subtitle?: string;
      icon?: 'link' | 'cpu' | 'layers' | 'activity' | 'users' | 'zap';
      iconColor?: 'orange' | 'blue' | 'green' | 'purple' | 'cyan' | 'amber';
      goodDirection?: 'up' | 'down' | 'neutral';
    }
  | { type: 'timeseries'; metric: string; title: string; stacked?: boolean }
  | { type: 'donut';      metric: string; title: string; colorScheme?: 'default' | 'severity' | 'status' }
  | { type: 'bar';        metric: string; title: string; colorScheme?: 'default' | 'severity' | 'status' }
  | { type: 'gauge';      metric: string; title: string; badge?: string; unit?: string }
  | { type: 'funnel';     metric: string; title: string }
  | { type: 'speed_dial'; metric: string; title: string; unit?: string }
  | { type: 'heatmap';    metric: string; title: string }
  | { type: 'leaderboard'; metric: string; title: string }
  | { type: 'project_banner'; metric: string }
  | { type: 'health_bar';  metric: string; title: string }
  | { type: 'timeline';    metric: string; title: string }
  | { type: 'progress_trend'; metric: string; title: string }
  | { type: 'what_changed'; metric: string; title: string }
  | { type: 'attention_required'; metric: string; title: string }
  | { type: 'milestone_tracker'; metric: string; title: string }
  | { type: 'portfolio_matrix'; metric: string; title: string }
  | {
      type: 'table';
      metric: string;
      title: string;
      sortableColumns?: string[];
      columnConfig?: Record<string, ColumnConfig>;
      pageSize?: number;
      compact?: boolean;         // Hide pagination footer
      refetchMs?: number;        // Override default 7s polling
    };

/**
 * Per-column presentation config.
 */
export interface ColumnConfig {
  label?: string;                                                    // Header override
  align?: 'left' | 'right' | 'center';                               // Default: right for numeric-looking cols
  format?: 'text' | 'number' | 'bold-number' | 'muted' | 'feature-icon' | 'badge'
         | 'timestamp' | 'severity-badge' | 'status-badge' | 'age' | 'percent-cell'
         | 'format-badge' | 'pipeline-stage-badge' | 'build-status-badge'
         | 'health-status-badge' | 'progress-bar' | 'report-type-badge'
         | 'milestone-status-badge' | 'risk-severity-badge';
  hideOn?: 'compact';                                                // Hide this column in compact mode
}

/**
 * A widget cell hides itself when any of these filter keys is active.
 */
export type HideWhen = (keyof FilterState)[];

export interface LayoutCell {
  w: number;   // 1–12 grid columns
  h: number;   // Row height in units (1 unit ≈ 88px)
  widget: Widget;
  hideWhen?: HideWhen;
  showWhen?: HideWhen;
}

export interface DashboardDef {
  slug: string;
  title: string;
  category?: string;
  requires?: string[];
  filterBar?: FilterDropdown[];   // dropdowns shown in the filter bar
  layout: LayoutCell[];
}

// ---------------------------------------------------------------------------
// Filter state — date range is always present; other keys are dashboard-specific
// ---------------------------------------------------------------------------

export interface FilterState {
  date_range_start: string;
  date_range_end: string;
  [key: string]: string | undefined;
}

/**
 * A dropdown filter in the FilterBar. `param` is the URL query key AND the
 * filter key sent to the API. `dimension` is the /api/dimensions/:name source.
 */
export interface FilterDropdown {
  param: string;          // e.g. 'project_id' → ?project_id=...
  dimension: string;      // e.g. 'projects' → GET /api/dimensions/projects
  placeholder: string;    // e.g. 'All projects'
}

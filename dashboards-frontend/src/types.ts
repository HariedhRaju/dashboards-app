// Response shapes returned by the backend metrics API.
// These mirror the Python `models.py` shapes exactly.

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

export interface MatrixRow {
  feature: string;
  assigned: string;                      // the feature's assigned priority tier
  cells: Record<string, number>;         // priority → count
  total: number;
}

export interface MatrixResponse {
  kind: 'matrix';
  columns: string[];                     // e.g. ['Core','High','Medium','Low']
  rows: MatrixRow[];
  format: Format;
}

export type MetricResponse =
  | ScalarResponse
  | SeriesResponse
  | GroupResponse
  | TableResponse
  | MatrixResponse;

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
  | { type: 'donut';      metric: string; title: string; colorScheme?: 'default' | 'severity' | 'status' | 'priority' }
  | { type: 'bar';        metric: string; title: string; colorScheme?: 'default' | 'severity' | 'status' | 'priority'; highlightZero?: boolean }
  | { type: 'gauge';      metric: string; title: string; badge?: string; unit?: string }
  | { type: 'heatmap';    metric: string; title: string; note?: string }
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
 * Per-column presentation config. All fields optional; sensible defaults apply.
 */
export interface ColumnConfig {
  label?: string;                                                    // Header override
  align?: 'left' | 'right' | 'center';                               // Default: right for numeric-looking cols
  format?: 'text' | 'number' | 'bold-number' | 'muted' | 'feature-icon' | 'badge'
         | 'timestamp' | 'severity-badge' | 'status-badge' | 'age' | 'percent-cell'
         | 'priority-pill' | 'test-type' | 'drift-dot' | 'bool-check' | 'step-count';
  hideOn?: 'compact';                                                // Hide this column in compact mode
}

/**
 * A widget cell hides itself when any of these filter keys is active.
 */
export type HideWhen = (keyof FilterState)[];

export interface LayoutCell {
  w: number;   // 1–12 grid columns
  h: number;   // Row height in units (1 unit ≈ 120px)
  widget: Widget;
  hideWhen?: HideWhen;
  /**
   * When true, the cell grows to fit its content instead of being clamped to
   * `h` fixed rows. Use for data-driven widgets (heatmaps, long compact tables)
   * so they never show an internal scrollbar. `h` still acts as a minimum.
   */
  autoHeight?: boolean;
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
// Filter state — a generic string map. Date range is always present; other
// keys are dashboard-specific (user_id, severity, status, etc.).
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
  param: string;          // e.g. 'severity' → ?severity=P1 and passed to API as severity
  dimension: string;      // e.g. 'bug_severities' → GET /api/dimensions/bug_severities
  placeholder: string;    // e.g. 'All severities'
}

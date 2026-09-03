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

/**
 * A grid whose cells carry a STATUS rather than a count — the localization
 * matrix. Distinct from MatrixResponse because the colour of a cell is decided
 * by its own outcome, not by its magnitude relative to a column.
 */
export interface StatusMatrixRow {
  item: string;
  section: string | null;
  cells: Record<string, string>;        // dimension → status
  not_passing: number;
  comment?: string | null;
}

export interface StatusMatrixResponse {
  kind: 'status_matrix';
  columns: string[];                    // e.g. ['Chinese','English','French', …]
  rows: StatusMatrixRow[];
  statuses: string[];                   // the vocabulary, for the legend
  format: Format;
}

/** One themed section of the report, with the ids its body cites. */
export interface ReportSection {
  title: string;
  body: string;
  citations: string[];
}

/** The agent's narrated summary. `available: false` until an analysis has run. */
export interface NarrativeResponse {
  kind: 'narrative';
  available: boolean;
  verdict: 'healthy' | 'caution' | 'at_risk' | 'blocked' | 'unknown';
  headline: string;
  narrative: string;
  sections: ReportSection[];
  recommendation: string;
  risks: string[];
  generated_at: string | null;
  model_enabled: boolean;
  model_name: string | null;
  partial: boolean;
}

export interface Finding {
  id: string;
  kind: string;
  level: 'critical' | 'warning' | 'info';
  title: string;
  detail: string;
  impact: number;
  value: number | null;
  unit: 'count' | 'percent' | 'days';
  /** The concrete next step, written by the detector that raised this. */
  action: string;
  evidence: Record<string, unknown>[];
}

export interface FindingsResponse {
  kind: 'findings';
  available: boolean;
  findings: Finding[];
  counts: { critical: number; warning: number; info: number };
  generated_at: string | null;
}

export type MetricResponse =
  | ScalarResponse
  | SeriesResponse
  | GroupResponse
  | TableResponse
  | MatrixResponse
  | StatusMatrixResponse
  | NarrativeResponse
  | FindingsResponse;

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
  | { type: 'statusmatrix'; metric: string; title: string; note?: string }
  | { type: 'narrative';  metric: string; title: string; emptyHint?: string }
  | {
      type: 'findings';
      metric: string;
      title: string;
      /** Cap the list; the rest stay behind a "show all" toggle. */
      limit?: number;
      emptyHint?: string;
    }
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
   * Capability keys this cell needs before it is worth rendering, resolved
   * against `DashboardDef.capabilities`. A cell whose keys are not all
   * satisfied is dropped and its row rebalances around it.
   *
   * This is about the SHAPE of the data, not its values: a workbook with no
   * localization sheet should not show a locale heatmap, an empty locale bar
   * and a "0.0%" localization KPI — three tiles reporting one absence.
   */
  requires?: string[];
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
  /**
   * Endpoint returning `{ capabilities: Record<string, boolean> }` describing
   * what the current data actually contains. Cells declaring `requires` are
   * filtered against it. Omitted, every cell renders.
   */
  capabilities?: string;
  /** Optional control panel rendered above the grid. */
  console?: 'qa';
  /** Hide the date-range presets when they do not apply to this data. */
  hideDateRange?: boolean;
  /** Show an explicit calendar range picker (with an "All data" mode). */
  calendarRange?: boolean;
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

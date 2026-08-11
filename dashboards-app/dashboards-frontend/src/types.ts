// Response shapes returned by the backend metrics API.
// These mirror the Python `models.py` shapes exactly.

export type Format = 'number' | 'currency' | 'percent';

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
  | { type: 'donut';      metric: string; title: string }
  | { type: 'bar';        metric: string; title: string }
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
  format?: 'text' | 'number' | 'bold-number' | 'muted' | 'feature-icon' | 'badge' | 'timestamp';
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
}

export interface DashboardDef {
  slug: string;
  title: string;
  category?: string;
  requires?: string[];
  filters?: readonly ('dateRange' | 'projectId' | 'modelName' | 'feature')[];
  layout: LayoutCell[];
}

// ---------------------------------------------------------------------------
// Filter state — global filter bar values
// ---------------------------------------------------------------------------

export interface FilterState {
  date_range_start: string;   // ISO 8601
  date_range_end: string;     // ISO 8601
  user_id?: string;
  project_id?: string;
  model_name?: string;
  feature?: string;
}

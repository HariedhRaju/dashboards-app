// Public API for ReportIQ Dashboard package.

export { default as DashboardApp } from './DashboardApp';
export { DashboardRenderer } from './DashboardRenderer';
export { FilterProvider, FilterBar, useFilters, useFilterActions } from './filters';
export { useMetric, formatValue, formatDelta } from './api';
export { registry, loadDashboard, dashboardIndex } from './registry';

export type {
  DashboardDef, Widget, LayoutCell, FilterState,
  ScalarResponse, SeriesResponse, GroupResponse, TableResponse, MetricResponse,
  Format,
} from './types';

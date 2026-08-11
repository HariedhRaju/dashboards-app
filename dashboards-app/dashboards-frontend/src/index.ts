// Public API for @yourorg/dashboards.
//
// The main app imports DashboardApp and mounts it at /analytics/*.
// Everything else is internal, but exported here in case you need to
// wrap or compose it.

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

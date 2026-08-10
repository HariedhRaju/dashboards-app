import type { DashboardDef } from '../types';

/**
 * Token Usage dashboard.
 *
 * Row 1 — four KPI cards (3 cols each, 1 row tall)
 * Row 2 — time series (8 cols) + donut (4 cols), 3 rows tall
 * Row 3 — feature bar (6) + project bar (6), 3 rows tall
 * Row 4 — detail table (12 cols), 5 rows tall
 *
 * Per-user drill-down happens via the table + user filter dropdown,
 * not a separate "top users" bar chart.
 */
const tokenUsageDashboard: DashboardDef = {
  slug: 'token-usage',
  title: 'Token usage',
  category: 'ops',
  filters: ['dateRange', 'projectId', 'modelName', 'feature'],
  layout: [
    // Row 1 — KPIs
    { w: 3, h: 1, widget: { type: 'metric', metric: 'tokens.total',        title: 'Total tokens',      goodDirection: 'neutral' } },
    { w: 3, h: 1, widget: { type: 'metric', metric: 'tokens.calls.count',  title: 'API calls',         goodDirection: 'neutral' } },
    { w: 3, h: 1, widget: { type: 'metric', metric: 'tokens.avg_per_call', title: 'Avg tokens / call', goodDirection: 'down'    } },
    { w: 3, h: 1, widget: { type: 'metric', metric: 'tokens.users.active', title: 'Active users',      goodDirection: 'up'      } },

    // Row 2 — trend + composition
    { w: 8, h: 3, widget: { type: 'timeseries', metric: 'tokens.timeseries', title: 'Token usage over time', stacked: true } },
    { w: 4, h: 3, widget: { type: 'donut',      metric: 'tokens.by_model',   title: 'By model' } },

    // Row 3 — breakdowns (feature + project)
    { w: 6, h: 3, widget: { type: 'bar', metric: 'tokens.by_feature', title: 'By feature' } },
    { w: 6, h: 3, widget: { type: 'bar', metric: 'tokens.by_project', title: 'By project' } },

    // Row 4 — detail table with model column, group by (user, project, model)
    {
      w: 12, h: 5,
      widget: {
        type: 'table',
        metric: 'tokens.top_consumers',
        title: 'Detail — usage by user, project & model',
        sortableColumns: ['total_tokens', 'calls', 'avg_per_call'],
      },
    },
  ],
};

export default tokenUsageDashboard;

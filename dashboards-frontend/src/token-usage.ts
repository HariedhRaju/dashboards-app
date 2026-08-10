import type { DashboardDef } from '../types';

/**
 * Token Usage dashboard.
 *
 * `hideWhen` tags on each grouping widget: if the user has already narrowed
 * to a single value for that dimension, the widget collapses to one bar and
 * conveys nothing — so hide it and let the row rebalance.
 *
 * KPIs, time series, and the detail table are always shown; they carry
 * useful information at every level of filtering.
 */
const tokenUsageDashboard: DashboardDef = {
  slug: 'token-usage',
  title: 'Token usage',
  category: 'ops',
  filters: ['dateRange', 'projectId', 'modelName', 'feature'],
  layout: [
    // Row 1 — KPIs (always visible)
    { w: 3, h: 1, widget: { type: 'metric', metric: 'tokens.total',        title: 'Total tokens',      goodDirection: 'neutral' } },
    { w: 3, h: 1, widget: { type: 'metric', metric: 'tokens.calls.count',  title: 'API calls',         goodDirection: 'neutral' } },
    { w: 3, h: 1, widget: { type: 'metric', metric: 'tokens.avg_per_call', title: 'Avg tokens / call', goodDirection: 'down'    } },
    { w: 3, h: 1, widget: { type: 'metric', metric: 'tokens.users.active', title: 'Active users',      goodDirection: 'up'      } },

    // Row 2 — trend (always) + model donut (hidden when model filter active)
    { w: 8, h: 3, widget: { type: 'timeseries', metric: 'tokens.timeseries', title: 'Token usage over time', stacked: true } },
    { w: 4, h: 3, widget: { type: 'donut',      metric: 'tokens.by_model',   title: 'By model' },
      hideWhen: ['model_name'] },

    // Row 3 — feature bar (hidden when feature filter active) + project bar (hidden when project filter active)
    { w: 6, h: 3, widget: { type: 'bar', metric: 'tokens.by_feature', title: 'By feature' },
      hideWhen: ['feature'] },
    { w: 6, h: 3, widget: { type: 'bar', metric: 'tokens.by_project', title: 'By project' },
      hideWhen: ['project_id'] },

    // Row 4 — detail table (always visible)
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

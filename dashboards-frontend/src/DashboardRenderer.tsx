import { Component, type ErrorInfo, type ReactNode } from 'react';
import { FilterBar, useFilters } from './filters';
import {
  BarWidget, DonutWidget, FunnelWidget, GaugeWidget, HeatmapGridWidget, LeaderboardWidget, MetricWidget, SpeedDialWidget, TableWidget, TimeseriesWidget,
  ProjectBannerWidget, ProjectHealthWidget, WhatChangedWidget, ProjectTimelineWidget, ProgressTrendWidget, AttentionRequiredWidget, MilestoneTrackerWidget, PortfolioMatrixWidget,
} from './widgets';
import type { DashboardDef, FilterState, LayoutCell, Widget } from './types';
import { AgentDashboardRenderer } from './AgentDashboardRenderer';

// ---------------------------------------------------------------------------
// WidgetRenderer — one switch, everything else falls out.
// ---------------------------------------------------------------------------

function WidgetRenderer({ widget }: { widget: Widget }) {
  switch (widget.type) {
    case 'metric':             return <MetricWidget             {...widget} />;
    case 'timeseries':         return <TimeseriesWidget         {...widget} />;
    case 'donut':              return <DonutWidget              {...widget} />;
    case 'bar':                return <BarWidget                {...widget} />;
    case 'gauge':              return <GaugeWidget              {...widget} />;
    case 'funnel':             return <FunnelWidget             {...widget} />;
    case 'speed_dial':         return <SpeedDialWidget          {...widget} />;
    case 'heatmap':            return <HeatmapGridWidget        {...widget} />;
    case 'leaderboard':        return <LeaderboardWidget        {...widget} />;
    case 'table':              return <TableWidget              {...widget} />;
    case 'project_banner':     return <ProjectBannerWidget      {...widget} />;
    case 'health_bar':         return <ProjectHealthWidget      {...widget} />;
    case 'what_changed':       return <WhatChangedWidget        {...widget} />;
    case 'timeline':           return <ProjectTimelineWidget    {...widget} />;
    case 'progress_trend':     return <ProgressTrendWidget      {...widget} />;
    case 'attention_required': return <AttentionRequiredWidget   {...widget} />;
    case 'milestone_tracker':  return <MilestoneTrackerWidget   {...widget} />;
    case 'portfolio_matrix':   return <PortfolioMatrixWidget    {...widget} />;
  }
}

// ---------------------------------------------------------------------------
// Error boundary — one broken widget must not blank the dashboard.
// ---------------------------------------------------------------------------

class WidgetErrorBoundary extends Component<
  { children: ReactNode },
  { hasError: boolean }
> {
  state = { hasError: false };
  static getDerivedStateFromError(): { hasError: boolean } { return { hasError: true }; }
  componentDidCatch(err: Error, info: ErrorInfo) {
    console.error('Widget crashed:', err, info);
  }
  render() {
    if (this.state.hasError) {
      return (
        <div className="h-full flex items-center justify-center bg-red-950/30 border border-red-900 rounded-xl p-4">
          <span className="text-sm text-red-300">Widget failed to render.</span>
        </div>
      );
    }
    return this.props.children;
  }
}

// ---------------------------------------------------------------------------
// Row rebalancing
// ---------------------------------------------------------------------------

/**
 * A widget is hidden when:
 *  - hideWhen: any listed filter key has a truthy value → hide
 *  - showWhen: NONE of the listed filter keys have a truthy value → hide
 */
function isHidden(cell: LayoutCell, filters: FilterState): boolean {
  if (cell.hideWhen?.length) {
    if (cell.hideWhen.some(key => Boolean(filters[key]))) return true;
  }
  if (cell.showWhen?.length) {
    if (!cell.showWhen.some(key => Boolean(filters[key]))) return true;
  }
  return false;
}

/**
 * Group cells into rows by walking the 12-column grid.
 * Rebalance each row so surviving cells fill the width evenly.
 * Preserves the original heights and order.
 */
function rebalance(layout: LayoutCell[], filters: FilterState): LayoutCell[] {
  const result: LayoutCell[] = [];
  let row: LayoutCell[] = [];
  let rowWidth = 0;

  const flushRow = () => {
    if (row.length === 0) return;
    const visible = row.filter(c => !isHidden(c, filters));
    if (visible.length === 0) return;                        // whole row disappears
    if (visible.length === row.length) {
      result.push(...row);                                    // nothing hidden here
    } else {
      // Distribute the row's original width evenly across survivors.
      const share = Math.floor(12 / visible.length);
      const remainder = 12 - share * visible.length;
      visible.forEach((c, i) => {
        result.push({ ...c, w: share + (i < remainder ? 1 : 0) });
      });
    }
    row = [];
    rowWidth = 0;
  };

  for (const cell of layout) {
    if (rowWidth + cell.w > 12) flushRow();
    row.push(cell);
    rowWidth += cell.w;
    if (rowWidth === 12) flushRow();
  }
  flushRow();

  return result;
}

export function DashboardRenderer({ def }: { def: DashboardDef }) {
  const filters = useFilters();
  const cells = rebalance(def.layout, filters);
  const isBugReports = def.slug === 'bug-reports';

  return (
    <div className="max-w-[1400px] mx-auto p-6">
      <FilterBar
        title={def.title}
        dropdowns={isBugReports ? undefined : def.filterBar}
      />

      {isBugReports ? (
        <AgentDashboardRenderer projectId={filters.project_id as string} />
      ) : (
        <div
          className="grid grid-cols-12 gap-3"
          style={{ gridAutoRows: '120px' }}
        >
          {cells.map((cell, i) => (
            <div
              key={i}
              style={{
                gridColumn: `span ${cell.w} / span ${cell.w}`,
                gridRow:    `span ${cell.h} / span ${cell.h}`,
              }}
            >
              <WidgetErrorBoundary>
                <WidgetRenderer widget={cell.widget} />
              </WidgetErrorBoundary>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

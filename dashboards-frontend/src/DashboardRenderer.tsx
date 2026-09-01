import { Component, type ErrorInfo, type ReactNode } from 'react';
import { useQuery } from '@tanstack/react-query';

import { API_BASE } from './api';
import { QaConsole } from './qa-console';
import { FilterBar, useFilters } from './filters';
import {
  BarWidget, DonutWidget, GaugeWidget, HeatmapWidget, MetricWidget, TableWidget, TimeseriesWidget,
} from './widgets';
import { FindingsWidget, NarrativeWidget, StatusMatrixWidget } from './qa-widgets';
import type { DashboardDef, FilterState, LayoutCell, Widget } from './types';

// ---------------------------------------------------------------------------
// WidgetRenderer — one switch, everything else falls out.
// ---------------------------------------------------------------------------

function WidgetRenderer({ widget }: { widget: Widget }) {
  switch (widget.type) {
    case 'metric':     return <MetricWidget     {...widget} />;
    case 'timeseries': return <TimeseriesWidget {...widget} />;
    case 'donut':      return <DonutWidget      {...widget} />;
    case 'bar':        return <BarWidget        {...widget} />;
    case 'gauge':      return <GaugeWidget      {...widget} />;
    case 'heatmap':    return <HeatmapWidget    {...widget} />;
    case 'table':      return <TableWidget      {...widget} />;
    case 'statusmatrix': return <StatusMatrixWidget {...widget} />;
    case 'narrative':    return <NarrativeWidget    {...widget} />;
    case 'findings':     return <FindingsWidget     {...widget} />;
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

type Capabilities = Record<string, boolean> | null;

/**
 * A widget is hidden when either signal says it is not worth its space:
 *
 *   hideWhen  a filter already pins the dimension the widget breaks down by.
 *             A single-select restricting to one feature makes "by feature"
 *             the same number twice.
 *
 *   requires  the data has no such dimension at all — a workbook with no
 *             localization sheet, a bug list with no usable dates.
 *
 * While capabilities are still loading (`caps === null`) nothing is hidden on
 * that basis, so the grid does not visibly reflow a moment after it paints.
 */
function isHidden(cell: LayoutCell, filters: FilterState, caps: Capabilities): boolean {
  if (cell.hideWhen?.length && cell.hideWhen.some(key => Boolean(filters[key]))) {
    return true;
  }
  if (cell.requires?.length && caps) {
    return !cell.requires.every(key => caps[key]);
  }
  return false;
}

/**
 * Group cells into rows by walking the 12-column grid.
 * Rebalance each row so surviving cells fill the width evenly.
 * Preserves the original heights and order.
 */
function rebalance(
  layout: LayoutCell[], filters: FilterState, caps: Capabilities,
): LayoutCell[][] {
  const rows: LayoutCell[][] = [];
  let row: LayoutCell[] = [];
  let rowWidth = 0;

  const flushRow = () => {
    if (row.length === 0) return;
    const visible = row.filter(c => !isHidden(c, filters, caps));
    if (visible.length === 0) { row = []; rowWidth = 0; return; }  // row disappears

    if (visible.length === row.length) {
      rows.push(row);                                        // nothing hidden here
    } else {
      // Distribute the row's original width evenly across survivors.
      const share = Math.floor(12 / visible.length);
      const remainder = 12 - share * visible.length;
      rows.push(visible.map((c, i) => ({
        ...c, w: share + (i < remainder ? 1 : 0),
      })));
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

  return rows;
}

// ---------------------------------------------------------------------------
// Auto-height cells
// ---------------------------------------------------------------------------

const ROW_PX = 120;
const GAP_PX = 12;      // matches gap-3

/** A cell's declared height in pixels — `h` row units plus the gaps between. */
function cellHeight(h: number): number {
  return h * ROW_PX + (h - 1) * GAP_PX;
}

// ---------------------------------------------------------------------------
// Capabilities — what the current data actually contains
// ---------------------------------------------------------------------------

/**
 * One request per dashboard, not one per widget. Returns null while loading so
 * `isHidden` can distinguish "no capability" from "not known yet" and avoid
 * hiding tiles it is about to show again.
 */
function useCapabilities(endpoint: string | undefined, snapshotId?: string): Capabilities {
  const { data } = useQuery({
    queryKey: ['capabilities', endpoint, snapshotId],
    enabled: Boolean(endpoint),
    queryFn: async () => {
      const qs = snapshotId ? `?snapshot_id=${encodeURIComponent(snapshotId)}` : '';
      const res = await fetch(`${API_BASE}${endpoint}${qs}`, { credentials: 'include' });
      if (!res.ok) throw new Error(`capabilities failed (${res.status})`);
      return res.json() as Promise<{ capabilities: Record<string, boolean> }>;
    },
    staleTime: 5000,
    // Polled, not fetch-once-and-wait-for-an-invalidate. `capabilities.report`
    // flips from false to true the moment an analysis finishes, and that can
    // happen from another tab, a curl call, or a click whose invalidation
    // raced the write — none of which this hook's own cache would otherwise
    // hear about. A short poll means a whole section of the dashboard
    // reappearing is bounded by a few seconds, not by remounting the page.
    refetchInterval: 8000,
  });
  return data?.capabilities ?? null;
}

// ---------------------------------------------------------------------------
// DashboardRenderer
// ---------------------------------------------------------------------------

export function DashboardRenderer({ def }: { def: DashboardDef }) {
  const filters = useFilters();
  const caps = useCapabilities(def.capabilities, filters.snapshot_id);
  const rows = rebalance(def.layout, filters, caps);

  return (
    <div className="max-w-[1400px] mx-auto px-3 py-4 sm:px-6 sm:py-6">
      <FilterBar title={def.title} dropdowns={def.filterBar}
                 showRange={!def.hideDateRange} />
      {def.console === 'qa' && <QaConsole />}

      {/*
        Each row is its OWN grid, rather than every cell sharing one big
        auto-placed one.

        With a single grid, a tall cell (a full report spanning many row tracks)
        leaves a narrow gutter beside it, and auto-placement then packs the
        following cells into that gutter one per track — which is how five KPI
        tiles ended up stacked in a column next to the summary instead of
        sitting in their own row. Per-row grids make a row's height a local
        question: nothing can flow out of its row into a gap somewhere else.

        Rows also size themselves. `align-items: stretch` (the default) makes
        every cell in a row as tall as its tallest sibling, so a long report and
        the findings list beside it end up flush without either being measured.
      */}
      {rows.map((row, r) => (
        <div key={r} className="grid grid-cols-1 md:grid-cols-12 gap-3 mb-3">
          {row.map((cell, i) => (
            <div
              key={i}
              style={{
                // In the 1-column layout the browser clamps a span to the
                // tracks that exist, so every cell goes full width on a phone
                // with no breakpoint bookkeeping here.
                gridColumn: `span ${cell.w} / span ${cell.w}`,
                // autoHeight: `h` is a floor and content may exceed it.
                // Otherwise `h` is exact and the widget scrolls inside.
                ...(cell.autoHeight
                  ? { minHeight: cellHeight(cell.h) }
                  : { height: cellHeight(cell.h) }),
              }}
            >
              <WidgetErrorBoundary>
                <WidgetRenderer widget={cell.widget} />
              </WidgetErrorBoundary>
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}

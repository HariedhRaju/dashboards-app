import { useState, type ReactNode } from 'react';
import {
  Area, AreaChart, CartesianGrid, Cell, Pie, PieChart,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts';
import { format as formatDate, parseISO } from 'date-fns';
import clsx from 'clsx';

import { formatDelta, formatValue, useMetric } from './api';
import type {
  GroupResponse, ScalarResponse, SeriesResponse, TableResponse,
} from './types';

// ══════════════════════════════════════════════════════════════════════════
//  Dark-mode palette
// ══════════════════════════════════════════════════════════════════════════

/** Chart palette tuned for dark backgrounds — 400-level Tailwind hues. */
const PALETTE = [
  '#818CF8', // indigo-400
  '#22D3EE', // cyan-400
  '#34D399', // emerald-400
  '#FBBF24', // amber-400
  '#F472B6', // pink-400
  '#F87171', // red-400
  '#A3E635', // lime-400
  '#94A3B8', // slate-400
];
const OTHER_COLOR = '#525252';   // neutral-600 — visibly muted
const GRID_COLOR = '#262626';    // neutral-800
const AXIS_TEXT = '#737373';     // neutral-500
const TOOLTIP_BG = '#171717';    // neutral-900
const TOOLTIP_BORDER = '#404040'; // neutral-700

// ══════════════════════════════════════════════════════════════════════════
//  Shared building blocks
// ══════════════════════════════════════════════════════════════════════════

function Card({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div className={clsx(
      'bg-neutral-900 border border-neutral-800 rounded-xl p-4 h-full flex flex-col',
      className,
    )}>
      {children}
    </div>
  );
}

function CardHeader({ title, right }: { title: string; right?: ReactNode }) {
  return (
    <div className="flex items-center justify-between mb-3">
      <h3 className="text-sm font-medium text-neutral-200">{title}</h3>
      {right && <div className="text-xs text-neutral-400">{right}</div>}
    </div>
  );
}

function Skeleton({ className }: { className?: string }) {
  return <div className={clsx('bg-neutral-800/60 rounded animate-pulse', className)} />;
}

function ErrorState({ onRetry }: { onRetry: () => void }) {
  return (
    <div className="text-sm text-red-300 bg-red-950/30 border border-red-900 rounded-md p-3">
      Couldn't load. <button onClick={onRetry} className="underline hover:text-red-200">Retry</button>
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════
//  MetricWidget — scalar KPI card
// ══════════════════════════════════════════════════════════════════════════

export function MetricWidget({
  metric, title, goodDirection = 'up',
}: {
  metric: string;
  title: string;
  goodDirection?: 'up' | 'down' | 'neutral';
}) {
  const { data, isPending, error, refetch } = useMetric<ScalarResponse>(metric);

  if (isPending) return (
    <div className="bg-neutral-900/60 border border-neutral-800 rounded-lg p-3 h-full flex flex-col justify-center">
      <Skeleton className="h-3 w-20 mb-2" />
      <Skeleton className="h-6 w-32 mb-1" />
      <Skeleton className="h-3 w-16" />
    </div>
  );
  if (error) return (
    <div className="bg-neutral-900/60 border border-neutral-800 rounded-lg p-3 h-full flex flex-col justify-center">
      <ErrorState onRetry={() => refetch()} />
    </div>
  );

  const delta = formatDelta(data.value, data.previous);
  const isGood = goodDirection === 'neutral' ? false
    : goodDirection === 'up' ? delta.direction === 'up' : delta.direction === 'down';
  const isBad = goodDirection === 'neutral' ? false
    : goodDirection === 'up' ? delta.direction === 'down' : delta.direction === 'up';

  return (
    <div className="bg-neutral-900/60 border border-neutral-800 rounded-lg p-3 h-full flex flex-col justify-center">
      <div className="text-xs text-neutral-400 leading-tight">{title}</div>
      <div className="text-2xl font-medium text-neutral-100 mt-1 tabular-nums leading-tight">
        {formatValue(data.value, data.format)}
      </div>
      <div className={clsx(
        'text-xs mt-1 tabular-nums leading-tight',
        isGood && 'text-emerald-400',
        isBad  && 'text-red-400',
        !isGood && !isBad && 'text-neutral-500',
      )}>
        {delta.direction === 'up'   && '↑ '}
        {delta.direction === 'down' && '↓ '}
        {delta.text}
        {delta.pct != null && <span className="text-neutral-600"> vs prev</span>}
      </div>
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════
//  TimeseriesWidget — stacked area chart
// ══════════════════════════════════════════════════════════════════════════

export function TimeseriesWidget({
  metric, title, stacked = true,
}: {
  metric: string;
  title: string;
  stacked?: boolean;
}) {
  const { data, isPending, error, refetch } = useMetric<SeriesResponse>(metric);

  if (isPending) return (
    <Card><CardHeader title={title} /><Skeleton className="flex-1 min-h-[180px]" /></Card>
  );
  if (error) return <Card><CardHeader title={title} /><ErrorState onRetry={() => refetch()} /></Card>;

  const timestamps = data.series[0]?.points.map(p => p.t) ?? [];
  const rows = timestamps.map((t, i) => {
    const row: Record<string, string | number> = { t };
    for (const s of data.series) row[s.name] = s.points[i]?.v ?? 0;
    return row;
  });

  return (
    <Card>
      <CardHeader
        title={title}
        right={
          <div className="flex gap-3">
            {data.series.map((s, i) => (
              <span key={s.name} className="inline-flex items-center gap-1.5">
                <span className="w-2.5 h-2.5 rounded-sm" style={{ background: PALETTE[i] }} />
                <span className="text-neutral-400">{s.name}</span>
              </span>
            ))}
          </div>
        }
      />
      <div className="flex-1 min-h-[180px]">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={rows} margin={{ top: 4, right: 8, left: -12, bottom: 0 }}>
            <CartesianGrid stroke={GRID_COLOR} vertical={false} />
            <XAxis
              dataKey="t"
              tickFormatter={t => formatDate(parseISO(t as string), 'MMM d')}
              stroke={AXIS_TEXT}
              tick={{ fontSize: 11, fill: AXIS_TEXT }}
              tickLine={false}
              axisLine={false}
            />
            <YAxis
              stroke={AXIS_TEXT}
              tick={{ fontSize: 11, fill: AXIS_TEXT }}
              tickLine={false}
              axisLine={false}
              tickFormatter={v => formatValue(v as number, data.format, true)}
            />
            <Tooltip
              contentStyle={{
                fontSize: 12,
                background: TOOLTIP_BG,
                border: `1px solid ${TOOLTIP_BORDER}`,
                borderRadius: 6,
                color: '#e5e5e5',
              }}
              labelStyle={{ color: '#a3a3a3' }}
              labelFormatter={t => formatDate(parseISO(t as string), 'MMM d, yyyy')}
              formatter={(v: number) => formatValue(v, data.format)}
            />
            {data.series.map((s, i) => (
              <Area
                key={s.name}
                type="monotone"
                dataKey={s.name}
                stackId={stacked ? '1' : undefined}
                stroke={PALETTE[i]}
                fill={PALETTE[i]}
                fillOpacity={0.25}
                strokeWidth={1.5}
              />
            ))}
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </Card>
  );
}

// ══════════════════════════════════════════════════════════════════════════
//  DonutWidget — pie with legend
// ══════════════════════════════════════════════════════════════════════════

export function DonutWidget({ metric, title }: { metric: string; title: string }) {
  const { data, isPending, error, refetch } = useMetric<GroupResponse>(metric);

  if (isPending) return <Card><CardHeader title={title} /><Skeleton className="flex-1 min-h-[180px]" /></Card>;
  if (error) return <Card><CardHeader title={title} /><ErrorState onRetry={() => refetch()} /></Card>;

  const total = data.groups.reduce((s, g) => s + g.value, 0);
  const colorFor = (key: string, i: number) =>
    key === 'Other' ? OTHER_COLOR : PALETTE[i % PALETTE.length];

  return (
    <Card>
      <CardHeader title={title} />
      <div className="flex-1 flex items-center justify-center min-h-[140px]">
        <ResponsiveContainer width="100%" height={140}>
          <PieChart>
            <Pie
              data={data.groups}
              dataKey="value"
              nameKey="key"
              innerRadius={38}
              outerRadius={58}
              paddingAngle={1}
              stroke="none"
            >
              {data.groups.map((g, i) => (
                <Cell key={g.key} fill={colorFor(g.key, i)} />
              ))}
            </Pie>
            <Tooltip
              contentStyle={{
                fontSize: 12,
                background: TOOLTIP_BG,
                border: `1px solid ${TOOLTIP_BORDER}`,
                borderRadius: 6,
                color: '#e5e5e5',
              }}
              formatter={(v: number) => formatValue(v, data.format)}
            />
          </PieChart>
        </ResponsiveContainer>
      </div>
      <div className="text-xs flex flex-col gap-1 mt-2">
        {data.groups.map((g, i) => (
          <div key={g.key} className="flex items-center justify-between">
            <span className="flex items-center gap-2 text-neutral-300">
              <span className="w-2 h-2 rounded-sm" style={{ background: colorFor(g.key, i) }} />
              {g.key}
            </span>
            <span className="text-neutral-500 tabular-nums">
              {total > 0 ? `${((g.value / total) * 100).toFixed(0)}%` : '—'}
            </span>
          </div>
        ))}
      </div>
    </Card>
  );
}

// ══════════════════════════════════════════════════════════════════════════
//  BarWidget — horizontal bars
// ══════════════════════════════════════════════════════════════════════════

export function BarWidget({ metric, title }: { metric: string; title: string }) {
  const { data, isPending, error, refetch } = useMetric<GroupResponse>(metric);

  if (isPending) return <Card><CardHeader title={title} /><Skeleton className="flex-1 min-h-[180px]" /></Card>;
  if (error) return <Card><CardHeader title={title} /><ErrorState onRetry={() => refetch()} /></Card>;

  const max = Math.max(...data.groups.map(g => g.value), 1);
  const colorFor = (key: string, i: number) =>
    key === 'Other' ? OTHER_COLOR : PALETTE[i % PALETTE.length];

  return (
    <Card>
      <CardHeader title={title} />
      <div className="flex flex-col gap-2.5 text-xs">
        {data.groups.map((g, i) => {
          const pct = (g.value / max) * 100;
          return (
            <div key={g.key}>
              <div className="flex justify-between mb-1">
                <span className="text-neutral-200">{g.key}</span>
                <span className="text-neutral-500 tabular-nums">
                  {formatValue(g.value, data.format, true)}
                </span>
              </div>
              <div className="h-1.5 bg-neutral-800 rounded-sm overflow-hidden">
                <div className="h-full rounded-sm transition-all"
                     style={{ width: `${pct}%`, background: colorFor(g.key, i) }} />
              </div>
            </div>
          );
        })}
      </div>
    </Card>
  );
}

// ══════════════════════════════════════════════════════════════════════════
//  TableWidget — sortable, paginated
// ══════════════════════════════════════════════════════════════════════════

export function TableWidget({
  metric, title, sortableColumns,
}: {
  metric: string;
  title: string;
  sortableColumns?: string[];
}) {
  const [page, setPage] = useState(1);
  const [sort, setSort] = useState({ col: 'total_tokens', dir: 'desc' as 'asc' | 'desc' });

  const { data, isPending, error, refetch } = useMetric<TableResponse>(metric, {
    page, page_size: 15, sort: sort.col, sort_dir: sort.dir,
  });

  if (isPending) return <Card><CardHeader title={title} /><Skeleton className="min-h-[240px]" /></Card>;
  if (error) return <Card><CardHeader title={title} /><ErrorState onRetry={() => refetch()} /></Card>;

  const toggleSort = (col: string) => {
    if (!sortableColumns?.includes(col)) return;
    if (sort.col === col) setSort({ col, dir: sort.dir === 'asc' ? 'desc' : 'asc' });
    else setSort({ col, dir: 'desc' });
    setPage(1);
  };

  const pageEnd = Math.min(page * 15, data.total);
  const pageStart = data.total === 0 ? 0 : (page - 1) * 15 + 1;
  const totalPages = Math.max(1, Math.ceil(data.total / 15));

  return (
    <Card>
      <CardHeader
        title={title}
        right={<span>{pageStart.toLocaleString()}–{pageEnd.toLocaleString()} of {data.total.toLocaleString()}</span>}
      />
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-xs text-neutral-500 font-normal border-b border-neutral-800">
              {data.columns.map(col => {
                const isSortable = sortableColumns?.includes(col);
                const isActive = sort.col === col;
                const isNumeric = ['calls', 'total_tokens', 'avg_per_call'].includes(col);
                return (
                  <th
                    key={col}
                    onClick={() => toggleSort(col)}
                    className={clsx(
                      'py-2 px-3 font-normal',
                      isNumeric ? 'text-right' : 'text-left',
                      isSortable && 'cursor-pointer hover:text-neutral-300 select-none',
                    )}
                  >
                    {col.replaceAll('_', ' ')}
                    {isActive && <span className="ml-1 text-neutral-400">{sort.dir === 'asc' ? '↑' : '↓'}</span>}
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody className="tabular-nums">
            {data.rows.length === 0 && (
              <tr>
                <td colSpan={data.columns.length} className="py-8 text-center text-neutral-500">
                  No data matches these filters.
                </td>
              </tr>
            )}
            {data.rows.map((row, i) => (
              <tr key={i} className="border-b border-neutral-800/50 last:border-b-0 hover:bg-neutral-800/30">
                {data.columns.map(col => {
                  const isNumeric = ['calls', 'total_tokens', 'avg_per_call'].includes(col);
                  return (
                    <td
                      key={col}
                      className={clsx(
                        'py-2 px-3',
                        isNumeric ? 'text-right text-neutral-200' : 'text-neutral-300',
                      )}
                    >
                      {formatCell(row[col])}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {data.total > 15 && (
        <div className="flex justify-between items-center mt-3 text-xs text-neutral-500">
          <span>Page {page} of {totalPages.toLocaleString()}</span>
          <div className="flex gap-2">
            <button
              onClick={() => setPage(p => Math.max(1, p - 1))}
              disabled={page === 1}
              className="px-3 py-1 border border-neutral-800 rounded text-neutral-300 hover:bg-neutral-800/50 disabled:opacity-30 disabled:cursor-not-allowed"
            >
              Prev
            </button>
            <button
              onClick={() => setPage(p => (pageEnd < data.total ? p + 1 : p))}
              disabled={pageEnd >= data.total}
              className="px-3 py-1 border border-neutral-800 rounded text-neutral-300 hover:bg-neutral-800/50 disabled:opacity-30 disabled:cursor-not-allowed"
            >
              Next
            </button>
          </div>
        </div>
      )}
    </Card>
  );
}

function formatCell(v: unknown): string {
  if (v == null) return '—';
  if (typeof v === 'number') return v.toLocaleString();
  return String(v);
}

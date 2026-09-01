import { useState, type CSSProperties, type ReactNode } from 'react';
import {
  Area, AreaChart, CartesianGrid, Cell, Pie, PieChart,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts';
import { format as formatDate, parseISO } from 'date-fns';
import clsx from 'clsx';
import {
  Activity, Bug, Cpu, FlaskConical, HelpCircle, Layers, Link2, MessageSquare,
  Settings, Users, Wrench, Zap,
  type LucideIcon,
} from 'lucide-react';

import { formatDelta, formatValue, useMetric } from './api';
import type {
  ColumnConfig, GroupResponse, MatrixResponse, MatrixRow,
  ScalarResponse, SeriesResponse, TableResponse,
} from './types';

// ══════════════════════════════════════════════════════════════════════════
//  Dark-mode palette
// ══════════════════════════════════════════════════════════════════════════

const PALETTE = [
  '#818CF8', '#22D3EE', '#34D399', '#FBBF24',
  '#F472B6', '#F87171', '#A3E635', '#94A3B8',
];
const OTHER_COLOR   = '#525252';
const GRID_COLOR    = '#262626';
const AXIS_TEXT     = '#737373';
const TOOLTIP_BG    = '#171717';
const TOOLTIP_BORDER = '#404040';
// Recharts' <Tooltip> only themes its own box via `contentStyle` — the
// name/value line it renders per series (`itemStyle`) defaults to black
// regardless, which on this dark card is invisible unless set explicitly.
// Shared here so every chart's tooltip text is legible, not just the box.
const TOOLTIP_ITEM_STYLE = { color: '#e5e5e5' };

// Semantic colors for bug severity + status.
const SEVERITY_COLORS: Record<string, string> = {
  P1: '#F87171', P2: '#FBBF24', P3: '#818CF8', P4: '#FB923C',
  // The QA agent's named severity scale — same ramp, its own vocabulary.
  Blocker: '#F87171', Critical: '#FB923C', Major: '#FBBF24',
  Minor: '#818CF8', Trivial: '#737373',
};
const STATUS_COLORS: Record<string, string> = {
  open: '#FBBF24', in_progress: '#22D3EE', fixed: '#34D399', closed: '#94A3B8',
};
const PRIORITY_COLORS: Record<string, string> = {
  Core: '#F87171', High: '#FBBF24', Medium: '#818CF8', Low: '#FB923C',
};
function schemeColor(scheme: string | undefined, key: string, i: number): string {
  if (key === 'Other') return OTHER_COLOR;
  if (scheme === 'severity' && SEVERITY_COLORS[key]) return SEVERITY_COLORS[key];
  if (scheme === 'status'   && STATUS_COLORS[key])   return STATUS_COLORS[key];
  if (scheme === 'priority' && PRIORITY_COLORS[key]) return PRIORITY_COLORS[key];
  return PALETTE[i % PALETTE.length];
}

// Colored icon backgrounds for KPI cards.
const ICON_COLORS: Record<string, { bg: string; fg: string }> = {
  orange: { bg: 'bg-orange-500/15', fg: 'text-orange-400' },
  blue:   { bg: 'bg-blue-500/15',   fg: 'text-blue-400'   },
  green:  { bg: 'bg-emerald-500/15',fg: 'text-emerald-400'},
  purple: { bg: 'bg-purple-500/15', fg: 'text-purple-400' },
  cyan:   { bg: 'bg-cyan-500/15',   fg: 'text-cyan-400'   },
  amber:  { bg: 'bg-amber-500/15',  fg: 'text-amber-400'  },
};
const KPI_ICONS: Record<string, LucideIcon> = {
  link: Link2, cpu: Cpu, layers: Layers, activity: Activity, users: Users, zap: Zap,
};

// Feature → icon + color. Add to this map when new features arrive.
const FEATURE_META: Record<string, { icon: LucideIcon; color: string; label?: string }> = {
  'Chat':                { icon: MessageSquare, color: '#60A5FA' },
  'Bug Bot':             { icon: Bug,           color: '#F87171' },
  'Ask Anything':        { icon: HelpCircle,    color: '#34D399' },
  'Test Features':       { icon: Wrench,        color: '#9CA3AF' },
  'Test Case Gen':       { icon: FlaskConical,  color: '#34D399' },
  'Resource Allocation': { icon: Settings,      color: '#9CA3AF' },
  'Unknown':             { icon: HelpCircle,    color: '#6B7280' },
};
function featureMeta(name: string) {
  return FEATURE_META[name] ?? { icon: HelpCircle, color: '#6B7280' };
}

// Deterministic color for project code badges.
const CODE_COLORS = [
  { bg: 'bg-orange-500/15', fg: 'text-orange-400' },
  { bg: 'bg-blue-500/15',   fg: 'text-blue-400'   },
  { bg: 'bg-emerald-500/15',fg: 'text-emerald-400'},
  { bg: 'bg-purple-500/15', fg: 'text-purple-400' },
  { bg: 'bg-cyan-500/15',   fg: 'text-cyan-400'   },
  { bg: 'bg-pink-500/15',   fg: 'text-pink-400'   },
];
function codeColor(code: string) {
  let hash = 0;
  for (let i = 0; i < code.length; i++) hash = (hash * 31 + code.charCodeAt(i)) | 0;
  return CODE_COLORS[Math.abs(hash) % CODE_COLORS.length];
}

// ══════════════════════════════════════════════════════════════════════════
//  Shared building blocks
// ══════════════════════════════════════════════════════════════════════════

// Exported so the QA agent widgets in qa-widgets.tsx render inside the same
// shell as everything else — one card chrome, defined once.
export function Card({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div className={clsx(
      'bg-neutral-900 border border-neutral-800 rounded-xl p-4 h-full flex flex-col',
      className,
    )}>
      {children}
    </div>
  );
}

export function CardHeader({ title, right, icon }: { title: string; right?: ReactNode; icon?: LucideIcon }) {
  const Icon = icon;
  return (
    <div className="flex items-center justify-between mb-3">
      <div className="flex items-center gap-2">
        {Icon && <Icon size={14} className="text-neutral-500" strokeWidth={2} />}
        <h3 className="text-sm font-medium text-neutral-200">{title}</h3>
      </div>
      {right && <div className="text-xs text-neutral-400">{right}</div>}
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={clsx('bg-neutral-800/60 rounded animate-pulse', className)} />;
}

export function ErrorState({ onRetry }: { onRetry: () => void }) {
  return (
    <div className="text-sm text-red-300 bg-red-950/30 border border-red-900 rounded-md p-3">
      Couldn't load. <button onClick={onRetry} className="underline hover:text-red-200">Retry</button>
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════
//  MetricWidget — KPI card with colored icon + subtitle
// ══════════════════════════════════════════════════════════════════════════

export function MetricWidget({
  metric, title, subtitle, icon, iconColor = 'blue', goodDirection = 'neutral',
}: {
  metric: string;
  title: string;
  subtitle?: string;
  icon?: 'link' | 'cpu' | 'layers' | 'activity' | 'users' | 'zap';
  iconColor?: 'orange' | 'blue' | 'green' | 'purple' | 'cyan' | 'amber';
  goodDirection?: 'up' | 'down' | 'neutral';
}) {
  const { data, isPending, error, refetch } = useMetric<ScalarResponse>(metric);
  const Icon = icon ? KPI_ICONS[icon] : undefined;
  const colors = ICON_COLORS[iconColor];

  const CardWrap = ({ children }: { children: ReactNode }) => (
    <div className="bg-neutral-900 border border-neutral-800 rounded-xl p-4 h-full flex flex-col">
      {children}
    </div>
  );

  if (isPending) return (
    <CardWrap>
      <Skeleton className="h-3 w-24 mb-3" />
      <Skeleton className="h-8 w-32 mb-2" />
      <Skeleton className="h-3 w-40" />
    </CardWrap>
  );
  if (error) return <CardWrap><ErrorState onRetry={() => refetch()} /></CardWrap>;

  const delta = formatDelta(data.value, data.previous);
  const isGood = goodDirection === 'neutral' ? false
    : goodDirection === 'up' ? delta.direction === 'up' : delta.direction === 'down';
  const isBad = goodDirection === 'neutral' ? false
    : goodDirection === 'up' ? delta.direction === 'down' : delta.direction === 'up';

  return (
    <CardWrap>
      <div className="flex items-start justify-between mb-1">
        <div className="text-[11px] font-medium uppercase tracking-wider text-neutral-500">
          {title}
        </div>
        {Icon && (
          <div className={clsx('w-7 h-7 rounded-md flex items-center justify-center', colors.bg)}>
            <Icon size={14} className={colors.fg} strokeWidth={2.5} />
          </div>
        )}
      </div>
      <div className="text-3xl font-semibold text-neutral-100 mt-1 tabular-nums leading-tight">
        {formatValue(data.value, data.format)}
      </div>
      <div className="mt-auto pt-2 flex items-center justify-between">
        {subtitle && (
          <div className="text-xs text-neutral-500">{subtitle}</div>
        )}
        {delta.pct != null && (
          <div className={clsx(
            'text-xs tabular-nums shrink-0 ml-2',
            isGood && 'text-emerald-400',
            isBad  && 'text-red-400',
            !isGood && !isBad && 'text-neutral-500',
          )}>
            {delta.direction === 'up'   ? '↑ ' : delta.direction === 'down' ? '↓ ' : ''}
            {delta.text}
          </div>
        )}
      </div>
    </CardWrap>
  );
}

// ══════════════════════════════════════════════════════════════════════════
//  TimeseriesWidget
// ══════════════════════════════════════════════════════════════════════════

export function TimeseriesWidget({
  metric, title, stacked = true,
}: {
  metric: string;
  title: string;
  stacked?: boolean;
}) {
  const { data, isPending, error, refetch } = useMetric<SeriesResponse>(metric);

  if (isPending) return <Card><CardHeader title={title} icon={Activity} /><Skeleton className="flex-1 min-h-[200px]" /></Card>;
  if (error) return <Card><CardHeader title={title} icon={Activity} /><ErrorState onRetry={() => refetch()} /></Card>;

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
        icon={Activity}
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
      <div className="flex-1 min-h-[200px]">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={rows} margin={{ top: 4, right: 8, left: -12, bottom: 0 }}>
            <CartesianGrid stroke={GRID_COLOR} vertical={false} />
            <XAxis
              dataKey="t"
              tickFormatter={t => formatDate(parseISO(t as string), 'MMM d')}
              stroke={AXIS_TEXT} tick={{ fontSize: 11, fill: AXIS_TEXT }}
              tickLine={false} axisLine={false}
            />
            <YAxis
              stroke={AXIS_TEXT} tick={{ fontSize: 11, fill: AXIS_TEXT }}
              tickLine={false} axisLine={false}
              tickFormatter={v => formatValue(v as number, data.format, true)}
            />
            <Tooltip
              contentStyle={{
                fontSize: 12, background: TOOLTIP_BG,
                border: `1px solid ${TOOLTIP_BORDER}`, borderRadius: 6, color: '#e5e5e5',
              }}
              labelStyle={{ color: '#a3a3a3' }}
              itemStyle={TOOLTIP_ITEM_STYLE}
              labelFormatter={t => formatDate(parseISO(t as string), 'MMM d, yyyy')}
              formatter={(v: number) => formatValue(v, data.format)}
            />
            {data.series.map((s, i) => (
              <Area
                key={s.name} type="monotone" dataKey={s.name}
                stackId={stacked ? '1' : undefined}
                stroke={PALETTE[i]} fill={PALETTE[i]}
                fillOpacity={0.25} strokeWidth={1.5}
              />
            ))}
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </Card>
  );
}

// ══════════════════════════════════════════════════════════════════════════
//  DonutWidget + BarWidget — kept for use if you want them later
// ══════════════════════════════════════════════════════════════════════════

export function DonutWidget({ metric, title, colorScheme }: { metric: string; title: string; colorScheme?: string }) {
  const { data, isPending, error, refetch } = useMetric<GroupResponse>(metric);
  if (isPending) return <Card><CardHeader title={title} /><Skeleton className="flex-1 min-h-[180px]" /></Card>;
  if (error) return <Card><CardHeader title={title} /><ErrorState onRetry={() => refetch()} /></Card>;

  const total = data.groups.reduce((s, g) => s + g.value, 0);
  const colorFor = (key: string, i: number) => schemeColor(colorScheme, key, i);

  return (
    <Card>
      <CardHeader title={title} />
      <div className="flex-1 flex items-center justify-center min-h-[140px]">
        <ResponsiveContainer width="100%" height={140}>
          <PieChart>
            <Pie data={data.groups} dataKey="value" nameKey="key" innerRadius={38} outerRadius={58} paddingAngle={1} stroke="none">
              {data.groups.map((g, i) => <Cell key={g.key} fill={colorFor(g.key, i)} />)}
            </Pie>
            <Tooltip
              contentStyle={{ fontSize: 12, background: TOOLTIP_BG, border: `1px solid ${TOOLTIP_BORDER}`, borderRadius: 6, color: '#e5e5e5' }}
              itemStyle={TOOLTIP_ITEM_STYLE}
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

export function BarWidget({ metric, title, colorScheme, highlightZero }: { metric: string; title: string; colorScheme?: string; highlightZero?: boolean }) {
  const { data, isPending, error, refetch } = useMetric<GroupResponse>(metric);
  if (isPending) return <Card><CardHeader title={title} /><Skeleton className="flex-1 min-h-[180px]" /></Card>;
  if (error) return <Card><CardHeader title={title} /><ErrorState onRetry={() => refetch()} /></Card>;

  const max = Math.max(...data.groups.map(g => g.value), 1);
  const colorFor = (key: string, i: number) => {
    if (highlightZero && key === '0') return '#F87171';   // red for the 0-step warning bar
    return schemeColor(colorScheme, key, i);
  };

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
                <span className="text-neutral-500 tabular-nums">{formatValue(g.value, data.format, true)}</span>
              </div>
              <div className="h-1.5 bg-neutral-800 rounded-sm overflow-hidden">
                <div className="h-full rounded-sm" style={{ width: `${pct}%`, background: colorFor(g.key, i) }} />
              </div>
            </div>
          );
        })}
      </div>
    </Card>
  );
}

// ══════════════════════════════════════════════════════════════════════════
//  GaugeWidget — a single percentage as a radial gauge
// ══════════════════════════════════════════════════════════════════════════

export function GaugeWidget({
  metric, title, badge, unit = 'FIX RATE',
}: {
  metric: string;
  title: string;
  badge?: string;
  unit?: string;
}) {
  const { data, isPending, error, refetch } = useMetric<ScalarResponse>(metric);

  if (isPending) return <Card><CardHeader title={title} /><Skeleton className="flex-1 min-h-[180px]" /></Card>;
  if (error) return <Card><CardHeader title={title} /><ErrorState onRetry={() => refetch()} /></Card>;

  const pct = Math.max(0, Math.min(100, data.value));   // value is 0-100
  const radius = 70;
  const stroke = 12;
  const circumference = 2 * Math.PI * radius;
  const arc = 0.75;                                       // 3/4 circle
  const dash = circumference * arc;
  const filled = dash * (pct / 100);

  // Color ramp: red < 40, amber < 70, green ≥ 70
  const color = pct >= 70 ? '#34D399' : pct >= 40 ? '#FBBF24' : '#F87171';

  return (
    <Card>
      <CardHeader
        title={title}
        right={badge ? (
          <span className="px-2 py-0.5 text-[10px] font-semibold rounded bg-emerald-500/15 text-emerald-400 uppercase tracking-wide">
            {badge}
          </span>
        ) : null}
      />
      <div className="flex-1 flex items-center justify-center min-h-[180px]">
        <svg viewBox="0 0 180 180" className="w-44 h-44">
          <circle
            cx="90" cy="90" r={radius} fill="none"
            stroke={GRID_COLOR} strokeWidth={stroke}
            strokeDasharray={`${dash} ${circumference}`}
            strokeLinecap="round"
            transform="rotate(135 90 90)"
          />
          <circle
            cx="90" cy="90" r={radius} fill="none"
            stroke={color} strokeWidth={stroke}
            strokeDasharray={`${filled} ${circumference}`}
            strokeLinecap="round"
            transform="rotate(135 90 90)"
            style={{ transition: 'stroke-dasharray 0.5s ease' }}
          />
          <text x="90" y="86" textAnchor="middle" className="fill-neutral-100"
                style={{ fontSize: 26, fontWeight: 600 }}>
            {pct.toFixed(1)}%
          </text>
          <text x="90" y="106" textAnchor="middle" className="fill-neutral-500"
                style={{ fontSize: 10, letterSpacing: 1 }}>
            {unit}
          </text>
        </svg>
      </div>
    </Card>
  );
}



// ══════════════════════════════════════════════════════════════════════════
//  HeatmapWidget — feature × priority grid, off-tier cells flagged as drift
// ══════════════════════════════════════════════════════════════════════════

export function HeatmapWidget({ metric, title, note }: { metric: string; title: string; note?: string }) {
  const { data, isPending, error, refetch } = useMetric<MatrixResponse>(metric);

  if (isPending) return <Card><CardHeader title={title} /><Skeleton className="flex-1 min-h-[200px]" /></Card>;
  if (error) return <Card><CardHeader title={title} /><ErrorState onRetry={() => refetch()} /></Card>;

  // Scale intensity per-column so each priority's cells are compared to their own
  // max — otherwise one dominant column flattens every other cell to invisibility.
  const colMax: Record<string, number> = {};
  for (const col of data.columns) {
    colMax[col] = Math.max(1, ...data.rows.map(r => r.cells[col] ?? 0));
  }

  // Perceptual curve: sqrt lifts mid/low values so they're distinguishable
  // instead of all collapsing to near-zero opacity.
  const intensityOf = (val: number, col: string) => {
    if (val <= 0) return 0;
    return Math.sqrt(val / colMax[col]);   // 0..1, curved
  };

  const cellStyle = (row: MatrixRow, col: string): CSSProperties => {
    const val = row.cells[col] ?? 0;
    const isAssignedTier = row.assigned === col;

    if (val === 0) {
      // Empty: barely-there recessed tile, clearly distinct from any real value.
      return { background: 'rgba(255,255,255,0.015)', color: 'transparent' };
    }
    const t = intensityOf(val, col);
    if (!isAssignedTier) {
      // Drift — red family. Floor at 0.28 so even 1 case is clearly visible.
      const alpha = 0.28 + t * 0.55;
      return {
        background: `rgba(248, 113, 113, ${alpha})`,
        color: t > 0.45 ? '#1a0a0a' : '#fecaca',
        fontWeight: 600,
      };
    }
    // On-tier — indigo family.
    const alpha = 0.22 + t * 0.62;
    return {
      background: `rgba(129, 140, 248, ${alpha})`,
      color: t > 0.5 ? '#0a0a1a' : '#e0e7ff',
      fontWeight: 600,
    };
  };

  const colWidth = `${72 / data.columns.length}%`;

  return (
    <Card>
      <CardHeader title={title} right={note ? <span className="text-neutral-500">{note}</span> : null} />
      <div className="overflow-x-auto flex-1">
        <div className="min-w-[560px]">
          {/* Header row */}
          <div className="flex items-center mb-1.5">
            <div className="w-[28%] shrink-0 text-[10px] uppercase tracking-wider text-neutral-500 pl-1">Feature</div>
            <div className="flex-1 flex gap-1.5">
              {data.columns.map(col => (
                <div key={col} className="flex-1 text-center text-[11px] font-semibold"
                     style={{ color: PRIORITY_COLORS[col] ?? '#a3a3a3' }}>
                  {col}
                </div>
              ))}
            </div>
            <div className="w-[52px] shrink-0 text-right text-[10px] uppercase tracking-wider text-neutral-500">Total</div>
          </div>

          {/* Tile rows */}
          <div className="flex flex-col gap-1.5">
            {data.rows.map(row => (
              <div key={row.feature} className="flex items-center">
                <div className="w-[28%] shrink-0 pr-2 truncate text-xs text-neutral-300">
                  <span className="inline-flex items-center gap-1.5">
                    <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ background: PRIORITY_COLORS[row.assigned] ?? '#6b7280' }} />
                    <span className="truncate">{row.feature}</span>
                  </span>
                </div>
                <div className="flex-1 flex gap-1.5">
                  {data.columns.map(col => {
                    const val = row.cells[col] ?? 0;
                    const isDrift = val > 0 && row.assigned !== col;
                    return (
                      <div
                        key={col}
                        title={`${row.feature} · ${col}: ${val}${isDrift ? ' (drift)' : ''}`}
                        className="flex-1 h-8 rounded-md flex items-center justify-center text-xs tabular-nums transition-transform hover:scale-[1.04] hover:ring-1 hover:ring-white/20 cursor-default"
                        style={cellStyle(row, col)}
                      >
                        {val > 0 ? val : ''}
                      </div>
                    );
                  })}
                </div>
                <div className="w-[52px] shrink-0 text-right text-xs tabular-nums text-neutral-200 font-medium">{row.total}</div>
              </div>
            ))}
          </div>
        </div>
      </div>
      <div className="mt-3 flex items-center gap-4 text-[10px] text-neutral-500">
        <span className="inline-flex items-center gap-1.5">
          <span className="flex gap-0.5">
            <span className="w-3 h-3 rounded-sm" style={{ background: 'rgba(129,140,248,0.3)' }} />
            <span className="w-3 h-3 rounded-sm" style={{ background: 'rgba(129,140,248,0.85)' }} />
          </span>
          on assigned tier (low → high)
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="w-3 h-3 rounded-sm" style={{ background: 'rgba(248,113,113,0.6)' }} /> priority drift
        </span>
      </div>
    </Card>
  );
}



const NUMERIC_COLS = new Set([
  'requests', 'prompt_tokens', 'completion_tokens', 'total_tokens', 'calls', 'avg_per_call',
  'count', 'reported', 'closed', 'total', 'unresolved', 'p1_open',
  'open', 'in_progress', 'fixed',
  'cases', 'core', 'schema_fails', 'drift', 'avg_steps', 'features', 'copies',
]);

function defaultColumnConfig(col: string): ColumnConfig {
  if (col === 'total_tokens') return { format: 'bold-number', align: 'right' };
  if (NUMERIC_COLS.has(col))  return { format: 'number',      align: 'right' };
  if (col === 'timestamp' || col === 'created_at') return { format: 'timestamp', align: 'left' };
  if (col === 'feature')      return { format: 'feature-icon', align: 'left' };
  if (col === 'severity')     return { format: 'severity-badge', align: 'left' };
  if (col === 'status')       return { format: 'status-badge', align: 'left' };
  if (col === 'project_code' || col === 'code') return { format: 'badge', align: 'left' };
  if (col === 'user_email' || col === 'email')  return { format: 'muted', align: 'left' };
  if (col === 'age_days')     return { format: 'age', align: 'right' };
  if (col === 'pct' || col === 'close_rate')    return { format: 'percent-cell', align: 'right' };
  if (col === 'priority' || col === 'assigned_priority') return { format: 'priority-pill', align: 'left' };
  if (col === 'test_type')    return { format: 'test-type', align: 'left' };
  if (col === 'drifted')      return { format: 'drift-dot', align: 'center' };
  if (col === 'schema_ok')    return { format: 'bool-check', align: 'center' };
  if (col === 'step_count')   return { format: 'step-count', align: 'right' };
  if (col === 'coverage_level') return { format: 'text', align: 'left' };
  return { format: 'text', align: 'left' };
}

function humanizeColumnName(col: string): string {
  return col.replaceAll('_', ' ');
}

function renderCell(col: string, value: unknown, cfg: ColumnConfig): ReactNode {
  if (value == null || value === '') return <span className="text-neutral-600">—</span>;

  switch (cfg.format) {
    case 'timestamp': {
      const d = typeof value === 'string' ? parseISO(value) : new Date(value as string);
      return <span className="text-neutral-400 tabular-nums text-xs">{formatDate(d, 'MM/dd/yyyy, HH:mm:ss')}</span>;
    }
    case 'feature-icon': {
      const meta = featureMeta(String(value));
      const Icon = meta.icon;
      return (
        <span className="inline-flex items-center gap-2">
          <Icon size={14} style={{ color: meta.color }} strokeWidth={2} />
          <span className="text-neutral-200">{String(value)}</span>
        </span>
      );
    }
    case 'badge': {
      const code = String(value);
      const c = codeColor(code);
      return (
        <span className={clsx('inline-block px-2 py-0.5 text-[10px] font-semibold rounded uppercase tracking-wide', c.bg, c.fg)}>
          {code}
        </span>
      );
    }
    case 'muted':
      return <span className="text-neutral-500">{String(value)}</span>;
    case 'severity-badge': {
      const sev = String(value);
      // P1-P4 (the bug_reports dashboard's own scale) and the QA agent's
      // named severities share one map — both rank worst-to-least-bad, so
      // the same red-to-neutral ramp reads correctly for either vocabulary.
      const styles: Record<string, string> = {
        P1: 'bg-red-500/15 text-red-400',
        P2: 'bg-amber-500/15 text-amber-400',
        P3: 'bg-indigo-500/15 text-indigo-400',
        P4: 'bg-orange-500/15 text-orange-400',
        Blocker:  'bg-red-500/15 text-red-400',
        Critical: 'bg-orange-500/15 text-orange-400',
        Major:    'bg-amber-500/15 text-amber-400',
        Minor:    'bg-indigo-500/15 text-indigo-400',
        Trivial:  'bg-neutral-600/30 text-neutral-400',
      };
      return (
        <span className={clsx('inline-block px-2 py-0.5 text-[10px] font-semibold rounded', styles[sev] ?? 'bg-neutral-700 text-neutral-300')}>
          {sev}
        </span>
      );
    }
    case 'status-badge': {
      const raw = String(value);
      // Normalized once so every dashboard's spelling lands on one key —
      // token/bug_reports write 'in_progress', the QA agent writes
      // 'In Progress'. Without this the QA statuses (title case, spaces)
      // matched nothing here and every badge fell through to the same grey
      // default, which is why Closed/QA Ready/In Progress all looked identical.
      const key = raw.toLowerCase().replace(/[\s-]+/g, '_');
      const styles: Record<string, string> = {
        open:         'bg-amber-500/15 text-amber-400',
        in_progress:  'bg-cyan-500/15 text-cyan-400',
        qa_ready:     'bg-violet-500/15 text-violet-400',
        fixed:        'bg-emerald-500/15 text-emerald-400',
        closed:       'bg-neutral-600/30 text-neutral-400',
        deferred:     'bg-neutral-600/30 text-neutral-500',
        unknown:      'bg-neutral-700/40 text-neutral-400',
        success:      'bg-emerald-500/15 text-emerald-400',
        partial:      'bg-amber-500/15 text-amber-400',
        failed:       'bg-red-500/15 text-red-400',
        pass:         'bg-emerald-500/15 text-emerald-400',
        fail:         'bg-red-500/15 text-red-400',
        some_issue:   'bg-amber-500/15 text-amber-400',
        blocked:      'bg-pink-500/15 text-pink-400',
        not_run:      'bg-neutral-700/40 text-neutral-400',
      };
      const dot: Record<string, string> = {
        open: 'bg-amber-400', in_progress: 'bg-cyan-400', qa_ready: 'bg-violet-400',
        fixed: 'bg-emerald-400', closed: 'bg-neutral-400', deferred: 'bg-neutral-500',
        unknown: 'bg-neutral-500',
        success: 'bg-emerald-400', partial: 'bg-amber-400', failed: 'bg-red-400',
        pass: 'bg-emerald-400', fail: 'bg-red-400', some_issue: 'bg-amber-400',
        blocked: 'bg-pink-400', not_run: 'bg-neutral-500',
      };
      return (
        <span className={clsx('inline-flex items-center gap-1.5 px-2 py-0.5 text-[10px] font-medium rounded', styles[key] ?? 'bg-neutral-700 text-neutral-300')}>
          <span className={clsx('w-1.5 h-1.5 rounded-full', dot[key] ?? 'bg-neutral-400')} />
          {raw}
        </span>
      );
    }
    case 'age': {
      const days = typeof value === 'number' ? value : parseFloat(String(value));
      const label = days < 1 ? `${Math.round(days * 24)}h` : `${days.toFixed(1)}d`;
      const color = days > 30 ? 'text-red-400' : days > 7 ? 'text-amber-400' : 'text-neutral-400';
      return <span className={clsx('tabular-nums', color)}>{label}</span>;
    }
    case 'percent-cell':
      return <span className="text-neutral-400 tabular-nums">{typeof value === 'number' ? `${value}%` : String(value)}</span>;
    case 'priority-pill': {
      const prio = String(value);
      const colors: Record<string, string> = {
        Core: 'bg-red-500/15 text-red-400',
        High: 'bg-amber-500/15 text-amber-400',
        Medium: 'bg-indigo-500/15 text-indigo-400',
        Low: 'bg-orange-500/15 text-orange-400',
      };
      return (
        <span className={clsx('inline-block px-2 py-0.5 text-[10px] font-semibold rounded', colors[prio] ?? 'bg-neutral-700 text-neutral-300')}>
          {prio}
        </span>
      );
    }
    case 'test-type': {
      const tt = String(value).replace('_', ' ');
      const colors: Record<string, string> = {
        'happy path': 'text-emerald-400',
        'negative': 'text-amber-400',
        'boundary': 'text-indigo-400',
        'error handling': 'text-red-400',
      };
      return <span className={clsx('text-xs', colors[tt] ?? 'text-neutral-400')}>{tt}</span>;
    }
    case 'drift-dot':
      return value === true
        ? <span title="priority drift" className="inline-block w-2 h-2 rounded-full bg-red-400" />
        : <span className="text-neutral-700">·</span>;
    case 'bool-check':
      return value === true
        ? <span className="text-emerald-400 text-xs">✓</span>
        : <span title="schema incomplete" className="text-red-400 text-xs">✕</span>;
    case 'step-count': {
      const n = typeof value === 'number' ? value : parseInt(String(value), 10);
      if (n === 0) return <span title="no steps — likely a parse failure" className="text-red-400 font-semibold tabular-nums">0</span>;
      return <span className="text-neutral-300 tabular-nums">{n}</span>;
    }
    case 'number':
      return <span className="text-neutral-300 tabular-nums">{typeof value === 'number' ? value.toLocaleString() : String(value)}</span>;
    case 'bold-number':
      return <span className="text-neutral-100 font-semibold tabular-nums">{typeof value === 'number' ? value.toLocaleString() : String(value)}</span>;
    default:
      return <span className="text-neutral-200">{String(value)}</span>;
  }
}

export function TableWidget({
  metric, title, sortableColumns, columnConfig, pageSize, compact, refetchMs,
}: {
  metric: string;
  title: string;
  sortableColumns?: string[];
  columnConfig?: Record<string, ColumnConfig>;
  pageSize?: number;
  compact?: boolean;
  refetchMs?: number;
}) {
  const effectivePageSize = pageSize ?? 15;
  const [page, setPage] = useState(1);
  const [sort, setSort] = useState({ col: 'total_tokens', dir: 'desc' as 'asc' | 'desc' });

  const extraParams = compact
    ? {}
    : { page, page_size: effectivePageSize, sort: sort.col, sort_dir: sort.dir };

  const { data, isPending, error, refetch } = useMetric<TableResponse>(metric, extraParams, {
    refetchInterval: refetchMs,
  });

  if (isPending) return <Card><CardHeader title={title} /><Skeleton className="min-h-[200px]" /></Card>;
  if (error) return <Card><CardHeader title={title} /><ErrorState onRetry={() => refetch()} /></Card>;

  const columns = data.columns;
  const configs: Record<string, ColumnConfig> = {};
  for (const col of columns) {
    configs[col] = { ...defaultColumnConfig(col), ...(columnConfig?.[col] ?? {}) };
  }

  const toggleSort = (col: string) => {
    if (!sortableColumns?.includes(col)) return;
    if (sort.col === col) setSort({ col, dir: sort.dir === 'asc' ? 'desc' : 'asc' });
    else setSort({ col, dir: 'desc' });
    setPage(1);
  };

  const pageEnd = Math.min(page * effectivePageSize, data.total);
  const pageStart = data.total === 0 ? 0 : (page - 1) * effectivePageSize + 1;
  const totalPages = Math.max(1, Math.ceil(data.total / effectivePageSize));
  const showPagination = !compact && data.total > effectivePageSize;

  return (
    <Card>
      <CardHeader
        title={title}
        right={
          !compact && data.total > 0 ? (
            <span>{pageStart.toLocaleString()}–{pageEnd.toLocaleString()} of {data.total.toLocaleString()}</span>
          ) : null
        }
      />
      <div className="overflow-x-auto flex-1">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-[10px] uppercase tracking-wider text-neutral-500 font-medium border-b border-neutral-800">
              {columns.map(col => {
                const isSortable = sortableColumns?.includes(col);
                const isActive = sort.col === col;
                const cfg = configs[col];
                return (
                  <th
                    key={col}
                    onClick={() => toggleSort(col)}
                    className={clsx(
                      'py-2 px-3 font-medium',
                      cfg.align === 'right' ? 'text-right' : 'text-left',
                      isSortable && 'cursor-pointer hover:text-neutral-300 select-none',
                    )}
                  >
                    {cfg.label ?? humanizeColumnName(col)}
                    {isActive && <span className="ml-1 text-neutral-400">{sort.dir === 'asc' ? '↑' : '↓'}</span>}
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {data.rows.length === 0 && (
              <tr>
                <td colSpan={columns.length} className="py-8 text-center text-neutral-500">
                  No data matches these filters.
                </td>
              </tr>
            )}
            {data.rows.map((row, i) => (
              <tr key={i} className="border-b border-neutral-800/50 last:border-b-0 hover:bg-neutral-800/30">
                {columns.map(col => {
                  const cfg = configs[col];
                  return (
                    <td key={col} className={clsx('py-2.5 px-3', cfg.align === 'right' ? 'text-right' : 'text-left')}>
                      {renderCell(col, row[col], cfg)}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {showPagination && (
        <div className="flex justify-between items-center mt-3 text-xs text-neutral-500 border-t border-neutral-800/50 pt-3">
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

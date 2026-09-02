import { useState, type ReactNode } from 'react';
import {
  Area, AreaChart, CartesianGrid, Cell, Legend, Line, LineChart, Pie, PieChart,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts';
import { format as formatDate, parseISO } from 'date-fns';
import clsx from 'clsx';
import {
  Activity, AlertCircle, AlertTriangle, ArrowLeft, ArrowUpRight, BarChart3,
  Bug, Calendar, CheckCircle2, ChevronRight, Clock, Cpu, FileText,
  FlaskConical, FolderGit2, HelpCircle, Layers, Link2, MessageSquare,
  Milestone, Settings, ShieldAlert, Sparkles, TrendingDown, TrendingUp,
  Users, Wrench, Zap,
  type LucideIcon,
} from 'lucide-react';

import { formatDelta, formatValue, useMetric } from './api';
import { useFilterActions } from './filters';
import type {
  ColumnConfig, GroupResponse, ScalarResponse, SeriesResponse, TableResponse,
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

// Semantic colors for status.
const SEVERITY_COLORS: Record<string, string> = {
  P1: '#F87171', P2: '#FBBF24', P3: '#818CF8', P4: '#FB923C',
};
const STATUS_COLORS: Record<string, string> = {
  open: '#FBBF24', in_progress: '#22D3EE', fixed: '#34D399', closed: '#94A3B8',
  'On Track': '#34D399', 'At Risk': '#FBBF24', 'Delayed': '#F87171',
  on_track: '#34D399', at_risk: '#FBBF24', delayed: '#F87171',
};
function schemeColor(scheme: string | undefined, key: string, i: number): string {
  if (key === 'Other') return OTHER_COLOR;
  if (scheme === 'severity' && SEVERITY_COLORS[key]) return SEVERITY_COLORS[key];
  if (scheme === 'status'   && STATUS_COLORS[key])   return STATUS_COLORS[key];
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

// Feature metadata
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

function CardHeader({ title, right, icon }: { title: string; right?: ReactNode; icon?: LucideIcon }) {
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

  const seriesList = data?.series ?? [];
  const timestamps = seriesList[0]?.points?.map(p => p.t) ?? [];
  const rows = timestamps.map((t, i) => {
    const row: Record<string, string | number> = { t };
    for (const s of seriesList) row[s.name] = s.points?.[i]?.v ?? 0;
    return row;
  });

  return (
    <Card>
      <CardHeader
        title={title}
        icon={Activity}
        right={
          <div className="flex gap-3">
            {seriesList.map((s, i) => (
              <span key={s.name} className="inline-flex items-center gap-1.5">
                <span className="w-2.5 h-2.5 rounded-sm" style={{ background: PALETTE[i % PALETTE.length] }} />
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
//  DonutWidget + BarWidget
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

export function BarWidget({ metric, title, colorScheme }: { metric: string; title: string; colorScheme?: string }) {
  const { data, isPending, error, refetch } = useMetric<GroupResponse>(metric);
  if (isPending) return <Card><CardHeader title={title} /><Skeleton className="flex-1 min-h-[180px]" /></Card>;
  if (error) return <Card><CardHeader title={title} /><ErrorState onRetry={() => refetch()} /></Card>;

  const max = Math.max(...data.groups.map(g => g.value), 1);
  const colorFor = (key: string, i: number) => schemeColor(colorScheme, key, i);

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

  const pct = Math.max(0, Math.min(100, data.value));
  const radius = 70;
  const stroke = 12;
  const circumference = 2 * Math.PI * radius;
  const arc = 0.75;
  const dash = circumference * arc;
  const filled = dash * (pct / 100);

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

export function FunnelWidget({ metric, title }: { metric: string; title: string }) {
  const { data, isPending, error, refetch } = useMetric<GroupResponse>(metric);
  if (isPending) return <Card><CardHeader title={title} /><Skeleton className="flex-1 min-h-[180px]" /></Card>;
  if (error) return <Card><CardHeader title={title} /><ErrorState onRetry={() => refetch()} /></Card>;

  const maxVal = data.groups[0]?.value || 1;

  return (
    <Card>
      <CardHeader title={title} icon={Activity} />
      <div className="flex-1 flex flex-col justify-center gap-3 my-auto">
        {data.groups.map((step, i) => {
          const pct = Math.round((step.value / maxVal) * 100);
          const prevVal = i > 0 ? data.groups[i - 1].value : step.value;
          const convRate = prevVal > 0 ? Math.round((step.value / prevVal) * 100) : 100;
          
          return (
            <div key={step.key} className="flex flex-col gap-1">
              <div className="flex items-center justify-between text-xs">
                <span className="flex items-center gap-2 font-medium text-neutral-200">
                  <span className="w-5 h-5 rounded-full bg-indigo-500/20 text-indigo-400 flex items-center justify-center text-[10px] font-bold border border-indigo-500/30">
                    {i + 1}
                  </span>
                  {step.key}
                </span>
                <div className="flex items-center gap-3">
                  <span className="text-neutral-400 text-[11px] tabular-nums">
                    {i > 0 && <span className="text-emerald-400 font-semibold mr-1.5">{convRate}% step conv</span>}
                    ({step.value.toLocaleString()})
                  </span>
                </div>
              </div>
              <div className="h-2.5 bg-neutral-800 rounded-full overflow-hidden p-0.5 border border-neutral-800">
                <div 
                  className="h-full rounded-full transition-all duration-500" 
                  style={{ 
                    width: `${Math.max(4, pct)}%`, 
                    background: `linear-gradient(90deg, ${PALETTE[i % PALETTE.length]}, ${PALETTE[(i + 1) % PALETTE.length]})`
                  }} 
                />
              </div>
            </div>
          );
        })}
      </div>
    </Card>
  );
}

export function SpeedDialWidget({ metric, title, unit = 'sec' }: { metric: string; title: string; unit?: string }) {
  const { data, isPending, error, refetch } = useMetric<ScalarResponse>(metric);
  if (isPending) return <Card><CardHeader title={title} /><Skeleton className="flex-1 min-h-[180px]" /></Card>;
  if (error) return <Card><CardHeader title={title} /><ErrorState onRetry={() => refetch()} /></Card>;

  const val = data.value;
  const pct = Math.min(100, Math.max(0, (val / 10) * 100));
  const statusLabel = val < 3.5 ? '⚡ ULTRA FAST' : val < 6.0 ? '⏱️ MODERATE' : '🐢 HEAVY';
  const statusColor = val < 3.5 ? 'text-emerald-400' : val < 6.0 ? 'text-amber-400' : 'text-red-400';

  return (
    <Card>
      <CardHeader title={title} icon={Cpu} right={<span className={clsx("text-[10px] font-bold uppercase tracking-wider", statusColor)}>{statusLabel}</span>} />
      <div className="flex-1 flex flex-col items-center justify-center min-h-[160px]">
        <div className="relative flex items-center justify-center">
          <svg viewBox="0 0 160 100" className="w-40 h-24">
            <path d="M 20 90 A 60 60 0 0 1 140 90" fill="none" stroke="#262626" strokeWidth="12" strokeLinecap="round" />
            <path d="M 20 90 A 60 60 0 0 1 140 90" fill="none" stroke="url(#speedGrad)" strokeWidth="12" strokeLinecap="round"
                  strokeDasharray="188.4" strokeDashoffset={188.4 - (188.4 * (pct / 100))} style={{ transition: 'stroke-dashoffset 0.6s ease' }} />
            <defs>
              <linearGradient id="speedGrad" x1="0%" y1="0%" x2="100%" y2="0%">
                <stop offset="0%" stopColor="#34D399" />
                <stop offset="50%" stopColor="#FBBF24" />
                <stop offset="100%" stopColor="#F87171" />
              </linearGradient>
            </defs>
          </svg>
          <div className="absolute bottom-1 text-center">
            <div className="text-2xl font-bold text-neutral-100 tabular-nums leading-tight">{val} <span className="text-xs text-neutral-400 font-normal">{unit}</span></div>
            <div className="text-[10px] text-neutral-500 uppercase tracking-widest mt-0.5">Avg Compilation</div>
          </div>
        </div>
      </div>
    </Card>
  );
}

export function HeatmapGridWidget({ metric, title }: { metric: string; title: string }) {
  const { data, isPending, error, refetch } = useMetric<GroupResponse>(metric);
  if (isPending) return <Card><CardHeader title={title} /><Skeleton className="flex-1 min-h-[180px]" /></Card>;
  if (error) return <Card><CardHeader title={title} /><ErrorState onRetry={() => refetch()} /></Card>;

  const maxVal = Math.max(...data.groups.map(g => g.value), 1);
  const projects = Array.from(new Set(data.groups.map(g => g.key.split(':')[0])));
  const categories = Array.from(new Set(data.groups.map(g => g.key.split(':')[1])));
  const map: Record<string, number> = {};
  for (const g of data.groups) map[g.key] = g.value;

  return (
    <Card>
      <CardHeader title={title} icon={Layers} />
      <div className="flex-1 overflow-x-auto flex flex-col justify-center">
        <table className="w-full text-xs border-collapse">
          <thead>
            <tr>
              <th className="p-2 text-left text-neutral-500 font-medium border-b border-neutral-800">Project</th>
              {categories.map(cat => (
                <th key={cat} className="p-2 text-center text-neutral-400 font-medium border-b border-neutral-800">{cat}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {projects.map(proj => (
              <tr key={proj} className="border-b border-neutral-800/40">
                <td className="p-2 font-semibold text-neutral-200">{proj}</td>
                {categories.map(cat => {
                  const val = map[`${proj}:${cat}`] || 0;
                  const intensity = val > 0 ? Math.max(0.15, val / maxVal) : 0;
                  return (
                    <td key={cat} className="p-1 text-center">
                      <div 
                        className="py-1.5 px-2 rounded font-semibold tabular-nums text-neutral-100 transition-all hover:scale-105"
                        style={{ 
                          backgroundColor: val > 0 ? `rgba(129, 140, 248, ${intensity})` : '#171717',
                          color: val > 0 ? '#ffffff' : '#525252',
                          border: val > 0 ? '1px solid rgba(129, 140, 248, 0.4)' : '1px solid #262626'
                        }}
                      >
                        {val}
                      </div>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

export function LeaderboardWidget({ metric, title }: { metric: string; title: string }) {
  const { data, isPending, error, refetch } = useMetric<GroupResponse>(metric);
  if (isPending) return <Card><CardHeader title={title} /><Skeleton className="flex-1 min-h-[180px]" /></Card>;
  if (error) return <Card><CardHeader title={title} /><ErrorState onRetry={() => refetch()} /></Card>;

  const maxVal = data.groups[0]?.value || 1;

  return (
    <Card>
      <CardHeader title={title} icon={Zap} />
      <div className="flex-1 flex flex-col gap-2.5 text-xs my-auto">
        {data.groups.map((item, i) => {
          const pct = (item.value / maxVal) * 100;
          return (
            <div key={item.key} className="flex items-center gap-3">
              <span className={clsx(
                "w-5 h-5 rounded flex items-center justify-center font-bold text-[11px] shrink-0",
                i === 0 ? "bg-amber-500/20 text-amber-400 border border-amber-500/30" :
                i === 1 ? "bg-neutral-400/20 text-neutral-300 border border-neutral-400/30" :
                i === 2 ? "bg-amber-700/20 text-amber-500 border border-amber-700/30" :
                "bg-neutral-800 text-neutral-500"
              )}>
                {i + 1}
              </span>
              <div className="flex-1 min-w-0">
                <div className="flex justify-between items-center mb-1">
                  <span className="text-neutral-200 font-medium truncate">{item.key}</span>
                  <span className="text-neutral-400 font-semibold tabular-nums ml-2">{item.value} reports</span>
                </div>
                <div className="h-1.5 bg-neutral-800 rounded-full overflow-hidden">
                  <div className="h-full rounded-full bg-gradient-to-r from-indigo-500 to-cyan-400" style={{ width: `${pct}%` }} />
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </Card>
  );
}

const NUMERIC_COLS = new Set([
  'requests', 'prompt_tokens', 'completion_tokens', 'total_tokens', 'calls', 'avg_per_call',
  'count', 'reported', 'closed', 'total', 'unresolved', 'p1_open',
  'open', 'in_progress', 'fixed', 'audit_score', 'reports_count', 'avg_latency', 'latency_sec', 'tokens_used'
]);

function defaultColumnConfig(col: string): ColumnConfig {
  if (col === 'total_tokens') return { format: 'bold-number', align: 'right' };
  if (col === 'progress_pct' || col === 'planned_pct') return { format: 'progress-bar', align: 'left' };
  if (col === 'health_status') return { format: 'health-status-badge', align: 'left' };
  if (col === 'report_type') return { format: 'report-type-badge', align: 'left' };
  if (col === 'severity' || col === 'risk_type') return { format: 'risk-severity-badge', align: 'left' };
  if (NUMERIC_COLS.has(col))  return { format: 'number',      align: 'right' };
  if (col === 'timestamp' || col === 'created_at' || col === 'target_date' || col === 'event_date' || col === 'completed_at') return { format: 'timestamp', align: 'left' };
  if (col === 'feature')      return { format: 'feature-icon', align: 'left' };
  if (col === 'status')       return { format: 'status-badge', align: 'left' };
  if (col === 'project_code' || col === 'code') return { format: 'badge', align: 'left' };
  if (col === 'user_email' || col === 'email')  return { format: 'muted', align: 'left' };
  if (col === 'output_format') return { format: 'format-badge', align: 'left' };
  if (col === 'pipeline_stage') return { format: 'pipeline-stage-badge', align: 'left' };
  if (col === 'age_days')     return { format: 'age', align: 'right' };
  if (col === 'pct' || col === 'close_rate' || col === 'coverage_pct' || col === 'delivery_score' || col === 'quality_score' || col === 'testing_score') return { format: 'percent-cell', align: 'right' };
  return { format: 'text', align: 'left' };
}

function humanizeColumnName(col: string): string {
  return col.replaceAll('_', ' ');
}

function renderCell(col: string, value: unknown, cfg: ColumnConfig): ReactNode {
  if (value == null || value === '') return <span className="text-neutral-600">—</span>;

  switch (cfg.format) {
    case 'timestamp': {
      const valStr = String(value);
      if (valStr.includes('T')) {
        const d = typeof value === 'string' ? parseISO(value) : new Date(value as string);
        return <span className="text-neutral-400 tabular-nums text-xs">{formatDate(d, 'MM/dd/yyyy, HH:mm:ss')}</span>;
      }
      return <span className="text-neutral-400 tabular-nums text-xs">{valStr}</span>;
    }
    case 'health-status-badge': {
      const st = String(value).toLowerCase();
      const styles: Record<string, { bg: string; dot: string; label: string }> = {
        on_track: { bg: 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/30', dot: 'bg-emerald-400', label: 'On Track' },
        at_risk:  { bg: 'bg-amber-500/15 text-amber-400 border border-amber-500/30', dot: 'bg-amber-400', label: 'At Risk' },
        delayed:  { bg: 'bg-red-500/15 text-red-400 border border-red-500/30', dot: 'bg-red-400', label: 'Delayed' },
      };
      const meta = styles[st] ?? { bg: 'bg-neutral-800 text-neutral-400 border border-neutral-700', dot: 'bg-neutral-400', label: st };
      return (
        <span className={clsx('inline-flex items-center gap-1.5 px-2.5 py-0.5 text-[10px] font-semibold rounded-full uppercase tracking-wider', meta.bg)}>
          <span className={clsx('w-1.5 h-1.5 rounded-full animate-pulse', meta.dot)} />
          {meta.label}
        </span>
      );
    }
    case 'progress-bar': {
      const pct = typeof value === 'number' ? value : parseInt(String(value), 10) || 0;
      const color = pct >= 80 ? 'from-emerald-500 to-teal-400' : pct >= 50 ? 'from-indigo-500 to-cyan-400' : 'from-amber-500 to-rose-400';
      return (
        <div className="flex items-center gap-2 min-w-[120px]">
          <div className="flex-1 h-2 bg-neutral-800 rounded-full overflow-hidden p-0.5 border border-neutral-800">
            <div className={clsx('h-full rounded-full bg-gradient-to-r transition-all duration-500', color)} style={{ width: `${Math.min(100, pct)}%` }} />
          </div>
          <span className="text-xs font-semibold text-neutral-200 tabular-nums w-8 text-right">{pct}%</span>
        </div>
      );
    }
    case 'report-type-badge': {
      const rt = String(value).toUpperCase();
      const isDSR = rt === 'DSR';
      return (
        <span className={clsx(
          'inline-flex items-center gap-1 px-2 py-0.5 text-[10px] font-bold rounded uppercase tracking-wider border',
          isDSR ? 'bg-indigo-500/15 text-indigo-400 border-indigo-500/25' : 'bg-purple-500/15 text-purple-400 border-purple-500/25'
        )}>
          <FileText size={10} strokeWidth={2.5} />
          {rt}
        </span>
      );
    }
    case 'risk-severity-badge': {
      const sev = String(value).toLowerCase();
      const styles: Record<string, string> = {
        critical: 'bg-red-500/15 text-red-400 border border-red-500/30 font-bold',
        warning:  'bg-amber-500/15 text-amber-400 border border-amber-500/30 font-semibold',
        notice:   'bg-blue-500/15 text-blue-400 border border-blue-500/30',
        info:     'bg-neutral-800 text-neutral-300 border border-neutral-700',
      };
      return (
        <span className={clsx('inline-block px-2 py-0.5 text-[10px] uppercase tracking-wider rounded', styles[sev] ?? 'bg-neutral-800 text-neutral-400')}>
          {sev}
        </span>
      );
    }
    case 'milestone-status-badge': {
      const st = String(value).toLowerCase();
      const isDone = st === 'completed';
      const isProg = st === 'in_progress';
      return (
        <span className={clsx(
          'inline-flex items-center gap-1 px-2 py-0.5 text-[10px] font-semibold rounded capitalize',
          isDone ? 'bg-emerald-500/15 text-emerald-400' : isProg ? 'bg-cyan-500/15 text-cyan-400' : 'bg-neutral-800 text-neutral-400'
        )}>
          <span className={clsx('w-1.5 h-1.5 rounded-full', isDone ? 'bg-emerald-400' : isProg ? 'bg-cyan-400 animate-pulse' : 'bg-neutral-500')} />
          {st.replace('_', ' ')}
        </span>
      );
    }
    case 'format-badge': {
      const fmt = String(value).toLowerCase();
      const styles: Record<string, string> = {
        pdf: 'bg-red-500/15 text-red-400 border-red-500/20',
        xlsx: 'bg-emerald-500/15 text-emerald-400 border-emerald-500/20',
        md: 'bg-purple-500/15 text-purple-400 border-purple-500/20',
      };
      return (
        <span className={clsx('inline-block px-2 py-0.5 text-[10px] font-bold rounded uppercase tracking-wider border', styles[fmt] ?? 'bg-neutral-800 text-neutral-400 border-neutral-700')}>
          .{fmt}
        </span>
      );
    }
    case 'pipeline-stage-badge': {
      const st = String(value).toLowerCase();
      const styles: Record<string, string> = {
        published:  'bg-emerald-500/15 text-emerald-400',
        compiled:   'bg-cyan-500/15 text-cyan-400',
        summarized: 'bg-amber-500/15 text-amber-400',
        ingested:   'bg-indigo-500/15 text-indigo-400',
      };
      const dot: Record<string, string> = {
        published: 'bg-emerald-400', compiled: 'bg-cyan-400',
        summarized: 'bg-amber-400', ingested: 'bg-indigo-400',
      };
      return (
        <span className={clsx('inline-flex items-center gap-1.5 px-2 py-0.5 text-[10px] font-medium rounded capitalize', styles[st] ?? 'bg-neutral-700 text-neutral-300')}>
          <span className={clsx('w-1.5 h-1.5 rounded-full', dot[st] ?? 'bg-neutral-400')} />
          {st}
        </span>
      );
    }
    case 'build-status-badge': {
      const st = String(value).toUpperCase();
      const styles: Record<string, string> = {
        PASS: 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30',
        WARN: 'bg-amber-500/15 text-amber-400 border-amber-500/30',
        FAIL: 'bg-red-500/15 text-red-400 border-red-500/30',
      };
      return (
        <span className={clsx('inline-block px-2 py-0.5 text-[10px] font-bold rounded uppercase tracking-wide border', styles[st] ?? 'bg-neutral-800 text-neutral-400')}>
          {st}
        </span>
      );
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
      const styles: Record<string, string> = {
        P1: 'bg-red-500/15 text-red-400',
        P2: 'bg-amber-500/15 text-amber-400',
        P3: 'bg-indigo-500/15 text-indigo-400',
        P4: 'bg-orange-500/15 text-orange-400',
      };
      return (
        <span className={clsx('inline-block px-2 py-0.5 text-[10px] font-semibold rounded', styles[sev] ?? 'bg-neutral-700 text-neutral-300')}>
          {sev}
        </span>
      );
    }
    case 'status-badge': {
      const st = String(value);
      const styles: Record<string, string> = {
        open:        'bg-amber-500/15 text-amber-400',
        in_progress: 'bg-cyan-500/15 text-cyan-400',
        fixed:       'bg-emerald-500/15 text-emerald-400',
        closed:      'bg-neutral-600/30 text-neutral-400',
        completed:   'bg-emerald-500/15 text-emerald-400',
        upcoming:    'bg-neutral-800 text-neutral-400',
      };
      const dot: Record<string, string> = {
        open: 'bg-amber-400', in_progress: 'bg-cyan-400',
        fixed: 'bg-emerald-400', closed: 'bg-neutral-400',
        completed: 'bg-emerald-400', upcoming: 'bg-neutral-500',
      };
      return (
        <span className={clsx('inline-flex items-center gap-1.5 px-2 py-0.5 text-[10px] font-medium rounded', styles[st] ?? 'bg-neutral-700 text-neutral-300')}>
          <span className={clsx('w-1.5 h-1.5 rounded-full', dot[st] ?? 'bg-neutral-400')} />
          {st.replace('_', ' ')}
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
      return <span className="text-neutral-300 font-medium tabular-nums">{typeof value === 'number' ? `${value}%` : String(value)}</span>;
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
  const { setFilter } = useFilterActions();
  const isTelemetry = metric === 'bugs.telemetry';
  const effectivePageSize = pageSize ?? 15;
  const [page, setPage] = useState(1);
  const [sort, setSort] = useState({ col: isTelemetry ? 'severity' : 'total_tokens', dir: (isTelemetry ? 'asc' : 'desc') as 'asc' | 'desc' });

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
    else setSort({ col, dir: col === 'severity' || col === 'issue_no' ? 'asc' : 'desc' });
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
              <tr
                key={i}
                onClick={() => {
                  if (isTelemetry && row.issue_no) {
                    setFilter('issue_no', String(row.issue_no));
                  }
                }}
                className={clsx(
                  "border-b border-neutral-800/50 last:border-b-0",
                  isTelemetry ? "hover:bg-indigo-950/20 cursor-pointer hover:text-indigo-300 transition-colors" : "hover:bg-neutral-800/30"
                )}
              >
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

// ══════════════════════════════════════════════════════════════════════════
//  REPORTIQ V2 WIDGETS
// ══════════════════════════════════════════════════════════════════════════

/**
 * 1. ProjectBannerWidget — Hero header for the selected project
 */
export function ProjectBannerWidget({ metric }: { metric: string }) {
  const { data, isPending, error, refetch } = useMetric<TableResponse>(metric);
  const { setFilter } = useFilterActions();

  if (isPending) return <Card><Skeleton className="h-32" /></Card>;
  if (error || !data.rows.length) return (
    <Card>
      <div className="flex items-center justify-between">
        <span className="text-neutral-400 text-sm">Project Command Center</span>
        <button
          onClick={() => setFilter('project_id', undefined)}
          className="flex items-center gap-1.5 text-xs text-indigo-400 hover:text-indigo-300 transition-colors"
        >
          <ArrowLeft size={13} /> Back to Portfolio Overview
        </button>
      </div>
    </Card>
  );

  const row = data.rows[0];
  const name = String(row.project_name || 'Project Command Center');
  const code = String(row.project_code || 'PRJ');
  const progressPct = Number(row.progress_pct || 0);
  const plannedPct = Number(row.planned_pct || 0);
  const healthStatus = String(row.health_status || 'on_track');
  const targetDate = String(row.target_date || 'TBD');
  const activeRisks = Number(row.active_risks_count || 0);
  const reportsCount = Number(row.reports_count || 0);
  const filesCount = Number(row.files_count || 0);
  const deliveryScore = Number(row.delivery_score || 0);
  const qualityScore = Number(row.quality_score || 0);
  const testingScore = Number(row.testing_score || 0);
  const buildScore = Number(row.build_score || 0);

  const gap = progressPct - plannedPct;
  const c = codeColor(code);

  const statusStyles: Record<string, { label: string; bg: string; dot: string }> = {
    on_track: { label: 'ON TRACK', bg: 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/30', dot: 'bg-emerald-400' },
    at_risk:  { label: 'AT RISK',  bg: 'bg-amber-500/15 text-amber-400 border border-amber-500/30', dot: 'bg-amber-400' },
    delayed:  { label: 'DELAYED',  bg: 'bg-red-500/15 text-red-400 border border-red-500/30', dot: 'bg-red-400' },
  };
  const stMeta = statusStyles[healthStatus] ?? statusStyles.on_track;

  return (
    <div className="bg-gradient-to-r from-neutral-900 via-neutral-900/95 to-indigo-950/40 border border-neutral-800 rounded-xl p-5 shadow-lg relative overflow-hidden flex flex-col justify-between">
      {/* Top action row */}
      <div className="flex flex-wrap items-center justify-between gap-4 mb-4">
        <div className="flex items-center gap-3">
          <button
            onClick={() => setFilter('project_id', undefined)}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-neutral-800/80 hover:bg-neutral-700/80 border border-neutral-700 text-neutral-300 hover:text-white text-xs font-medium transition-all shadow-sm group"
          >
            <ArrowLeft size={13} className="group-hover:-translate-x-0.5 transition-transform" />
            <span>All Projects</span>
          </button>
          <div className="h-4 w-px bg-neutral-800" />
          <div className="flex items-center gap-2">
            <span className={clsx('px-2 py-0.5 text-xs font-bold rounded uppercase tracking-wider', c.bg, c.fg)}>
              {code}
            </span>
            <h2 className="text-xl font-bold text-neutral-100 tracking-tight">{name}</h2>
          </div>
          <span className={clsx('inline-flex items-center gap-1.5 px-2.5 py-0.5 text-[10px] font-bold rounded-full uppercase tracking-wider', stMeta.bg)}>
            <span className={clsx('w-1.5 h-1.5 rounded-full animate-pulse', stMeta.dot)} />
            {stMeta.label}
          </span>
        </div>

        <div className="flex items-center gap-2 text-xs text-neutral-400">
          <Calendar size={13} className="text-neutral-500" />
          <span>Target Release: <strong className="text-neutral-200 font-semibold">{targetDate}</strong></span>
        </div>
      </div>

      {/* Hero progress & stats bar */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4 items-center bg-neutral-950/60 rounded-xl p-4 border border-neutral-800/80">
        {/* Progress gauge */}
        <div className="md:col-span-2 flex flex-col gap-2">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="text-xs text-neutral-400 uppercase tracking-wider font-semibold">Overall Delivery Progress</span>
              <span className={clsx('text-[11px] font-semibold px-2 py-0.5 rounded', gap >= 0 ? 'bg-emerald-500/15 text-emerald-400' : 'bg-rose-500/15 text-rose-400')}>
                {gap >= 0 ? `+${gap}% Ahead of Plan` : `${gap}% Lagging Plan`}
              </span>
            </div>
            <span className="text-2xl font-bold text-white tabular-nums">{progressPct}%</span>
          </div>
          <div className="h-3 bg-neutral-900 rounded-full overflow-hidden p-0.5 border border-neutral-800">
            <div
              className="h-full rounded-full bg-gradient-to-r from-indigo-500 via-cyan-400 to-emerald-400 transition-all duration-700 shadow-sm"
              style={{ width: `${Math.min(100, Math.max(2, progressPct))}%` }}
            />
          </div>
          <div className="flex justify-between text-[10px] text-neutral-500">
            <span>Planned Target: <strong className="text-neutral-400">{plannedPct}%</strong></span>
            <span>Current Execution: <strong className="text-neutral-300">{progressPct}%</strong></span>
          </div>
        </div>

        {/* Quick status chips */}
        <div className="flex items-center justify-around gap-2 border-t md:border-t-0 md:border-l border-neutral-800/80 pt-3 md:pt-0 md:pl-4">
          <div className="text-center">
            <div className="text-lg font-bold text-neutral-100 tabular-nums">{reportsCount}</div>
            <div className="text-[10px] text-neutral-400 uppercase tracking-wider">Reports Filed</div>
          </div>
          <div className="h-8 w-px bg-neutral-800" />
          <div className="text-center">
            <div className="text-lg font-bold text-neutral-100 tabular-nums">{filesCount}</div>
            <div className="text-[10px] text-neutral-400 uppercase tracking-wider">Specs & Files</div>
          </div>
          <div className="h-8 w-px bg-neutral-800" />
          <div className="text-center">
            <div className={clsx('text-lg font-bold tabular-nums', activeRisks > 0 ? 'text-amber-400' : 'text-emerald-400')}>
              {activeRisks}
            </div>
            <div className="text-[10px] text-neutral-400 uppercase tracking-wider">Active Risks</div>
          </div>
        </div>

        {/* Multi-score mini ratings */}
        <div className="flex flex-col gap-1.5 border-t md:border-t-0 md:border-l border-neutral-800/80 pt-3 md:pt-0 md:pl-4 text-xs">
          <div className="flex justify-between items-center">
            <span className="text-neutral-400">Quality Score:</span>
            <span className="font-semibold text-neutral-200 tabular-nums">{qualityScore}%</span>
          </div>
          <div className="flex justify-between items-center">
            <span className="text-neutral-400">Testing Pass:</span>
            <span className="font-semibold text-neutral-200 tabular-nums">{testingScore}%</span>
          </div>
          <div className="flex justify-between items-center">
            <span className="text-neutral-400">Build Stability:</span>
            <span className="font-semibold text-neutral-200 tabular-nums">{buildScore}%</span>
          </div>
        </div>
      </div>
    </div>
  );
}

/**
 * 2. ProjectHealthWidget — Multi-dimensional progress bars
 */
export function ProjectHealthWidget({ metric, title }: { metric: string; title: string }) {
  const { data, isPending, error, refetch } = useMetric<GroupResponse>(metric);

  if (isPending) return <Card><CardHeader title={title} /><Skeleton className="h-44" /></Card>;
  if (error) return <Card><CardHeader title={title} /><ErrorState onRetry={() => refetch()} /></Card>;

  const gradients = [
    'from-indigo-500 to-indigo-400',
    'from-cyan-500 to-cyan-400',
    'from-emerald-500 to-emerald-400',
    'from-amber-500 to-amber-400',
    'from-purple-500 to-purple-400',
  ];

  return (
    <Card>
      <CardHeader title={title} icon={BarChart3} />
      <div className="flex-1 flex flex-col justify-around gap-2.5 my-auto">
        {data.groups.map((dim, i) => {
          const val = dim.value;
          const statusText = val >= 85 ? 'Optimal' : val >= 65 ? 'Healthy' : 'Attention';
          const statusColor = val >= 85 ? 'text-emerald-400 bg-emerald-500/10' : val >= 65 ? 'text-cyan-400 bg-cyan-500/10' : 'text-amber-400 bg-amber-500/10';

          return (
            <div key={dim.key} className="flex flex-col gap-1">
              <div className="flex items-center justify-between text-xs">
                <span className="font-medium text-neutral-200">{dim.key}</span>
                <div className="flex items-center gap-2">
                  <span className={clsx('text-[10px] font-semibold px-1.5 py-0.5 rounded uppercase tracking-wider', statusColor)}>
                    {statusText}
                  </span>
                  <span className="text-neutral-100 font-bold tabular-nums w-8 text-right">{val}%</span>
                </div>
              </div>
              <div className="h-2 bg-neutral-800 rounded-full overflow-hidden p-0.5 border border-neutral-800">
                <div
                  className={clsx('h-full rounded-full bg-gradient-to-r transition-all duration-500', gradients[i % gradients.length])}
                  style={{ width: `${Math.min(100, Math.max(2, val))}%` }}
                />
              </div>
            </div>
          );
        })}
      </div>
    </Card>
  );
}

/**
 * 3. WhatChangedWidget — Delta highlights card
 */
export function WhatChangedWidget({ metric, title }: { metric: string; title: string }) {
  const { data, isPending, error, refetch } = useMetric<GroupResponse>(metric);

  if (isPending) return <Card><CardHeader title={title} /><Skeleton className="h-44" /></Card>;
  if (error) return <Card><CardHeader title={title} /><ErrorState onRetry={() => refetch()} /></Card>;

  return (
    <Card>
      <CardHeader title={title} icon={Sparkles} right={<span className="text-[10px] uppercase tracking-wider text-indigo-400 font-semibold">Live Delta</span>} />
      <div className="grid grid-cols-2 md:grid-cols-3 gap-3 flex-1 items-center">
        {data.groups.map(item => {
          const isWarn = item.key.toLowerCase().includes('blocker') || item.key.toLowerCase().includes('risk');
          const isGood = !isWarn;

          return (
            <div
              key={item.key}
              className="bg-neutral-950/50 border border-neutral-800/80 rounded-lg p-3 flex flex-col justify-between hover:border-neutral-700 transition-colors"
            >
              <div className="text-[11px] text-neutral-400 font-medium truncate mb-1">{item.key}</div>
              <div className="flex items-baseline justify-between mt-1">
                <span className="text-2xl font-bold text-neutral-100 tabular-nums">{item.value}</span>
                {isGood ? (
                  <span className="inline-flex items-center text-[10px] font-semibold text-emerald-400">
                    <TrendingUp size={12} className="mr-0.5" /> Good
                  </span>
                ) : (
                  <span className="inline-flex items-center text-[10px] font-semibold text-amber-400">
                    <AlertTriangle size={12} className="mr-0.5" /> Watch
                  </span>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </Card>
  );
}

/**
 * 4. ProjectTimelineWidget — Journey timeline
 */
export function ProjectTimelineWidget({ metric, title }: { metric: string; title: string }) {
  const { data, isPending, error, refetch } = useMetric<TableResponse>(metric);

  if (isPending) return <Card><CardHeader title={title} /><Skeleton className="h-56" /></Card>;
  if (error) return <Card><CardHeader title={title} /><ErrorState onRetry={() => refetch()} /></Card>;

  const rows = data.rows;

  return (
    <Card>
      <CardHeader title={title} icon={Milestone} right={<span className="text-xs text-neutral-500">{rows.length} Major Milestones & Events</span>} />
      <div className="overflow-y-auto max-h-[300px] pr-2 space-y-3.5 flex-1 relative">
        <div className="absolute left-3.5 top-2 bottom-2 w-0.5 bg-neutral-800" />

        {rows.map((evt, i) => {
          const dateStr = String(evt.event_date || '');
          const sev = String(evt.severity || 'info');
          const type = String(evt.event_type || 'event');
          const tTitle = String(evt.title || '');
          const desc = String(evt.description || '');

          const isCritical = sev === 'critical';
          const isWarning = sev === 'warning';
          const isSuccess = sev === 'success';

          const nodeColor = isCritical ? 'bg-rose-500 text-rose-100 ring-rose-500/30' :
                            isWarning  ? 'bg-amber-500 text-amber-950 ring-amber-500/30' :
                            isSuccess  ? 'bg-emerald-500 text-emerald-950 ring-emerald-500/30' :
                            'bg-indigo-500 text-indigo-100 ring-indigo-500/30';

          return (
            <div key={i} className="flex items-start gap-3.5 relative pl-1 group">
              <div className={clsx('w-6 h-6 rounded-full flex items-center justify-center text-[10px] font-bold shrink-0 ring-4 z-10', nodeColor)}>
                {isSuccess ? <CheckCircle2 size={12} /> : isCritical || isWarning ? <AlertCircle size={12} /> : <Clock size={12} />}
              </div>
              <div className="flex-1 bg-neutral-950/50 border border-neutral-800 rounded-lg p-2.5 hover:border-neutral-700 transition-colors">
                <div className="flex flex-wrap items-center justify-between gap-1 mb-1">
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-semibold text-neutral-100">{tTitle}</span>
                    <span className="px-1.5 py-0.5 text-[9px] font-bold rounded uppercase tracking-wider bg-neutral-800 text-neutral-400 border border-neutral-700">
                      {type.replace('_', ' ')}
                    </span>
                  </div>
                  <span className="text-[11px] text-neutral-500 tabular-nums font-mono">{dateStr}</span>
                </div>
                {desc && <p className="text-xs text-neutral-400 leading-relaxed">{desc}</p>}
              </div>
            </div>
          );
        })}
      </div>
    </Card>
  );
}

/**
 * 5. ProgressTrendWidget — Planned vs Actual Progress Curve
 */
export function ProgressTrendWidget({ metric, title }: { metric: string; title: string }) {
  const { data, isPending, error, refetch } = useMetric<SeriesResponse>(metric);

  if (isPending) return <Card><CardHeader title={title} /><Skeleton className="h-56" /></Card>;
  if (error) return <Card><CardHeader title={title} /><ErrorState onRetry={() => refetch()} /></Card>;

  const points = (data as any)?.points || [];

  return (
    <Card>
      <CardHeader title={title} icon={TrendingUp} right={<span className="text-[10px] text-neutral-400 uppercase tracking-wider font-semibold">Planned vs Actual</span>} />
      <div className="flex-1 min-h-[220px]">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={points} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
            <defs>
              <linearGradient id="actualGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#22D3EE" stopOpacity={0.4} />
                <stop offset="95%" stopColor="#22D3EE" stopOpacity={0.0} />
              </linearGradient>
              <linearGradient id="plannedGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#818CF8" stopOpacity={0.2} />
                <stop offset="95%" stopColor="#818CF8" stopOpacity={0.0} />
              </linearGradient>
            </defs>
            <CartesianGrid stroke={GRID_COLOR} strokeDasharray="3 3" vertical={false} />
            <XAxis dataKey="timestamp" stroke={AXIS_TEXT} tickLine={false} tick={{ fontSize: 10 }} minTickGap={30} />
            <YAxis stroke={AXIS_TEXT} tickLine={false} tick={{ fontSize: 10 }} domain={[0, 100]} unit="%" />
            <Tooltip
              contentStyle={{ backgroundColor: TOOLTIP_BG, borderColor: TOOLTIP_BORDER, borderRadius: '8px', fontSize: '12px' }}
              labelStyle={{ color: '#A3A3A3', marginBottom: '4px' }}
              formatter={(value: any, name: any) => [`${value}%`, name === 'actual' ? 'Actual Progress' : 'Planned Progress']}
            />
            <Legend
              verticalAlign="top" align="right" height={24}
              formatter={(val) => <span className="text-[11px] text-neutral-300 font-medium">{val === 'actual' ? 'Actual Progress' : 'Planned Progress'}</span>}
            />
            <Area type="monotone" dataKey="planned" stroke="#818CF8" strokeWidth={2} strokeDasharray="4 4" fill="url(#plannedGrad)" name="planned" />
            <Area type="monotone" dataKey="actual" stroke="#22D3EE" strokeWidth={2.5} fill="url(#actualGrad)" name="actual" />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </Card>
  );
}

/**
 * 6. AttentionRequiredWidget — Risk & blocker alerts
 */
export function AttentionRequiredWidget({ metric, title }: { metric: string; title: string }) {
  const { data, isPending, error, refetch } = useMetric<TableResponse>(metric);

  if (isPending) return <Card><CardHeader title={title} /><Skeleton className="h-56" /></Card>;
  if (error) return <Card><CardHeader title={title} /><ErrorState onRetry={() => refetch()} /></Card>;

  const rows = data.rows;

  return (
    <Card>
      <CardHeader title={title} icon={ShieldAlert} right={<span className="px-2 py-0.5 text-[10px] font-bold rounded bg-amber-500/15 text-amber-400 border border-amber-500/25 uppercase">{rows.length} Active Items</span>} />
      <div className="flex-1 overflow-y-auto max-h-[260px] space-y-2.5 pr-1">
        {rows.length === 0 ? (
          <div className="h-full flex items-center justify-center text-xs text-neutral-500">
            No critical blockers or active risks flagged.
          </div>
        ) : (
          rows.map((risk, i) => {
            const sev = String(risk.severity || 'warning').toLowerCase();
            const isCrit = sev === 'critical';
            const borderCol = isCrit ? 'border-rose-500/40 bg-rose-500/5' : 'border-amber-500/40 bg-amber-500/5';
            const badgeCol = isCrit ? 'bg-rose-500/20 text-rose-400 border-rose-500/30' : 'bg-amber-500/20 text-amber-400 border-amber-500/30';

            return (
              <div key={i} className={clsx('border rounded-lg p-3 transition-colors', borderCol)}>
                <div className="flex items-center justify-between mb-1">
                  <span className={clsx('px-1.5 py-0.5 text-[9px] font-bold rounded uppercase tracking-wider border', badgeCol)}>
                    {sev}
                  </span>
                  <span className="text-[10px] text-neutral-500 font-mono">{String(risk.risk_type || 'RISK')}</span>
                </div>
                <h4 className="text-xs font-semibold text-neutral-100 mb-1">{String(risk.title)}</h4>
                {risk.detail ? <p className="text-[11px] text-neutral-400 leading-relaxed">{String(risk.detail)}</p> : null}
              </div>
            );
          })
        )}
      </div>
    </Card>
  );
}

/**
 * 7. MilestoneTrackerWidget — Milestone roadmap
 */
export function MilestoneTrackerWidget({ metric, title }: { metric: string; title: string }) {
  const { data, isPending, error, refetch } = useMetric<TableResponse>(metric);

  if (isPending) return <Card><CardHeader title={title} /><Skeleton className="h-44" /></Card>;
  if (error) return <Card><CardHeader title={title} /><ErrorState onRetry={() => refetch()} /></Card>;

  const rows = data.rows;

  return (
    <Card>
      <CardHeader title={title} icon={Milestone} />
      <div className="flex-1 flex flex-col justify-around gap-2 my-auto">
        {rows.map((ms, i) => {
          const st = String(ms.status || 'upcoming').toLowerCase();
          const isDone = st === 'completed';
          const isProg = st === 'in_progress';
          const dateLabel = isDone && ms.completed_at ? `Done ${ms.completed_at}` : ms.target_date ? `Target ${ms.target_date}` : '';

          return (
            <div key={i} className="flex items-center justify-between gap-3 text-xs bg-neutral-950/40 border border-neutral-800/60 rounded-lg p-2.5">
              <div className="flex items-center gap-2.5 min-w-0">
                <span className={clsx(
                  'w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-bold shrink-0',
                  isDone ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/40' :
                  isProg ? 'bg-cyan-500/20 text-cyan-400 border border-cyan-500/40 animate-pulse' :
                  'bg-neutral-800 text-neutral-500 border border-neutral-700'
                )}>
                  {isDone ? '✓' : i + 1}
                </span>
                <span className={clsx('font-medium truncate', isDone ? 'text-neutral-200' : isProg ? 'text-cyan-300 font-semibold' : 'text-neutral-400')}>
                  {String(ms.name)}
                </span>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                <span className="text-[10px] text-neutral-500 tabular-nums">{dateLabel}</span>
                <span className={clsx(
                  'px-2 py-0.5 text-[9px] font-semibold rounded capitalize',
                  isDone ? 'bg-emerald-500/15 text-emerald-400' : isProg ? 'bg-cyan-500/15 text-cyan-400' : 'bg-neutral-800 text-neutral-500'
                )}>
                  {st.replace('_', ' ')}
                </span>
              </div>
            </div>
          );
        })}
      </div>
    </Card>
  );
}

/**
 * 8. PortfolioMatrixWidget — Interactive project table with drilldown
 */
export function PortfolioMatrixWidget({ metric, title }: { metric: string; title: string }) {
  const { data, isPending, error, refetch } = useMetric<TableResponse>(metric);
  const { setFilter } = useFilterActions();

  if (isPending) return <Card><CardHeader title={title} /><Skeleton className="h-64" /></Card>;
  if (error) return <Card><CardHeader title={title} /><ErrorState onRetry={() => refetch()} /></Card>;

  const rows = data.rows;

  return (
    <Card>
      <CardHeader
        title={title}
        icon={FolderGit2}
        right={<span className="text-[10px] text-indigo-400 font-semibold uppercase tracking-wider">Click any project to drill down</span>}
      />
      <div className="overflow-x-auto flex-1">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-[10px] uppercase tracking-wider text-neutral-500 font-medium border-b border-neutral-800">
              <th className="py-2.5 px-3 text-left">Project</th>
              <th className="py-2.5 px-3 text-left">Progress</th>
              <th className="py-2.5 px-3 text-left">Health</th>
              <th className="py-2.5 px-3 text-right">Delivery</th>
              <th className="py-2.5 px-3 text-right">Quality</th>
              <th className="py-2.5 px-3 text-right">Reports</th>
              <th className="py-2.5 px-3 text-left">Target Date</th>
              <th className="py-2.5 px-3 text-right">Action</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => {
              const pid = String(r.project_id);
              const pCode = String(r.project_code || '');
              const c = codeColor(pCode);
              const pct = Number(r.progress_pct || 0);
              const hSt = String(r.health_status || 'on_track');
              const delScore = Number(r.delivery_score || 0);
              const qScore = Number(r.quality_score || 0);
              const reports = Number(r.total_reports || 0);
              const tDate = String(r.target_date || '');

              return (
                <tr
                  key={i}
                  onClick={() => setFilter('project_id', pid)}
                  className="border-b border-neutral-800/40 last:border-b-0 hover:bg-neutral-800/50 cursor-pointer transition-colors group"
                >
                  <td className="py-3 px-3 font-semibold text-neutral-100">
                    <div className="flex items-center gap-2">
                      <span className={clsx('px-1.5 py-0.5 text-[9px] font-bold rounded uppercase', c.bg, c.fg)}>
                        {pCode}
                      </span>
                      <span className="group-hover:text-indigo-300 transition-colors">{String(r.project_name)}</span>
                    </div>
                  </td>
                  <td className="py-3 px-3 min-w-[130px]">
                    <div className="flex items-center gap-2">
                      <div className="flex-1 h-2 bg-neutral-800 rounded-full overflow-hidden p-0.5 border border-neutral-800">
                        <div
                          className="h-full rounded-full bg-gradient-to-r from-indigo-500 to-cyan-400"
                          style={{ width: `${Math.min(100, Math.max(2, pct))}%` }}
                        />
                      </div>
                      <span className="font-semibold text-neutral-200 tabular-nums w-8 text-right">{pct}%</span>
                    </div>
                  </td>
                  <td className="py-3 px-3">
                    {renderCell('health_status', hSt, { format: 'health-status-badge' })}
                  </td>
                  <td className="py-3 px-3 text-right font-medium text-neutral-300 tabular-nums">{delScore}%</td>
                  <td className="py-3 px-3 text-right font-medium text-neutral-300 tabular-nums">{qScore}%</td>
                  <td className="py-3 px-3 text-right font-semibold text-neutral-100 tabular-nums">{reports}</td>
                  <td className="py-3 px-3 text-neutral-400 tabular-nums font-mono text-[11px]">{tDate}</td>
                  <td className="py-3 px-3 text-right">
                    <span className="inline-flex items-center gap-1 text-xs font-semibold text-indigo-400 group-hover:text-indigo-300 group-hover:translate-x-0.5 transition-all">
                      Drill down <ChevronRight size={13} />
                    </span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

import { createContext, useContext, useMemo, useState, type ReactNode } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useSearchParams } from 'react-router-dom';
import type { FilterState } from './types';

// ---------------------------------------------------------------------------
// Filter context — URL-synced global state
// ---------------------------------------------------------------------------

type FilterContextValue = {
  filters: FilterState;
  setRange: (start: string, end: string) => void;
  setFilter: (key: keyof FilterState, value: string | undefined) => void;
};

const FilterCtx = createContext<FilterContextValue | null>(null);

function defaultRange(): { start: string; end: string } {
  const end = new Date();
  const start = new Date(end.getTime() - 30 * 24 * 60 * 60 * 1000);
  return { start: start.toISOString(), end: end.toISOString() };
}

// URL param name ↔ filter key mapping
const PARAM_MAP: Record<Exclude<keyof FilterState, 'date_range_start' | 'date_range_end'>, string> = {
  user_id:    'user',
  project_id: 'project',
  model_name: 'model',
  feature:    'feature',
};

export function FilterProvider({ children }: { children: ReactNode }) {
  const [searchParams, setSearchParams] = useSearchParams();

  const filters = useMemo<FilterState>(() => {
    const def = defaultRange();
    return {
      date_range_start: searchParams.get('start') ?? def.start,
      date_range_end:   searchParams.get('end')   ?? def.end,
      user_id:    searchParams.get('user')    ?? undefined,
      project_id: searchParams.get('project') ?? undefined,
      model_name: searchParams.get('model')   ?? undefined,
      feature:    searchParams.get('feature') ?? undefined,
    };
  }, [searchParams]);

  const setRange = (start: string, end: string) => {
    setSearchParams(prev => {
      const next = new URLSearchParams(prev);
      next.set('start', start);
      next.set('end', end);
      return next;
    });
  };

  const setFilter = (key: keyof FilterState, value: string | undefined) => {
    const paramKey = PARAM_MAP[key as keyof typeof PARAM_MAP];
    if (!paramKey) return;
    setSearchParams(prev => {
      const next = new URLSearchParams(prev);
      if (value) next.set(paramKey, value);
      else       next.delete(paramKey);
      return next;
    });
  };

  return (
    <FilterCtx.Provider value={{ filters, setRange, setFilter }}>
      {children}
    </FilterCtx.Provider>
  );
}

export function useFilters(): FilterState {
  const ctx = useContext(FilterCtx);
  if (!ctx) throw new Error('useFilters must be used inside <FilterProvider>');
  return ctx.filters;
}

export function useFilterActions() {
  const ctx = useContext(FilterCtx);
  if (!ctx) throw new Error('useFilterActions must be used inside <FilterProvider>');
  return { setRange: ctx.setRange, setFilter: ctx.setFilter };
}

// ---------------------------------------------------------------------------
// Date range presets
// ---------------------------------------------------------------------------

type Preset =
  | { kind: 'rolling'; label: string; hours: number }
  | { kind: 'ytd';     label: string };

const RANGE_PRESETS: Preset[] = [
  { kind: 'rolling', label: '24h', hours: 24 },
  { kind: 'rolling', label: '7d',  hours: 24 * 7 },
  { kind: 'rolling', label: '30d', hours: 24 * 30 },
  { kind: 'rolling', label: '90d', hours: 24 * 90 },
  { kind: 'ytd',     label: 'YTD' },
];

function computePreset(p: Preset): { start: Date; end: Date } {
  const end = new Date();
  if (p.kind === 'ytd') {
    const start = new Date(end.getFullYear(), 0, 1);
    return { start, end };
  }
  const start = new Date(end.getTime() - p.hours * 60 * 60 * 1000);
  return { start, end };
}

function detectActivePreset(filters: FilterState): string | null {
  const start = new Date(filters.date_range_start);
  const end = new Date(filters.date_range_end);
  const spanHours = (end.getTime() - start.getTime()) / (60 * 60 * 1000);
  const now = new Date();

  // YTD detection: start close to Jan 1, end close to now
  const jan1 = new Date(now.getFullYear(), 0, 1);
  if (
    Math.abs(start.getTime() - jan1.getTime()) < 60 * 60 * 1000 &&
    Math.abs(end.getTime() - now.getTime()) < 24 * 60 * 60 * 1000
  ) {
    return 'YTD';
  }
  for (const p of RANGE_PRESETS) {
    if (p.kind === 'rolling' && Math.abs(p.hours - spanHours) < 1) return p.label;
  }
  return null;
}

// ---------------------------------------------------------------------------
// Dimension dropdown — fetched from /api/dimensions/:name
// ---------------------------------------------------------------------------

interface DimensionOption { value: string; label: string; }
interface DimensionResponse { name: string; options: DimensionOption[]; }

const API_BASE =
  (typeof import.meta !== 'undefined' && import.meta.env?.VITE_DASHBOARDS_API) || '';

async function fetchDimension(name: string): Promise<DimensionResponse> {
  const res = await fetch(`${API_BASE}/api/dimensions/${name}`, { credentials: 'include' });
  if (!res.ok) throw new Error(`dimension ${name} failed (${res.status})`);
  return res.json();
}

function DimensionSelect({
  dimension, filterKey, placeholder,
}: {
  dimension: 'users' | 'projects' | 'models' | 'features';
  filterKey: keyof FilterState;
  placeholder: string;
}) {
  const filters = useFilters();
  const { setFilter } = useFilterActions();
  const current = (filters[filterKey] as string | undefined) ?? '';

  const { data } = useQuery({
    queryKey: ['dimension', dimension],
    queryFn: () => fetchDimension(dimension),
    staleTime: 60_000,
  });

  return (
    <select
      value={current}
      onChange={e => setFilter(filterKey, e.target.value || undefined)}
      className="
        bg-neutral-900 border border-neutral-800 rounded-md text-sm px-3 py-1.5
        text-neutral-200 hover:border-neutral-700 focus:outline-none
        focus:border-neutral-600 min-w-[140px] cursor-pointer
      "
    >
      <option value="">{placeholder}</option>
      {data?.options.map(o => (
        <option key={o.value} value={o.value}>{o.label}</option>
      ))}
    </select>
  );
}

// ---------------------------------------------------------------------------
// FilterBar — the top-of-dashboard filter row
// ---------------------------------------------------------------------------

export function FilterBar({ title }: { title: string }) {
  const filters = useFilters();
  const { setRange } = useFilterActions();
  const activePreset = detectActivePreset(filters);

  const selectPreset = (p: Preset) => {
    const { start, end } = computePreset(p);
    setRange(start.toISOString(), end.toISOString());
  };

  return (
    <div className="flex flex-col gap-3 mb-6">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <h1 className="text-xl font-medium text-neutral-100">{title}</h1>
        <div className="inline-flex border border-neutral-800 rounded-md overflow-hidden text-sm">
          {RANGE_PRESETS.map(p => (
            <button
              key={p.label}
              onClick={() => selectPreset(p)}
              className={
                'px-3 py-1.5 border-r border-neutral-800 last:border-r-0 transition-colors ' +
                (activePreset === p.label
                  ? 'bg-neutral-800 text-neutral-100 font-medium'
                  : 'text-neutral-400 hover:bg-neutral-900 hover:text-neutral-200')
              }
            >
              {p.label}
            </button>
          ))}
        </div>
      </div>
      <div className="flex flex-wrap gap-2">
        <DimensionSelect dimension="users"    filterKey="user_id"    placeholder="All users" />
        <DimensionSelect dimension="projects" filterKey="project_id" placeholder="All projects" />
        <DimensionSelect dimension="models"   filterKey="model_name" placeholder="All models" />
        <DimensionSelect dimension="features" filterKey="feature"    placeholder="All features" />
      </div>
    </div>
  );
}

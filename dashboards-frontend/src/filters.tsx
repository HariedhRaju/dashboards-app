import { createContext, useContext, useMemo, type ReactNode } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useSearchParams } from 'react-router-dom';
import type { FilterDropdown, FilterState } from './types';

// ---------------------------------------------------------------------------
// Filter context — URL-synced global state.
// Date range lives under ?start / ?end. Every other dropdown stores its value
// under its own `param` key directly (e.g. ?severity=P1).
// ---------------------------------------------------------------------------

type FilterContextValue = {
  filters: FilterState;
  setRange: (start: string, end: string) => void;
  setFilter: (param: string, value: string | undefined) => void;
};

const FilterCtx = createContext<FilterContextValue | null>(null);

// Reserved param names that are NOT dashboard filter dropdowns.
const RESERVED = new Set(['start', 'end']);

function defaultRange(): { start: string; end: string } {
  const end = new Date();
  const start = new Date(end.getTime() - 30 * 24 * 60 * 60 * 1000);
  return { start: start.toISOString(), end: end.toISOString() };
}

export function FilterProvider({ children }: { children: ReactNode }) {
  const [searchParams, setSearchParams] = useSearchParams();

  const filters = useMemo<FilterState>(() => {
    const def = defaultRange();
    const out: FilterState = {
      date_range_start: searchParams.get('start') ?? def.start,
      date_range_end:   searchParams.get('end')   ?? def.end,
    };
    // Every other query param becomes a filter key verbatim.
    for (const [k, v] of searchParams.entries()) {
      if (!RESERVED.has(k) && v) out[k] = v;
    }
    return out;
  }, [searchParams]);

  const setRange = (start: string, end: string) => {
    setSearchParams(prev => {
      const next = new URLSearchParams(prev);
      next.set('start', start);
      next.set('end', end);
      return next;
    });
  };

  const setFilter = (param: string, value: string | undefined) => {
    setSearchParams(prev => {
      const next = new URLSearchParams(prev);
      if (value) next.set(param, value);
      else       next.delete(param);
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
  if (p.kind === 'ytd') return { start: new Date(end.getFullYear(), 0, 1), end };
  return { start: new Date(end.getTime() - p.hours * 60 * 60 * 1000), end };
}

function detectActivePreset(filters: FilterState): string | null {
  const start = new Date(filters.date_range_start);
  const end = new Date(filters.date_range_end);
  const spanHours = (end.getTime() - start.getTime()) / (60 * 60 * 1000);
  const now = new Date();
  const jan1 = new Date(now.getFullYear(), 0, 1);
  if (
    Math.abs(start.getTime() - jan1.getTime()) < 60 * 60 * 1000 &&
    Math.abs(end.getTime() - now.getTime()) < 24 * 60 * 60 * 1000
  ) return 'YTD';
  for (const p of RANGE_PRESETS) {
    if (p.kind === 'rolling' && Math.abs(p.hours - spanHours) < 1) return p.label;
  }
  return null;
}

// ---------------------------------------------------------------------------
// Calendar range
// ---------------------------------------------------------------------------

/** `<input type="date">` wants yyyy-mm-dd in LOCAL time, not a UTC ISO slice. */
function toInputDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/**
 * Two native date inputs — which open the platform's own calendar picker, so
 * this stays keyboard-accessible and localized without shipping a date-picker
 * dependency for two fields.
 *
 * `scoped` is the real state: a dashboard can be looking at ALL the data or at
 * an explicit window, and those are different questions rather than one
 * question with a very wide default. Keeping it explicit is what lets the
 * report say "whole set" instead of inventing a range nobody chose.
 */
function CalendarRange() {
  const filters = useFilters();
  const { setRange, setFilter } = useFilterActions();
  const scoped = filters.date_scoped === '1';

  const start = toInputDate(filters.date_range_start);
  const end = toInputDate(filters.date_range_end);

  const update = (nextStart: string, nextEnd: string) => {
    if (!nextStart || !nextEnd) return;
    // End is inclusive to the reader; the API is told the inclusive dates and
    // does its own exclusive-end arithmetic, so nothing here has to guess.
    setRange(new Date(`${nextStart}T00:00:00`).toISOString(),
             new Date(`${nextEnd}T23:59:59`).toISOString());
  };

  return (
    <div className="flex items-center gap-2 flex-wrap">
      <div className="inline-flex rounded-md border border-neutral-800 overflow-hidden text-sm">
        <button
          onClick={() => setFilter('date_scoped', undefined)}
          className={
            'px-3 py-1.5 border-r border-neutral-800 transition-colors ' +
            (!scoped ? 'bg-neutral-800 text-neutral-100 font-medium'
                     : 'text-neutral-400 hover:bg-neutral-900 hover:text-neutral-200')
          }
        >
          All data
        </button>
        <button
          onClick={() => setFilter('date_scoped', '1')}
          className={
            'px-3 py-1.5 transition-colors ' +
            (scoped ? 'bg-neutral-800 text-neutral-100 font-medium'
                    : 'text-neutral-400 hover:bg-neutral-900 hover:text-neutral-200')
          }
        >
          Date range
        </button>
      </div>

      {scoped && (
        <div className="flex items-center gap-1.5 text-sm">
          <input
            type="date" value={start} max={end || undefined}
            onChange={e => update(e.target.value, end)}
            className="bg-neutral-900 border border-neutral-800 rounded-md px-2 py-1.5 text-neutral-200 focus:outline-none focus:border-neutral-600 [color-scheme:dark]"
          />
          <span className="text-neutral-600">to</span>
          <input
            type="date" value={end} min={start || undefined}
            onChange={e => update(start, e.target.value)}
            className="bg-neutral-900 border border-neutral-800 rounded-md px-2 py-1.5 text-neutral-200 focus:outline-none focus:border-neutral-600 [color-scheme:dark]"
          />
        </div>
      )}
    </div>
  );
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

function DimensionSelect({ dropdown }: { dropdown: FilterDropdown }) {
  const filters = useFilters();
  const { setFilter } = useFilterActions();
  const current = (filters[dropdown.param] as string | undefined) ?? '';

  const { data } = useQuery({
    queryKey: ['dimension', dropdown.dimension],
    queryFn: () => fetchDimension(dropdown.dimension),
    staleTime: 60_000,
  });

  return (
    <select
      value={current}
      onChange={e => setFilter(dropdown.param, e.target.value || undefined)}
      className="
        bg-neutral-900 border border-neutral-800 rounded-md text-sm px-3 py-1.5
        text-neutral-200 hover:border-neutral-700 focus:outline-none
        focus:border-neutral-600 min-w-[140px] cursor-pointer
      "
    >
      <option value="">{dropdown.placeholder}</option>
      {data?.options.map(o => (
        <option key={o.value} value={o.value}>{o.label}</option>
      ))}
    </select>
  );
}

// ---------------------------------------------------------------------------
// FilterBar — dashboard declares its dropdowns via `filterBar`
// ---------------------------------------------------------------------------

export function FilterBar({ title, dropdowns, showRange = true, showCalendar = false }: {
  title: string;
  dropdowns?: FilterDropdown[];
  /**
   * Hide the range presets on dashboards where they do nothing. On the QA
   * dashboard the snapshot is the unit of scope, so every preset resolves to
   * the same snapshot — a control that visibly changes nothing when clicked
   * reads as a broken dashboard rather than an inapplicable filter.
   */
  showRange?: boolean;
  /**
   * Show an explicit calendar range instead of the presets.
   *
   * The presets are all relative to now ("last 30 days"), which suits a live
   * telemetry dashboard and actively misleads on ingested QA data: a workbook
   * of bugs logged last September matches none of them, and every preset
   * returns an empty window. A calendar lets the reader name the period the
   * data is actually from.
   */
  showCalendar?: boolean;
}) {
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
        <h1 className="text-xl font-semibold text-neutral-100">{title}</h1>
        {showCalendar && <CalendarRange />}
        <div className={
          'inline-flex border border-neutral-800 rounded-md overflow-hidden text-sm' +
          (showRange ? '' : ' hidden')
        }>
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
      {dropdowns && dropdowns.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {dropdowns.map(d => <DimensionSelect key={d.param} dropdown={d} />)}
        </div>
      )}
    </div>
  );
}

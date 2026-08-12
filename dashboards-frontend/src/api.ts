import { useQuery, type UseQueryResult } from '@tanstack/react-query';
import { useFilters } from './filters';
import type { Format, MetricResponse } from './types';

// ---------------------------------------------------------------------------
// API base URL — override via VITE_DASHBOARDS_API or fall back to same-origin.
// ---------------------------------------------------------------------------

const API_BASE =
  (typeof import.meta !== 'undefined' && import.meta.env?.VITE_DASHBOARDS_API) ||
  '';

async function fetchMetric<T extends MetricResponse>(
  id: string,
  params: Record<string, unknown>,
  signal?: AbortSignal,
): Promise<T> {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v == null || v === '') continue;
    qs.set(k, typeof v === 'object' ? JSON.stringify(v) : String(v));
  }

  const res = await fetch(`${API_BASE}/api/metrics/${id}?${qs}`, {
    credentials: 'include',    // Send session cookies to the main app
    signal,
  });

  if (!res.ok) {
    const detail = await res.text().catch(() => '');
    throw new Error(`metric ${id} failed (${res.status}): ${detail}`);
  }
  return res.json() as Promise<T>;
}

// ---------------------------------------------------------------------------
// useMetric — the one hook every widget uses.
// ---------------------------------------------------------------------------

export function useMetric<T extends MetricResponse>(
  metricId: string,
  extra?: Record<string, unknown>,
  options?: { refetchInterval?: number },
): UseQueryResult<T, Error> {
  const filters = useFilters();
  const merged = { ...filters, ...(extra ?? {}) };

  return useQuery<T, Error>({
    queryKey: ['metric', metricId, merged],
    queryFn: ({ signal }) => fetchMetric<T>(metricId, merged, signal),
    refetchInterval: options?.refetchInterval ?? 7000,
    staleTime: 3000,
    refetchOnWindowFocus: true,
    retry: 1,
  });
}

// ---------------------------------------------------------------------------
// Number formatting — one place, called everywhere.
// ---------------------------------------------------------------------------

const compactFormatter = new Intl.NumberFormat('en-US', {
  notation: 'compact',
  maximumFractionDigits: 1,
});
const standardFormatter = new Intl.NumberFormat('en-US');
const percentFormatter = new Intl.NumberFormat('en-US', {
  style: 'percent',
  maximumFractionDigits: 1,
});
const currencyFormatter = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  maximumFractionDigits: 0,
});

export function formatValue(value: number, format: Format, compact = false): string {
  if (format === 'currency') return currencyFormatter.format(value);
  if (format === 'percent')  return percentFormatter.format(value);
  if (format === 'percent_whole') return `${value.toFixed(1)}%`;   // value already 0-100
  if (format === 'hours') {
    // Render hours human-friendly: <48h as hours, else days.
    if (value < 48) return `${value.toFixed(1)}h`;
    return `${(value / 24).toFixed(1)}d`;
  }
  return compact ? compactFormatter.format(value) : standardFormatter.format(value);
}

export function formatDelta(current: number, previous: number | null): {
  pct: number | null;
  text: string;
  direction: 'up' | 'down' | 'flat';
} {
  if (previous == null || previous === 0) {
    return { pct: null, text: '—', direction: 'flat' };
  }
  const pct = ((current - previous) / previous) * 100;
  const direction = pct > 0.5 ? 'up' : pct < -0.5 ? 'down' : 'flat';
  const sign = pct > 0 ? '+' : '';
  return { pct, text: `${sign}${pct.toFixed(1)}%`, direction };
}

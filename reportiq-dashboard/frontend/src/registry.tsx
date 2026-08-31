import type { DashboardDef } from './types';

// Registry of available dashboards.
export const registry: Record<string, () => Promise<{ default: DashboardDef }>> = {
  'report-iq': () => import('./dashboards/report-iq'),
};

export async function loadDashboard(slug: string = 'report-iq'): Promise<DashboardDef | null> {
  const loader = registry[slug] || registry['report-iq'];
  if (!loader) return null;
  return (await loader()).default;
}

/** Sync metadata for navigation and indexing */
export const dashboardIndex = [
  { slug: 'report-iq', title: 'ReportIQ — Executive Intelligence', category: 'executive' },
] as const;

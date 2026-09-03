import type { DashboardDef } from './types';

// Each entry is a dynamic import → Vite/webpack code-splits automatically.
// Adding a dashboard is one folder/file plus one line here.
export const registry: Record<string, () => Promise<{ default: DashboardDef }>> = {
  'token-usage': () => import('./dashboards/token-usage'),
  'bug-reports': () => import('./dashboards/bug-reports'),
  'report-iq':   () => import('./dashboards/report-iq'),
};

export async function loadDashboard(slug: string): Promise<DashboardDef | null> {
  const loader = registry[slug];
  if (!loader) return null;
  return (await loader()).default;
}

/** For sidebar/index navigation — sync metadata only, no dashboard code loaded. */
export const dashboardIndex = [
  { slug: 'token-usage',  title: 'Token usage', category: 'ops' },
  { slug: 'bug-reports',  title: 'Bug reports (Bug Bot)', category: 'quality' },
  { slug: 'report-iq',    title: 'ReportIQ',    category: 'executive' },
  { slug: 'common-agent', title: 'Common Agent (Bugsy × TestSmith)', category: 'insights' },
] as const;

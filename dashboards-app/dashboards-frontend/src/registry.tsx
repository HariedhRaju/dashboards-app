import type { DashboardDef } from './types';

// Each entry is a dynamic import → Vite/webpack code-splits automatically.
// Adding a dashboard is one folder/file plus one line here.
export const registry: Record<string, () => Promise<{ default: DashboardDef }>> = {
  'token-usage': () => import('./dashboards/token-usage'),

  // 'user-engagement': () => import('./dashboards/user-engagement'),
  // 'billing-overview': () => import('./dashboards/billing-overview'),
};

export async function loadDashboard(slug: string): Promise<DashboardDef | null> {
  const loader = registry[slug];
  if (!loader) return null;
  return (await loader()).default;
}

/** For sidebar/index navigation — sync metadata only, no dashboard code loaded. */
export const dashboardIndex = [
  { slug: 'token-usage', title: 'Token usage', category: 'ops' },
] as const;

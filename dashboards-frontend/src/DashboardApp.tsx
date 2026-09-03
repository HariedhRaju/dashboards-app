import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query';
import { Link, Route, Routes, useParams } from 'react-router-dom';
import { Suspense } from 'react';

import { DashboardRenderer } from './DashboardRenderer';
import { FilterProvider } from './filters';
import { dashboardIndex, loadDashboard } from './registry';

// ---------------------------------------------------------------------------
// One QueryClient for the whole dashboard app.
// ---------------------------------------------------------------------------

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 3000,
      refetchOnWindowFocus: false,
      retry: 1,
    },
  },
});

// ---------------------------------------------------------------------------
// DashboardPage — resolves slug → config → renders
// ---------------------------------------------------------------------------

import { AgentDashboardRenderer } from './AgentDashboardRenderer';
import { CommonAgentDashboard } from './CommonAgentDashboard';

function DashboardPage() {
  const { slug } = useParams<{ slug: string }>();

  if (slug === 'ai-agent') {
    return <AgentDashboardRenderer />;
  }

  if (slug === 'common-agent') {
    return <CommonAgentDashboard />;
  }

  const { data, isPending, error } = useQuery({
    queryKey: ['dashboard-def', slug],
    queryFn: () => loadDashboard(slug!),
    enabled: !!slug,
  });

  if (isPending) return <DashboardSkeleton />;
  if (error) return (
    <div className="max-w-[1400px] mx-auto p-6 text-red-400">
      Failed to load dashboard. {String(error)}
    </div>
  );
  if (!data) return (
    <div className="max-w-[1400px] mx-auto p-6 text-neutral-400">
      Dashboard <code className="text-neutral-200">{slug}</code> not found.
    </div>
  );

  return <DashboardRenderer def={data} />;
}

function DashboardSkeleton() {
  return (
    <div className="max-w-[1400px] mx-auto p-6">
      <div className="h-6 w-40 bg-neutral-800/60 rounded animate-pulse mb-5" />
      <div className="grid grid-cols-12 gap-3" style={{ gridAutoRows: '120px' }}>
        {[3, 3, 3, 3].map((w, i) => (
          <div key={i} className="bg-neutral-900/60 rounded-lg animate-pulse"
               style={{ gridColumn: `span ${w} / span ${w}` }} />
        ))}
        <div className="bg-neutral-900/60 rounded-xl animate-pulse"
             style={{ gridColumn: 'span 8 / span 8', gridRow: 'span 3 / span 3' }} />
        <div className="bg-neutral-900/60 rounded-xl animate-pulse"
             style={{ gridColumn: 'span 4 / span 4', gridRow: 'span 3 / span 3' }} />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// DashboardIndex — landing page showing available dashboards
// ---------------------------------------------------------------------------

function DashboardIndex() {
  return (
    <div className="max-w-[1400px] mx-auto p-6">
      <h1 className="text-xl font-medium text-neutral-100 mb-4">Analytics</h1>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        {dashboardIndex.map(d => (
          <Link
            key={d.slug}
            to={d.slug}
            className="bg-neutral-900 border border-neutral-800 rounded-xl p-4 hover:border-neutral-700 transition-colors"
          >
            <div className="text-xs text-neutral-500 uppercase tracking-wide">{d.category}</div>
            <div className="text-sm font-medium mt-1 text-neutral-200">{d.title}</div>
          </Link>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// DashboardApp — export this and mount it under /analytics/* in the main app.
// ---------------------------------------------------------------------------

export default function DashboardApp() {
  return (
    <QueryClientProvider client={queryClient}>
      <FilterProvider>
        <Suspense fallback={<DashboardSkeleton />}>
          <Routes>
            <Route index element={<DashboardIndex />} />
            <Route path=":slug" element={<DashboardPage />} />
          </Routes>
        </Suspense>
      </FilterProvider>
    </QueryClientProvider>
  );
}

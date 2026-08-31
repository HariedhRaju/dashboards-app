import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query';
import { Route, Routes, useParams } from 'react-router-dom';
import { Suspense } from 'react';

import { DashboardRenderer } from './DashboardRenderer';
import { FilterProvider } from './filters';
import { loadDashboard } from './registry';

// ---------------------------------------------------------------------------
// One QueryClient for the dashboard app.
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
// DashboardPage — resolves slug (defaults to 'report-iq') → renders
// ---------------------------------------------------------------------------

function DashboardPage() {
  const { slug = 'report-iq' } = useParams<{ slug?: string }>();

  const { data, isPending, error } = useQuery({
    queryKey: ['dashboard-def', slug],
    queryFn: () => loadDashboard(slug),
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
        {[3, 2, 2, 2, 3].map((w, i) => (
          <div key={i} className="bg-neutral-900/60 rounded-lg animate-pulse"
               style={{ gridColumn: `span ${w} / span ${w}` }} />
        ))}
        <div className="bg-neutral-900/60 rounded-xl animate-pulse"
             style={{ gridColumn: 'span 8 / span 8', gridRow: 'span 4 / span 4' }} />
        <div className="bg-neutral-900/60 rounded-xl animate-pulse"
             style={{ gridColumn: 'span 4 / span 4', gridRow: 'span 4 / span 4' }} />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// DashboardApp — Primary export for standalone app or mounting into host app
// ---------------------------------------------------------------------------

export default function DashboardApp() {
  return (
    <QueryClientProvider client={queryClient}>
      <FilterProvider>
        <Suspense fallback={<DashboardSkeleton />}>
          <Routes>
            <Route index element={<DashboardPage />} />
            <Route path=":slug" element={<DashboardPage />} />
          </Routes>
        </Suspense>
      </FilterProvider>
    </QueryClientProvider>
  );
}

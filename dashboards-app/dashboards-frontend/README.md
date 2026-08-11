# @yourorg/dashboards (frontend)

Config-driven React dashboard package. Mount it at `/analytics/*` in the main
app; end users see a fully-polling, code-split dashboard experience without
the main app knowing anything about charts.

## Structure

```
src/
├── index.ts                Public exports
├── DashboardApp.tsx        Root: QueryClient + Router + FilterProvider
├── DashboardRenderer.tsx   Config → grid → widgets
├── widgets.tsx             All 5 widget primitives in one file
├── filters.tsx             FilterProvider + FilterBar UI
├── api.ts                  API client + useMetric hook + formatters
├── registry.tsx            Dashboard registry (lazy-loaded)
├── types.ts                Response shapes + config types
├── vite-env.d.ts           Vite env types
└── dashboards/
    └── token-usage.ts      First dashboard config (pure data)
```

**8 files total.** Widgets are together because they share loading/error
patterns and rarely change independently; splitting them adds ceremony
without adding clarity.

## Wiring into the main app

Assuming your main React app uses React Router:

```tsx
// main-app/src/routes.tsx
import { lazy, Suspense } from 'react';
import { Route } from 'react-router-dom';

const DashboardApp = lazy(() => import('@yourorg/dashboards'));

<Route
  path="/analytics/*"
  element={
    <Suspense fallback={<div>Loading…</div>}>
      <DashboardApp />
    </Suspense>
  }
/>
```

That's it. The dashboard package brings its own router, its own
`QueryClientProvider`, and its own `FilterProvider`.

## Environment

Set `VITE_DASHBOARDS_API` if your API is on a different origin than the main
app. Falls back to same-origin `/api/...` calls which work when both are
served from the same host.

## Adding a new dashboard

1. Create `src/dashboards/<slug>.ts` — a `DashboardDef` object, no JSX.
2. Add one line to `src/registry.tsx`:
   ```ts
   '<slug>': () => import('./dashboards/<slug>'),
   ```
3. Add one line to `dashboardIndex` for the landing page.

Done. Vite code-splits the file automatically.

## Adding a new widget type

1. Add a variant to the `Widget` union in `types.ts`.
2. Write the component in `widgets.tsx`.
3. Add one case to the `WidgetRenderer` switch in `DashboardRenderer.tsx`.

Every existing dashboard can now use it.

## What the token-usage dashboard uses

Nine metric endpoints, mapped to widgets:

| Metric endpoint | Widget |
|---|---|
| `tokens.total` | MetricWidget |
| `tokens.calls.count` | MetricWidget |
| `tokens.avg_per_call` | MetricWidget |
| `tokens.users.active` | MetricWidget |
| `tokens.timeseries` | TimeseriesWidget (stacked area) |
| `tokens.by_model` | DonutWidget |
| `tokens.by_feature` | BarWidget |
| `tokens.by_user` | BarWidget |
| `tokens.top_consumers` | TableWidget (sortable, paginated) |

## Dependencies

- **React 18+** — peer dependency
- **TanStack Query v5** — data fetching and polling
- **Recharts** — chart rendering
- **React Router v6** — routing between dashboards
- **date-fns** — date formatting on axes
- **clsx** — conditional classNames
- **Tailwind** — the components use Tailwind utility classes. Make sure the
  main app's Tailwind config includes this package in `content:`.

## Design system notes

- **Palette**: 8-color categorical, with `#B4B2A9` reserved for "Other"
  buckets. Semantic green/red only for deltas.
- **Numerics**: every displayed number uses `font-variant-numeric: tabular-nums`
  so digits align vertically.
- **Card**: white background, `border-neutral-200`, `rounded-xl`, `p-4`.
- **KPI card**: neutral-50 background (subtler than white-with-border).
- **Loading**: skeleton animation matching the eventual widget shape.
- **Errors**: inline red banner with retry button — never blank space.

## Verification

The package was type-checked (`tsc --noEmit`, zero errors) and built with
Vite (produces `index.js` + one chunk per dashboard for code-splitting).

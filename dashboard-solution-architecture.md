# Dashboard Application — Solution Architecture & Action Plan

**Status:** Approved for implementation
**Document version:** 1.0
**Last updated:** August 2026

---

## 1. Overview

We are building an **embedded analytics module** for our existing multi-tenant SaaS product. The module surfaces multiple preset dashboards to end customers under a dedicated `/analytics` section of the main application. Data is served near-real-time (5–10 second refresh) from the operational Postgres database, scoped per tenant, and rendered through a small library of chart primitives that are configured via metric definitions authored by analysts and implemented by engineers.

The architecture is designed to scale to dozens of dashboards and hundreds of metrics without proportional engineering cost. This is achieved by separating four concerns cleanly: chart primitives, metric definitions, dashboard configurations, and rendering plumbing. Each lives in exactly one place and changes independently.

---

## 2. Context & Requirements

### Product context

- Customer-facing SaaS, multi-tenant
- Embedded inside a large existing React application
- Full-page dedicated Analytics section (not iframe panels or contextual widgets)
- Multiple preset dashboards, expected to grow to 20–40 over time
- End users cannot build custom dashboards; they filter and adjust date ranges only
- Same engineering team owns both the main app and the dashboard module

### Data characteristics

- Data source: operational Postgres (no data warehouse today)
- Mixed tenant scale expected — power-law distribution with some whale tenants
- Refresh cadence: near real-time (5–10s polling from the client)
- Metrics defined by business analysts, implemented by engineers

### Non-functional requirements

- Tenant isolation must be strong — defense in depth
- One tenant's queries cannot degrade another's experience
- New dashboards should be addable without touching shared code paths
- New metrics should be addable without touching frontend code
- Failure on one widget must not blank the entire dashboard
- Bundle sizes must not grow proportionally with dashboard count

---

## 3. Solution Architecture

### 3.1 System View

```
┌──────────────────────────────────────────────────────────────┐
│                    Main React Application                     │
│                                                               │
│   Route /analytics/*  ─→  lazy import Dashboard Package      │
│                                                               │
│   ┌─────────────────────────────────────────────────────┐    │
│   │           @yourorg/dashboards package               │    │
│   │  FilterProvider · Registry · DashboardRenderer      │    │
│   │  Chart primitives · Widget renderer · useMetric     │    │
│   └───────────────────────┬─────────────────────────────┘    │
└───────────────────────────┼──────────────────────────────────┘
                            │  HTTPS  ·  Bearer JWT
                            ▼
┌──────────────────────────────────────────────────────────────┐
│               dashboards-api  (Fastify + Drizzle)             │
│                                                               │
│  auth plugin  →  rate limit  →  cache lookup  →  db query    │
│  JWT verify     (per tenant)     (Redis 5s)     (Drizzle)     │
└───────────────────────────┬──────────────────────────────────┘
                            │
                  ┌─────────┴──────────┐
                  ▼                    ▼
              ┌────────┐         ┌────────────┐
              │ Redis  │         │  Postgres  │
              │ cache  │         │  read repl │
              └────────┘         │ + mat views│
                                 └────────────┘
```

### 3.2 Integration Model

The dashboard module lives in the same monorepo as the main application and is imported as a lazy-loaded React package. The main app mounts it at `/analytics/*` with a single line of routing.

**Decision:** monorepo package. Not iframe. Not Module Federation.

Rationale: iframe's benefits (tech-stack independence, deploy isolation, failure isolation) don't apply because the same team owns both apps and both are React. Module Federation adds coordination overhead that pays off at multi-team scale, not at ours. A lazy-loaded package gives native React composition, shared auth context, shared TypeScript types, and independent bundle isolation via Vite code-splitting. Migration to Module Federation later is straightforward if organizational needs change.

### 3.3 Frontend Architecture

**Stack:** React + Vite + TypeScript, TanStack Query for data fetching, Tremor for dashboard components, Tailwind for styling.

**Layered design.** The frontend is deliberately structured in four layers, each with a distinct responsibility:

1. **Primitives** — a small fixed set of chart components (`MetricCard`, `TimeSeries`, `Bar`, `Donut`, `Table`, `Heatmap`, `Funnel`). Written and polished once.
2. **Widgets** — thin renderers that pair a primitive with a metric ID and a data-fetching hook. Not tied to any specific dashboard.
3. **Dashboards** — configuration files (`.ts`) that declare layout and which widgets to place where. No JSX in dashboard files.
4. **Renderer** — a single component that takes a dashboard config and renders the whole thing. Written once.

The payoff of this layering: adding a new dashboard is a config file plus one line in the registry. Adding a new metric is server-side only. Adding a new chart type requires a new primitive, one widget, and one case in the renderer's switch — done once, available everywhere afterward.

**Rendering approach.** Dashboards are defined as `DashboardDef` objects with a slug, title, permissions, filter list, and layout array. The `DashboardRenderer` walks the layout and delegates to `WidgetRenderer` for each cell. `WidgetRenderer` is a discriminated-union switch that instantiates the correct widget. Each widget calls `useMetric(metricId, extraFilters?)`, which handles fetching, caching, refetch scheduling, and error/loading states.

**Filter management.** Global filter state (date range, region, product line, etc.) lives in a `FilterProvider` at the top of the dashboard tree. Filter values are included in every widget's `useMetric` query key, so filter changes trigger refetches automatically. Filter state is bidirectionally synced to URL search params, making filter states bookmarkable and browser-back navigable.

### 3.4 Backend Architecture

**Stack:** Fastify (Node.js) + Drizzle ORM + native `pg` driver.

**Metrics registry.** The metrics registry is the single source of truth for what data the dashboard app can serve. Every metric is a self-contained definition: filter schema, response kind (`scalar` / `series` / `group` / `table`), cache TTL, and the query function itself.

The registry is a plain TypeScript object keyed by metric ID. Metric IDs follow a strict namespaced convention: `<domain>.<entity>.<measure>[.<qualifier>]` — for example `sales.revenue.gross`, `customer.churn.30d`.

**API surface.** The API exposes a single generic endpoint: `GET /api/metrics/:id`. This endpoint:

1. Looks up the metric by ID (404 if unknown).
2. Validates query parameters against the metric's declared filter schema.
3. Checks Redis cache using a key hashed from `(tenant_id, metric_id, filters, time_bucket)`.
4. On miss, acquires a tenant-scoped Postgres connection and runs the metric's query function.
5. Stores the result in Redis with the metric's declared TTL.
6. Returns the typed response.

One endpoint serves every metric. Adding metrics does not add API surface area.

**Request lifecycle.**

```
Request  →  JWT verification         (tenant/user context attached)
         →  Per-tenant rate limit    (Redis token bucket)
         →  Query param validation   (Zod, per-metric schema)
         →  Redis cache lookup       (hit → return)
         →  Postgres query           (tenant-scoped connection, RLS session var)
         →  Redis cache write        (with metric's TTL)
         →  Typed JSON response
```

### 3.5 Data Layer & Multi-Tenancy

**Isolation strategy: shared schema + `tenant_id` column + Row-Level Security.**

Every tenant-scoped table has a `tenant_id` column and an RLS policy that reads from a Postgres session variable:

```sql
ALTER TABLE <table> ENABLE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON <table>
  USING (tenant_id = current_setting('app.tenant_id')::uuid);

CREATE INDEX ON <table> (tenant_id, <hot_columns>);
```

On every API request, the `db` plugin acquires a connection from the pool and executes `SET LOCAL app.tenant_id = '<from-jwt>'` before running the metric's query. RLS acts as a safety net — even if a query is missing an explicit `WHERE tenant_id = ...`, the DB rejects cross-tenant leakage.

All tenant-scoped indexes must be composite indexes leading with `tenant_id`.

**Read replica for analytics traffic.** A dedicated Postgres read replica serves all dashboard traffic. This is a critical isolation measure — analytical queries never touch the primary that serves the main application's transactional traffic. Streaming replication is used; sub-second replication lag is acceptable for a 5–10s refresh dashboard.

**Materialized views.** For the 5–10 most expensive metrics (large group-bys, complex window functions, expensive joins), materialized views are precomputed and refreshed on a schedule of 30–60 seconds. The metric's query function then reads from the materialized view rather than the base tables.

**Caching layer.** Redis sits in front of the query layer. Cache keys are hashed from `(tenant_id, metric_id, filters, time_bucket)`. Default TTL is 5 seconds; each metric can override. This means even with 100 users on the same dashboard, the DB sees one query per unique (tenant, metric, filter, 5s-bucket) combination.

**Defensive settings.**

- `statement_timeout = '5s'` on the analytics DB role — runaway queries die, they don't cascade.
- Separate PgBouncer pool with a hard connection cap for analytics traffic — noisy neighbors have bounded blast radius.
- Per-tenant rate limiting in Redis — abuse or misuse cannot degrade shared resources.

### 3.6 Authentication & Authorization

The dashboard module inherits authentication from the main application entirely. It has no login flow of its own.

- Main app's `AuthProvider` sits above `/analytics/*` in the React tree.
- Dashboard package uses the same `useAuth()` hook to access the current JWT.
- Dashboard API validates the same JWT the main app issues (shared signing key).
- The JWT carries `tenant_id`, `user_id`, and roles/permissions.

**Authorization.** Each dashboard config declares `requires: [...permissions]`. The `DashboardPage` component checks the current user's permissions against this list before rendering; missing permissions produce a "no access" placeholder rather than an error.

---

## 4. The Metrics Model

### 4.1 What a Metric Is

A metric is not a column or a query. It is a **named, versioned, owned business measurement** with a formal definition. Every metric has:

- A stable ID (`sales.revenue.gross`)
- A business definition in plain English
- A source table and formula
- A time column and supported grains (hour / day / week / month)
- A list of dimensions it can be sliced by
- A display format and "good direction"
- A named owner
- A cache TTL

### 4.2 Workflow

1. **Analyst** identifies a business measurement dashboards need, and completes the metric spec template.
2. **Engineer** reviews the spec, implements the query in the metrics registry, and validates against the analyst's provided sample value.
3. **Metric** ships with the next deploy and becomes available to every dashboard by ID reference.
4. **Any dashboard** can now reference the metric in its layout config — no additional plumbing required.

### 4.3 Metric Spec Template

Every new metric request must be documented in this shape before implementation:

```
Metric ID:         <domain>.<entity>.<measure>
Title:             (human-readable)
Owner:             (team or person)
Business meaning:  (one paragraph)

Source table(s):   (Postgres tables involved)
Formula:           (plain-English or SQL sketch)
Time column:       (which column drives time filtering)
Time grains:       [day, week, month, ...]

Dimensions:        [region, product_line, ...]

Format:            currency | number | percent
Good direction:    up | down | neutral
Expected range:    (sanity check on plausible values)

Sample value:      (for tenant X on date Y, should be ~Z)
```

The **sample value** line is not optional. It is how the analyst pre-validates the metric before it hits production. When the engineer's implementation disagrees with the sample value, someone catches the bug before it ships. This one habit prevents most metric errors in embedded analytics.

### 4.4 Governance Principles

- **Naming convention** enforced by lint rule: `<domain>.<entity>.<measure>[.<qualifier>]`.
- **Ownership** required in the metric definition — no unowned metrics allowed.
- **Metric catalog** — an in-app page listing every registered metric, its definition, its owner, and which dashboards use it. Analysts consult this before proposing new metrics to prevent duplicates.
- **Deprecation, not deletion** — metrics can be marked deprecated with a pointer to a successor. Dashboards using deprecated metrics show a warning badge. Deletion follows a grace period.
- **Snapshot tests** for the top 20 metrics against known-good values, catching silent breakage when someone edits a query.

---

## 5. Key Design Decisions

| Decision | Choice | Rationale | Rejected Alternatives |
|---|---|---|---|
| Integration model | Monorepo lazy-loaded package | Same team, same stack, no independent-deploy need | iframe (unnecessary isolation cost); Module Federation (coordination overhead) |
| Frontend stack | React + Vite + Tremor + TanStack Query | Tremor is purpose-built for dashboards; TanStack Query solves polling elegantly | Custom Recharts wrappers (more work); Chart.js (weaker React story) |
| Backend framework | Fastify | Fast, first-class TypeScript, plugin model fits auth/tenant scoping | Express (weaker types, slower); Next.js API routes (couples frontend/backend deploys) |
| ORM | Drizzle | Close to SQL, transparent query plans, tree-shakable | Prisma (hides SQL, slower cold starts); raw SQL (loses type safety) |
| Tenant isolation | Shared schema + RLS + session variable | Scales to thousands of tenants, low ops cost, defense-in-depth | Schema-per-tenant (painful past ~100 tenants); DB-per-tenant (ops overhead) |
| Auth model | Inherited from main app via shared React context | Same team, same app tree, simplest possible | Signed-token exchange (unnecessary for embedded same-tree case) |
| Data source | Read replica of operational Postgres | Zero warehouse cost; isolates analytical load from primary | Warehouse (unnecessary complexity now); primary DB directly (would degrade main app) |
| Freshness mechanism | Client polling (7s) + Redis cache (5s) | Simple, robust, "live enough" for the requirement | WebSockets (unneeded complexity); SSE (marginal gain) |
| Dashboard authoring | Config-driven, engineer-owned | Matches team structure; keeps quality high | Analyst-authored PRs (governance risk); UI builder (build cost) |
| Cache TTL | 5 seconds per metric (overridable) | Bounds DB load; imperceptible to users | Longer TTL (staleness perceived); shorter (defeats purpose) |

---

## 6. Action Plan — Phased Rollout

### Phase 0 — Foundations (Weeks 1–2)

**Goal:** Working end-to-end pipeline with one dummy dashboard.

- Monorepo structure with `apps/main-app`, `packages/dashboards`, `services/dashboards-api`, `packages/shared`, `packages/db`.
- Postgres read replica provisioned and reachable from the API.
- Redis provisioned.
- PgBouncer pool for the API with hard connection cap.
- Fastify skeleton with `auth`, `db`, `cache`, and `rateLimit` plugins.
- RLS enabled on one pilot table; `SET LOCAL app.tenant_id` verified end-to-end.
- `statement_timeout = '5s'` set on the analytics role.
- Shared contracts package with `scalar`, `series`, and `group` response schemas.
- Dashboard package skeleton: `DashboardApp`, `FilterProvider`, `useMetric`, one `MetricWidget`.
- Main app mounts `/analytics/*` → lazy-loaded `DashboardApp`.
- One dummy metric (`hello.count`) and one dummy dashboard rendering it.

**Exit criteria:** an engineer opens `/analytics/hello`, sees a live KPI card polling every 7s, backed by a Redis-cached Postgres query on the read replica, scoped to their tenant via RLS.

### Phase 1 — First Real Dashboards (Weeks 3–6)

**Goal:** Ship the first 2–3 production dashboards with real analyst-defined metrics.

- Metric spec template published; first 8–12 metrics documented by analysts.
- Metrics registered in the backend registry, each validated against its analyst-provided sample value.
- All primitives implemented (`MetricCard`, `TimeSeries`, `Bar`, `Donut`, `Table`) with skeleton, error, and empty states.
- Design system decisions locked: color palette (one accent, semantic status colors, neutrals), typography (tabular numerics), density, spacing scale.
- Filter bar (date range + 1–2 dashboard-specific filters).
- URL sync for filters.
- Registry pattern in place; first 2–3 dashboards live.
- Error boundaries around every widget.
- Snapshot tests for the top metrics.

**Exit criteria:** first three dashboards demoed to product and analyst stakeholders; performance under load tested with realistic tenant data.

### Phase 2 — Scale-Up (Weeks 7–10)

**Goal:** Enable rapid dashboard authoring; harden performance under load.

- Materialized views identified for the 5–10 most expensive metrics; refresh scheduler in place.
- Metric catalog UI (list of all registered metrics with definitions, owners, and usage).
- Per-tenant rate limiting in Redis.
- Sidebar navigation with grouping and search (Cmd+K palette).
- Favorites and recents for end users.
- Load testing with a realistic tenant mix (small + medium + whale).
- Observability: metrics on cache hit rate, p95 API latency, DB query duration, per-tenant query volume.
- Runbook: how to diagnose slow dashboards; how to add a materialized view; how to onboard a new metric.

**Exit criteria:** the team can ship a new dashboard in under a week end-to-end; the system holds up to 10× current load in staging.

### Phase 3 — Steady State (Ongoing)

- Continuous addition of dashboards and metrics through the documented workflow.
- Deprecation lifecycle actively used for retired metrics.
- Periodic review of cache hit rates and materialized view coverage.
- Consider TimescaleDB adoption if time-series workload grows significantly.
- Re-evaluate warehouse adoption (Snowflake / BigQuery / ClickHouse) if analytical queries begin to dominate replica capacity or if cross-source joins become common.

---

## 7. Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Analytical queries degrade the main app's transactional performance | Medium | High | Read replica isolation (Phase 0); statement timeouts; separate connection pool with hard cap |
| Whale tenant runs a heavy query that starves others | Medium | Medium | Per-tenant rate limiting; statement timeout; materialized views for heavy metrics |
| Metric proliferation without governance leads to duplication and confusion | High over time | Medium | Naming convention enforced by lint; ownership required; metric catalog UI; deprecation lifecycle |
| Cross-tenant data leak via a bug in a query | Low | Very High | RLS as safety net beneath explicit `WHERE tenant_id`; snapshot tests; code review checklist |
| Engineering becomes a bottleneck on metric requests | Medium | Medium | Track turnaround time; consider analyst-authored PRs for well-scoped metrics in Phase 3 |
| Dashboard bundle grows large as dashboard count increases | High | Low | Vite code-splitting per dashboard is automatic; monitor bundle sizes; enforce lazy imports |
| One broken widget blanks the entire dashboard | Medium | Medium | Error boundaries per widget; explicit error state UI in every widget |
| Replica lag exceeds acceptable staleness | Low | Low | Monitor replication lag; alert if >10s; fall back to primary for time-critical metrics |

---

## 8. Appendix A — Directory Structure

```
your-org/
├── apps/
│   └── main-app/                    Existing React application
│       └── src/routes.tsx           Mounts /analytics/* lazy
│
├── packages/
│   ├── dashboards/                  The dashboard app as a package
│   │   └── src/
│   │       ├── DashboardApp.tsx     Root: QueryClientProvider + inner router
│   │       ├── DashboardRenderer.tsx
│   │       ├── registry.ts
│   │       ├── dashboards/          One file per dashboard (config only)
│   │       ├── widgets/             MetricWidget, TimeseriesWidget, ...
│   │       ├── primitives/          Chart components (Tremor-wrapped)
│   │       └── lib/                 useMetric, filters, api client
│   │
│   ├── auth/                        Shared auth context
│   ├── ui/                          Shared design system
│   ├── shared/                      Zod schemas, contract types
│   └── db/                          Drizzle schema and migrations
│
├── services/
│   └── dashboards-api/              Fastify backend
│       └── src/
│           ├── plugins/             auth, db, cache, rateLimit
│           ├── routes/metrics.ts    The single generic endpoint
│           ├── metrics/             All metric definitions
│           └── lib/defineMetric.ts
│
└── infra/                           IaC for Postgres, replica, Redis, PgBouncer
```

## 9. Appendix B — Response Shape Contract

Every metric returns one of these shapes; every widget consumes one:

- `scalar` → `MetricWidget` (single number, optional previous-period comparison)
- `series` → `TimeseriesWidget` (array of time-value points)
- `group` → `DonutWidget`, `BarWidget` (array of key-value pairs)
- `table` → `TableWidget` (paginated rows)

New response shapes should be added conservatively; each requires a new primitive component.

## 10. References

- Tremor: https://www.tremor.so/
- TanStack Query: https://tanstack.com/query
- Drizzle ORM: https://orm.drizzle.team/
- Postgres RLS: https://www.postgresql.org/docs/current/ddl-rowsecurity.html
- Fastify: https://fastify.dev/
- Vite: https://vitejs.dev/

---

*This document captures the architecture decided during the design phase. It should be treated as living — update it when meaningful decisions change, and record the rationale for the change in section 5.*

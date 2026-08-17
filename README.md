# Dashboards App

Config-driven analytics dashboards. FastAPI backend + React frontend, running
locally against Postgres and Redis.

## What's in this zip

```
dashboards-app/
├── main.py                            FastAPI host app
├── requirements.txt                   Python dependencies
├── dashboards/                        Backend package (2 files)
│   ├── __init__.py                    All infra: db, cache, filters, registry, router
│   └── metrics.py                     The 9 token_usage metrics
├── dashboards-frontend/               React package
│   ├── package.json
│   ├── vite.config.js
│   ├── tailwind.config.js
│   ├── postcss.config.js
│   ├── tsconfig.json
│   ├── index.html                     Dev harness HTML
│   ├── dev/                           Dev harness entry
│   │   ├── main.tsx
│   │   └── index.css
│   ├── src/                           The actual dashboard package
│   │   ├── DashboardApp.tsx
│   │   ├── DashboardRenderer.tsx
│   │   ├── widgets.tsx                All 5 widget primitives
│   │   ├── api.ts                     useMetric hook + formatters
│   │   ├── filters.tsx                FilterProvider + FilterBar UI
│   │   ├── registry.tsx               Dashboard registry
│   │   ├── types.ts
│   │   ├── index.ts
│   │   ├── vite-env.d.ts
│   │   └── dashboards/
│   │       └── token-usage.ts         The first dashboard config
│   └── README.md                      Frontend-specific notes
├── setup/
│   ├── schema.sql                     Create the tables + indexes
│   └── seed.sql                       10 users, 5 projects, 5000 fake rows
└── dashboard-solution-architecture.md The full architecture document
```

---

## Windows setup

Prerequisites (install once):

1. **Python 3.11+** — https://www.python.org/downloads/
   During install, **check "Add python.exe to PATH"**.
2. **Node.js 20 LTS** — https://nodejs.org/
3. **PostgreSQL 15 or 16** — https://www.postgresql.org/download/windows/
   Remember the `postgres` superuser password you set.
4. **Memurai** — https://www.memurai.com/get-memurai
   Redis-compatible Windows service. Runs on port 6379.
5. **Git + a code editor** (VS Code recommended).

Verify:

```powershell
python --version
node --version
psql --version
Get-Service Memurai   # should say Running
```

---

### 1. Extract the zip

Unzip somewhere like `C:\dev\dashboards-app`. Open PowerShell and:

```powershell
cd C:\dev\dashboards-app
```

---

### 2. Create the database

```powershell
psql -U postgres -c "CREATE DATABASE dashboards_dev;"
psql -U postgres -d dashboards_dev -f setup/schema.sql
psql -U postgres -d dashboards_dev -f setup/seed.sql
```

**Upgrading from an earlier version?** The seed now wipes existing data before
re-inserting, and the schema adds `users.email` and `projects.code` if missing.
Just run the same three commands again — safe.

**Bug reports dashboard** — a second dashboard with its own tables. Set it up with:

```powershell
psql -U postgres -d dashboards_dev -f setup/bug_schema.sql
psql -U postgres -d dashboards_dev -f setup/bug_seed.sql
```

This creates `bug_users`, `bug_projects`, `bug_reports` (separate from the token
tables) and seeds ~15,000 bug reports over 18 months. Access it at
`/analytics/bug-reports`.

**Test case generation dashboard** — a third dashboard with two tables
(`generation_runs` + `test_cases`). Set it up with:

```powershell
psql -U postgres -d dashboards_dev -f setup/testcase_schema.sql
psql -U postgres -d dashboards_dev -f setup/testcase_seed.sql
```

This seeds 256 generation runs and ~6,000 test cases over 12 months, with
realistic priority drift, schema failures, and coverage gaps. Access it at
`/analytics/test-cases`. To regenerate the seed with fresh random data, run
`python setup/gen_testcase_seed.py > setup/testcase_seed.sql`.

---

### 3. Backend

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

If PowerShell blocks the activation script:

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

Then re-run the Activate line. Your prompt should show `(.venv)`.

```powershell
pip install -r requirements.txt
```

Set the env vars (replace `YOUR_PASSWORD`):

```powershell
$env:DASHBOARDS_REPLICA_DSN = "postgresql://postgres:YOUR_PASSWORD@localhost:5432/dashboards_dev"
$env:REDIS_URL = "redis://localhost:6379/0"
```

Start it:

```powershell
uvicorn main:app --reload --port 8000
```

Leave this window open. In a **new** PowerShell tab, sanity-check:

```powershell
curl http://localhost:8000/api/metrics
```

You should see JSON listing all 9 registered metrics.

---

### 4. Frontend

In another new PowerShell tab:

```powershell
cd C:\dev\dashboards-app\dashboards-frontend
npm install
npm run dev
```

Open http://localhost:5173/analytics in your browser.

You should see the Analytics index page. Click **Token usage** to see the full
dashboard: 4 KPI cards up top, stacked-area time series, donut, two bar charts,
and a paginated table. Toggle the range (24h / 7d / 30d / 90d) — the URL updates
and every widget refetches.

---

## What's running

| Process   | Port | Purpose               |
|-----------|------|-----------------------|
| Memurai   | 6379 | Redis cache           |
| Postgres  | 5432 | Database              |
| Uvicorn   | 8000 | FastAPI backend       |
| Vite      | 5173 | Frontend dev server   |

---

## Common gotchas

**"psycopg2 install fails."** You installed `psycopg2-binary` — the pre-compiled
wheel. If pip tried to install `psycopg2` (no `-binary`), it fails without Visual
C++ build tools. `requirements.txt` uses the right one.

**"Connection refused" from FastAPI.** Postgres service might not be running:
`Get-Service postgresql*` should show `Running`. Start it with
`Start-Service postgresql-x64-16` (adjust version number).

**Redis connection errors.** Memurai isn't running: `Start-Service Memurai`.

**CORS errors in browser console.** The Vite proxy handles this by default. If
you disabled it, add `http://localhost:5173` to `allow_origins` in `main.py`
(it's already there).

**PowerShell won't run `Activate.ps1`.** Execution policy — the one-line fix is
`Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned`.

**Env vars gone after closing PowerShell.** They're per-session. For persistence,
use `[Environment]::SetEnvironmentVariable('DASHBOARDS_REPLICA_DSN', '...', 'User')`.

**Frontend shows "Dashboard not found."** URL path issue — the dev harness uses
`basename="/analytics"`, so visit `http://localhost:5173/analytics`, not `/`.

---

## Next steps

- **Read** `dashboard-solution-architecture.md` for the full design rationale
  (why monorepo instead of iframe, why RLS as safety net, why metrics registry
  pattern, etc.).
- **Read** `dashboards-frontend/README.md` for the frontend-specific notes.
- **Add a metric:** open `dashboards/metrics.py`, append a function decorated
  with `@register_metric`. Done.
- **Add a dashboard:** create `dashboards-frontend/src/dashboards/<slug>.ts`
  (pure config), add one line to `registry.tsx`.

For a full walkthrough of the design decisions and phased rollout plan, see the
architecture document at the root of this zip.

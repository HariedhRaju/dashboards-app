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

**QA insights (reporting agent)** — a fourth dashboard, fed by an agent rather
than a seed script. Create its tables with:

```powershell
psql -U postgres -d dashboards_dev -f setup/qa_schema.sql
```

There is no seed file: the agent populates it by ingesting a real QA workbook
or reading an existing Postgres table. Access it at `/analytics/qa-insights`.
See **The QA agent** below.

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

## The QA agent

`agent/` turns a QA workbook — or an existing Postgres table — into a
normalized snapshot, a set of ranked findings, and a narrated executive
summary. The `qa-insights` dashboard renders what it produces.

```
sources/   fetch      .xlsx upload, or read a Postgres table directly
ingest/    normalize  probe sheets -> map columns -> canonical records
store/     persist    one immutable snapshot in Postgres
insights/  reason     deterministic findings, then optional model narration
```

**The ordering is the design.** Every number the agent reports is computed in
SQL or Python before a model sees anything; the model is only ever asked to
narrate figures that are already correct, and the health verdict is decided by
rule rather than by the model. With no model configured the dashboard is fully
functional — it loses prose, not data.

### Ingest a workbook

```powershell
curl.exe -X POST -F "file=@C:\path\to\workbook.xlsx" http://localhost:4100/api/qa/ingest
curl.exe -X POST http://localhost:4100/api/qa/analyze
```

Then open `http://localhost:4099/analytics/qa-insights`.

The ingest layer is schema-agnostic. It decides what each sheet is by scoring
its structure and its values, not by matching known filenames, so a workbook
with renamed columns or a counter block above the header still parses. What it
cannot resolve it reports rather than guesses — unresolved columns and
unparseable values both surface as findings on the dashboard.

### Ingest from Postgres

```powershell
curl.exe -X POST -H "Content-Type: application/json" -d '{}' `
  http://localhost:4100/api/qa/ingest/postgres
```

With an empty body this reads the app's own `bug_reports` table. To point it
elsewhere, name the table and say which columns mean what — the Postgres path
does no guessing, because the caller already knows the schema:

```json
{
  "bugs_table": "jira_issues",
  "bugs_columns": {
    "id": "issue_key", "created": "created_at", "severity": "priority",
    "status": "state", "summary": "title", "description": "body"
  }
}
```

### Endpoints

| Method | Path                             | Purpose                              |
|--------|----------------------------------|--------------------------------------|
| GET    | `/api/qa/health`                 | Snapshot, report, and model status    |
| POST   | `/api/qa/ingest`                 | Upload an .xlsx, write a snapshot     |
| POST   | `/api/qa/ingest/postgres`        | Read a Postgres table into a snapshot |
| GET    | `/api/qa/snapshots`              | Ingest history                        |
| POST   | `/api/qa/analyze`                | Start analysis (returns a `job_id`)   |
| GET    | `/api/qa/analyze/{id}/events`    | SSE stage progress                    |
| GET    | `/api/qa/analyze/{id}/result`    | The finished report                   |
| GET    | `/api/qa/report`                 | Newest persisted report               |
| GET    | `/api/qa/capabilities`           | What this snapshot contains           |
| POST   | `/api/qa/chat`                   | Ask a question, get answer + SQL      |

### The console

The dashboard has two panels above the grid, both collapsed by default.

**Ingest data** — drag a workbook in, or read the Postgres source. It shows
what the mapper understood: which sheet was read as what, how many columns
resolved, and every parse warning. Every number on the dashboard is
conditional on that having gone right, and an unresolved column is the
difference between "no bugs of that type" and "we could not read it". Running
the analysis streams its stages live.

**Ask the data** — a question is compiled into a filter query, run as SQL, and
narrated from the rows that came back. The compiled SQL and the rows are shown
beneath every answer, because an answer you cannot check against a query is a
claim, not a result.

Two small model calls, not one large one. The first never sees the database —
only the field list in `agent/query/dsl.py`, so a hallucinated column fails
validation instead of becoming a query. The second never sees anything but the
rows the query returned. Values are always bound; identifiers reach SQL only
after being checked against the frozen sets in the DSL.

### Tiles follow the data

Each cell in `qa-insights.ts` declares `requires`, checked against
`/api/qa/capabilities`. A source with no localization sheet does not render an
empty locale heatmap, an empty locale bar and a `0.0%` localization KPI —
three tiles reporting one absence. Those cells drop out and the row rebalances.

The workbook shows 17 tiles; the Postgres source, which has bugs but no test
plan or localization matrix, shows 7. Switch the snapshot dropdown to watch the
layout reflow.

### Enabling narration (optional)

Narration is off unless `OLLAMA_HOST` is set. Without it the summary is
assembled from the computed statistics and labelled `computed · no model
configured` on the dashboard, so a reader can always tell narrated prose from
a generated stand-in.

This project uses the `qa_ollama` container in WSL, which publishes 11434 on
the WSL VM's address. **`localhost` will not reach it** — a Windows-side Ollama
also binds 127.0.0.1:11434 and wins, so the WSL IP must be explicit:

```powershell
wsl hostname -I                                 # e.g. 172.30.71.143
$env:OLLAMA_HOST  = "http://172.30.71.143:11434"
$env:OLLAMA_MODEL = "qwen2.5:7b-instruct"       # the default
uvicorn main:app --port 4100
```

That IP changes when WSL restarts, so re-read it rather than hard-coding it.

The container mounts `qa---ai---assistant_ollama_data` at `/root/.ollama`,
which shadows anything baked into the image — models must be pulled into the
volume, and a fresh volume starts empty:

```powershell
wsl -e docker exec qa_ollama ollama pull qwen2.5:7b-instruct
wsl -e docker exec qa_ollama ollama list        # confirm
```

Structured output goes through Ollama's `format` field with a JSON Schema, so
the response cannot be malformed JSON. If the model is unreachable or exhausts
its retries the report falls back and is marked `partial` — never blocked.

### Snapshots, and why deltas compare snapshots

Each ingest appends rather than overwriting. A QA workbook is a point-in-time
statement of test state, and overwriting it destroys the thing the dashboard is
for: how coverage and severity moved between builds.

Every KPI therefore compares to the **previous snapshot of the same source**,
not the previous time period — "what did this build change" rather than "how
did last month look". A source with no earlier reading shows no delta rather
than an invented one.

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
- **Add a QA finding:** write a detector in `agent/insights/findings.py` that
  returns `Finding`s and append it to `DETECTORS`. It appears on the dashboard
  and in the narrator's input automatically.
- **Add a QA source:** implement the `Source` protocol in
  `agent/sources/base.py`. Nothing downstream knows where records came from.

For a full walkthrough of the design decisions and phased rollout plan, see the
architecture document at the root of this zip.

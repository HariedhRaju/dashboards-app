# ReportIQ Dashboard — Executive Project Reporting & Progress Intelligence

A full-stack, real-time executive dashboard for project status reporting (DSR/WSR), execution tracking, engineering health telemetry, and risk monitoring.

---

## 🌟 Key Features & Architecture

ReportIQ features an intelligent **Dual-Mode Dashboard Architecture**:

### 1. 🏢 Organization / Portfolio Intelligence Mode (Default / All Projects)
* **Executive KPIs**: Active Projects, Files & Specs Ingested, Daily Reports (DSR), Weekly Reports (WSR), Reporting Compliance Rate.
* **Portfolio Delivery Matrix**: Interactive table detailing progress, planned vs actual variance, health status, scores, and one-click drill-down.
* **Health Distribution**: Donut breakdown of projects into *On Track*, *At Risk*, and *Delayed*.
* **Publishing Velocity Timeseries**: Historical volume of DSR vs WSR reports filed.
* **Reporting Compliance Table**: Track report filing compliance and coverage per project.

### 2. 🎯 Project Command Center Mode (When a specific Project is selected)
* **Hero Command Banner**: Displays overall progress gauge, variance against plan, active risks count, files ingested, and multi-score telemetry with an instant "Back to Portfolio" navigation button.
* **Multi-Dimensional Health Breakdown**: Delivery Velocity, Code Quality, QA Testing, Build Stability, and Reporting status.
* **Sprint & Release Delta ("What Changed?")**: Live changes in tasks completed, defects fixed, automated tests run, blockers, and reports filed.
* **Project Journey Timeline**: Chronological event milestones (sprint closures, releases, critical bug spikes, UAT kick-offs).
* **Execution Velocity Trend (60-day Area Chart)**: Interactive Planned vs Actual progress curve.
* **Attention Required (Risks & Blockers)**: Active risk telemetry cards prioritized by severity (Critical / Warning / Notice).
* **Release Gate Milestones Tracker**: Multi-stage delivery gates and completion status.
* **Recent Status Reports Table**: Searchable history of DSR/WSR logs, pipeline compilation latency, and token consumption.

---

## 📁 Repository Structure

```
reportiq-dashboard/
├── backend/
│   ├── dashboards/
│   │   ├── __init__.py           # Connection pool, Redis cache, ReportIQ filter model, metric registry, dynamic dimensions
│   │   └── reportiq_metrics.py   # All 13+ ReportIQ metrics (Dual-Mode: Org Portfolio & Project Command Center)
│   ├── setup/
│   │   ├── reportiq_schema.sql   # Standalone schema for ReportIQ tables & indexes
│   │   ├── reportiq_seed.sql     # Static SQL seed file
│   │   └── seed_reportiq_v2.py   # Autonomous database migration and mock data generator
│   ├── .env.example              # Environment variables template
│   ├── main.py                   # FastAPI server entry point with CORS & API routing
│   └── requirements.txt          # Python dependencies (FastAPI, Uvicorn, Psycopg2, Redis, Pydantic)
├── frontend/
│   ├── dev/
│   │   ├── index.css             # Tailwind dark mode styling
│   │   └── main.tsx              # React mounting entry point
│   ├── src/
│   │   ├── dashboards/
│   │   │   └── report-iq.ts      # Dual-mode dashboard layout & widget definition
│   │   ├── api.ts                # API client, React Query hooks, formatters
│   │   ├── DashboardApp.tsx      # Main application router and provider
│   │   ├── DashboardRenderer.tsx # Dynamic responsive grid layout & widget renderer
│   │   ├── filters.tsx           # Interactive filter bar (projects, templates, statuses, dates)
│   │   ├── index.ts              # Public export bundle for mounting into existing host apps
│   │   ├── registry.tsx          # Dashboard loader & registry
│   │   ├── types.ts              # Full TypeScript type definitions
│   │   ├── vite-env.d.ts         # Vite client types
│   │   └── widgets.tsx           # All ReportIQ UI widgets (Project Banner, Health Matrix, What Changed, Progress Trend, Timeline, etc.)
│   ├── index.html                # HTML entry point
│   ├── package.json              # Frontend dependencies (React 18, Vite, Recharts, Lucide, Tailwind, React Query)
│   ├── postcss.config.js         # PostCSS config
│   ├── tailwind.config.js        # Tailwind CSS config
│   ├── tsconfig.json             # TypeScript configuration
│   └── vite.config.js            # Vite dev & proxy config
├── .gitignore                    # Git ignore rules for Python & Node.js
└── README.md                     # This guide
```

---

## 🚀 Quickstart Guide

### Step 1: Backend Setup

1. Open a terminal and navigate to the backend folder:
   ```bash
   cd backend
   ```

2. Create and activate a Python virtual environment:
   ```bash
   # Windows (PowerShell)
   python -m venv .venv
   .venv\Scripts\Activate.ps1

   # Linux / macOS
   python3 -m venv .venv
   source .venv/bin/activate
   ```

3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

4. Configure environment variables:
   ```bash
   # Copy the example .env
   cp .env.example .env
   ```
   Update `.env` with your PostgreSQL credentials:
   ```ini
   DASHBOARDS_REPLICA_DSN=postgresql://postgres:yourpassword@localhost:5432/your_database
   REDIS_URL=redis://localhost:6379/0
   ```
   *(Note: Redis is optional. If Redis is unavailable, the backend automatically falls back to direct database execution with zero crashes).*

5. Run database migration and autonomous seeding:
   ```bash
   python setup/seed_reportiq_v2.py
   ```

6. Start the FastAPI backend server:
   ```bash
   uvicorn main:app --reload --port 8000
   ```
   API will be available at `http://localhost:8000` with documentation at `http://localhost:8000/docs`.

---

### Step 2: Frontend Setup

1. Open a second terminal and navigate to the frontend folder:
   ```bash
   cd frontend
   ```

2. Install Node.js dependencies:
   ```bash
   npm install
   ```

3. Start the Vite development server:
   ```bash
   npm run dev
   ```

4. Open your browser at:
   ```
   http://localhost:5173
   ```

---

## 📦 How to Replicate to a New Git Repository

To push this standalone folder into a brand new Git repository (e.g. on GitHub, GitLab, or Bitbucket):

1. Initialize Git in the `reportiq-dashboard` folder:
   ```bash
   cd reportiq-dashboard
   git init
   ```

2. Stage all files and create the initial commit:
   ```bash
   git add .
   git commit -m "feat: initial commit of standalone ReportIQ dashboard"
   ```

3. Link to your new remote repository:
   ```bash
   git branch -M main
   git remote add origin https://github.com/your-org/reportiq-dashboard.git
   git push -u origin main
   ```

---

## 🔌 Embedding ReportIQ into Existing Applications

### Mount in an Existing FastAPI App
```python
from fastapi import FastAPI
from dashboards import router as reportiq_router

app = FastAPI()
app.include_router(reportiq_router, prefix="/api")
```

### Mount in an Existing React App
```tsx
import { BrowserRouter } from 'react-router-dom';
import { DashboardApp } from './src';

export function AnalyticsSection() {
  return (
    <BrowserRouter basename="/analytics">
      <DashboardApp />
    </BrowserRouter>
  );
}
```

---

## 📄 License
MIT License.

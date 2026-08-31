"""
FastAPI host application for the ReportIQ dashboard module.

Run with:
    uvicorn main:app --reload --port 8000

Configure via environment variables or .env file:
    DASHBOARDS_REPLICA_DSN  Postgres DSN (e.g. postgresql://postgres:pw@localhost:5432/dashboards_dev)
    REDIS_URL               Redis URL (default redis://localhost:6379/0)
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from dashboards import router as dashboards_router

app = FastAPI(title="ReportIQ Dashboard API", version="1.0.0")

# Allow the Vite dev server (port 5173 / localhost) to call the API during development.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(dashboards_router, prefix="/api")


@app.get("/")
def health():
    return {"ok": True, "service": "reportiq-dashboard-api"}

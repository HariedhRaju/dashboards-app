"""
FastAPI host app for the dashboards module.

Run with:
    uvicorn main:app --reload --port 8000

Configure via environment variables:
    DASHBOARDS_REPLICA_DSN  Postgres DSN (e.g. postgresql://postgres:pw@localhost:5432/dashboards_dev)
    REDIS_URL               Redis URL (default redis://localhost:6379/0)
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from dashboards import router as dashboards_router

app = FastAPI(title="Dashboards Dev")

# Allow the Vite dev server (port 5173) to call the API during development.
# In production, the frontend and API sit on the same origin — this middleware
# is only needed for the local dev flow.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(dashboards_router, prefix="/api")


@app.get("/")
def health():
    return {"ok": True, "service": "dashboards"}

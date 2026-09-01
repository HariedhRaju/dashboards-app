"""QA reporting & summarizing agent.

Turns a QA workbook — or an existing Postgres source — into a normalized
snapshot, a set of ranked findings, and a narrated executive summary that the
`qa-insights` dashboard renders.

The pipeline is four stages, each independently useful:

    sources/   fetch      .xlsx upload, or read a Postgres source directly
    ingest/    normalize  probe → map columns → canonical records
    store/     persist    one immutable snapshot in Postgres
    insights/  reason     deterministic findings, then model narration

The ordering is the design. Every number the agent reports is computed in SQL
or Python before a model sees anything, and the model is only ever asked to
narrate figures that are already correct. With no model configured the
dashboard is fully functional — it loses prose, not data.

Wire in:
    from agent.api import router as agent_router
    app.include_router(agent_router, prefix="/api")

The `ingest/` package (probe, mapping, normalize, synonyms) is ported from the
Crescent QA Pipeline prototype in the sibling `test-cases-summarizer-agent`
repo, where it has its own regression suite. It was taken rather than rewritten
because sheet-structure detection is the part of this pipeline where a subtle
mistake is silent — a misread header row corrupts every number downstream
without ever raising. Fixes worth having should flow between the two.

Env vars:
    DASHBOARDS_PRIMARY_DSN  Writable Postgres DSN for ingest
                            (falls back to DASHBOARDS_REPLICA_DSN, DATABASE_URL)
    OLLAMA_HOST             e.g. http://127.0.0.1:11434 — unset disables narration
    OLLAMA_MODEL            default qwen2.5:14b-instruct
"""

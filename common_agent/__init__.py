"""
Common Analytics Agent — cross-feature analytics between Bugsy and TestSmith.

Layering (see contracts.py / core.py docstrings for the rules each layer must
follow):

    contracts.py   pure data shapes + Protocol interfaces. No DB, no LLM.
    core.py        build_common_dashboard() — deterministic aggregation.
                   Depends only on contracts.py. No DB, no LLM.
    postgres_*.py  adapters — the only files here that touch the database.
                   Each implements exactly one Protocol from contracts.py.
    insights.py    LLM interpretation layer. Receives only the dict already
                   produced by core.py. No DB, no adapters.

Wired into the app in dashboards/__init__.py, which lazily imports from this
package inside the /common-agent/dashboard route handler (matching the
lazy-import pattern already used there for dashboard_agent/insight_agent).
"""

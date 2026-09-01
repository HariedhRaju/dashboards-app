"""The seam between "where the data came from" and everything after it.

A source's only job is to produce an `IngestResult` — the canonical records the
rest of the agent binds to. Nothing downstream of this module knows whether a
bug arrived as a spreadsheet cell or a database row, which is what lets a new
source be added without touching the insight engine, the metrics, or the UI.
"""

from __future__ import annotations

from typing import Protocol

from ..ingest.models import IngestResult


class Source(Protocol):
    """Anything that can yield canonical QA records."""

    #: Stored on the snapshot so a report can say where its numbers came from.
    kind: str

    def label(self) -> str:
        """Human-readable origin — a filename, or a DSN's database + tables."""
        ...

    def fetch(self) -> IngestResult:
        """Produce canonical records. Raises on unusable input, never guesses."""
        ...

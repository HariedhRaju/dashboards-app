"""Workbook source — probe, map, normalize an .xlsx into canonical records.

All of the hard work lives in `agent.ingest`, which is deliberately schema-
agnostic: it decides what each sheet is by scoring its structure and its
values, not by matching a known filename. That is what lets the agent accept
next quarter's workbook after someone has renamed three columns and inserted a
counter block above the header.
"""

from __future__ import annotations

import os

from ..ingest.models import IngestResult
from ..ingest.pipeline import ingest


class XlsxSource:
    kind = "xlsx"

    def __init__(self, path: str, display_name: str | None = None):
        self.path = path
        # An upload lands in a temp file with a generated name; the original
        # filename is what belongs on the snapshot.
        self._display_name = display_name or os.path.basename(path)

    def label(self) -> str:
        return self._display_name

    def fetch(self) -> IngestResult:
        return ingest(self.path)

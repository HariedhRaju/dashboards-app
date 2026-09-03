"""Several workbooks, one analysis set.

A QA cycle is rarely one file. It is a gameplay test plan, a map test plan,
this week's bug tracker and last week's — and the questions worth asking span
them: which plan is behind, whether the bugs cluster in the area the thin plan
covers. Analysing each file alone cannot answer either.

So the files merge into ONE snapshot, and every record keeps the name of the
file it came from. That is what makes both readings available: the aggregate
("81% of 592 cases executed") and the per-plan breakdown ("the map plan is at
45%, and it is the whole gap"). Dropping file identity would leave only the
first, which averages the problem away.

Each file is probed independently — the mapper's structural detection is
per-workbook, and one file's layout must not influence another's reading.
"""

from __future__ import annotations

import hashlib
import os
from typing import Iterable, Optional

from ..ingest.models import IngestResult
from ..ingest.pipeline import ingest


class MultiXlsxSource:
    """Ingest N workbooks into a single IngestResult."""

    kind = "xlsx"

    def __init__(self, files: Iterable[tuple[str, str]], label: Optional[str] = None):
        """`files` is (temp_path, display_name) pairs, in upload order."""
        self._files = list(files)
        self._label = label

    def label(self) -> str:
        if self._label:
            return self._label
        names = [name for _, name in self._files]
        if not names:
            return "empty upload"
        if len(names) == 1:
            return names[0]
        # Name the set after its first file plus a count, so the snapshot
        # dropdown stays readable when someone uploads eight trackers.
        return f"{names[0]} + {len(names) - 1} more"

    # ── fetch ────────────────────────────────────────────────────────────

    def fetch(self) -> IngestResult:
        merged = IngestResult(source_path=self.label(), fingerprint="")
        fingerprints: list[str] = []

        for path, display_name in self._files:
            try:
                one = ingest(path)
            except Exception as e:  # noqa: BLE001
                # One unreadable file must not sink the upload. It is recorded
                # as a file that yielded nothing and the rest still ingest —
                # a partial set the reader can see is better than an error
                # page that loses the four files that parsed fine.
                merged.source_files.append({
                    "name": display_name,
                    "ok": False,
                    "error": f"{type(e).__name__}: {e}",
                    "bugs": 0, "test_cases": 0, "matrix_results": 0, "sheets": [],
                })
                merged.warnings.append(f"{display_name}: could not be parsed — {e}")
                continue

            fingerprints.append(one.fingerprint)
            self._stamp(one, display_name)

            merged.bugs.extend(one.bugs)
            merged.test_cases.extend(one.test_cases)
            merged.matrix_results.extend(one.matrix_results)
            merged.sheets.extend(one.sheets)
            # Warnings are prefixed: "row 25 has an unparseable date" is not
            # actionable across four files unless it says which one.
            merged.warnings.extend(f"{display_name}: {w}" for w in one.warnings)

            merged.source_files.append({
                "name": display_name,
                "ok": True,
                "error": None,
                "bugs": len(one.bugs),
                "test_cases": len(one.test_cases),
                "matrix_results": len(one.matrix_results),
                "sheets": [
                    {"name": s.name, "role": s.role.value, "rows": s.row_count}
                    for s in one.sheets
                ],
            })

        # The set's fingerprint is the hash of its members' fingerprints, in
        # upload order — so re-uploading the same files in the same order is
        # recognisable as the same shape, and swapping one file in is not.
        merged.fingerprint = hashlib.sha256(
            "\x1f".join(fingerprints).encode()
        ).hexdigest()[:16]
        return merged

    # ── attribution ──────────────────────────────────────────────────────

    @staticmethod
    def _stamp(result: IngestResult, display_name: str) -> None:
        """Tag every record and sheet with the file it came from.

        Sheet names are qualified too. Four workbooks each with a sheet called
        "Sheet1" would otherwise be indistinguishable in the ingest receipt,
        and `source_sheet` is part of a bug's identity in Postgres.
        """
        for record in (*result.bugs, *result.test_cases, *result.matrix_results):
            record.source_file = display_name
            record.source_sheet = f"{display_name} · {record.source_sheet}"
        for sheet in result.sheets:
            sheet.name = f"{display_name} · {sheet.name}"


def source_for_uploads(
    files: list[tuple[str, str]], label: Optional[str] = None
):
    """Pick the right source for however many files arrived.

    A single file still goes through the multi-file path so that one code
    path writes attribution — otherwise a one-file upload would leave
    source_file blank and drop out of every per-file breakdown.
    """
    return MultiXlsxSource(files, label=label)


def default_label(names: list[str]) -> str:
    """A readable snapshot name for a set of uploaded files."""
    if not names:
        return "empty upload"
    if len(names) == 1:
        return names[0]
    stem = os.path.commonprefix(names).strip(" -_")
    return f"{stem or names[0]} + {len(names) - 1} more"

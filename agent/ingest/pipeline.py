"""Wire probe, mapping, and normalization into one ingest run."""

from __future__ import annotations

from .mapping import detect_role, map_columns
from .models import IngestResult, SheetRole
from .normalize import build_bugs, build_matrix_results, build_test_cases
from .probe import probe_workbook


def ingest(path: str) -> IngestResult:
    sheets, probes, fingerprint = probe_workbook(path)
    by_name = {s.name: s for s in sheets}

    result = IngestResult(source_path=path, fingerprint=fingerprint, sheets=probes)

    for probe in probes:
        sheet = by_name[probe.name]
        probe.role = detect_role(sheet, probe)
        probe.columns = map_columns(sheet, probe, probe.role)

        for m in probe.columns:
            if m.method == "rejected":
                result.warnings.append(f"{probe.name}: {m.note}")

        if probe.header_row is None:
            continue

        if probe.role is SheetRole.BUGS:
            result.bugs.extend(build_bugs(sheet, probe, result.warnings))
        elif probe.role is SheetRole.TEST_CASES:
            result.test_cases.extend(
                build_test_cases(sheet, probe, result.warnings)
            )
        elif probe.role is SheetRole.MATRIX_RESULTS:
            result.matrix_results.extend(
                build_matrix_results(sheet, probe, result.warnings)
            )

    return result

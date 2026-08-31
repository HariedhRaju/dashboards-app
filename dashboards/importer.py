"""
Excel and CSV Bug Ingestion, Normalization & Persistence Module (Step 1.5 Complete).

Reads Excel (.xlsx/.xls) or CSV files, normalizes columns and enums, validates required fields,
and persists valid records to PostgreSQL using idempotent ON CONFLICT UPSERT via write_cursor().
"""
from __future__ import annotations

import csv
import io
import json
import os
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import openpyxl
from . import replica_cursor, write_cursor

SYSTEM_REPORTER_UUID = "00000000-0000-0000-0000-000000000001"
SYSTEM_REPORTER_NAME = "Excel Import"
SYSTEM_REPORTER_EMAIL = "excel.import@system.local"

GENERIC_FILENAME_WORDS = {"bugs", "bug", "tracker", "import", "data", "unknown", "temp", "file", "export", "report", "sheet", "test"}


@dataclass
class NormalizedBug:
    """Internal representation of a validated bug report before database insertion."""
    source: str                         # e.g. "excel", "csv", "jira"
    source_record_id: str               # Clean internal identifier (e.g. "1", "61", "TEST-001")
    project: str | None                 # Project UUID or Name
    title: str                          # Bug title (truncated to max 300 chars)
    summary: str | None                 # Extended details / description
    severity: str                       # Canonical: "P1", "P2", "P3", "P4"
    status: str                         # Canonical: "open", "in_progress", "fixed", "closed"
    created_at: datetime | None = None  # Timezone-aware datetime (UTC)
    dynamic_fields: dict[str, Any] = field(default_factory=dict)  # Unmapped raw columns


@dataclass
class ImportErrorItem:
    """Validation failure details for a single row."""
    row: int
    field: str
    value: Any
    reason: str


@dataclass
class ImportParseResult:
    """Structured parsing result from an ingestion operation."""
    records: list[NormalizedBug]
    errors: list[ImportErrorItem]
    warnings: list[str]
    total_rows: int


# Explicit synonym mappings based on empirical inspection of actual QA bug trackers
COLUMN_ALIASES = {
    "source_record_id": ["issueno", "issuenumber", "bugid", "issue", "id", "recordid"],
    "title": ["summary", "title", "subject", "name"],
    "summary": ["description", "details", "steps", "actualresult", "expectedresult"],
    "severity": ["severity", "priority", "sev"],
    "status": ["status", "state", "resolution"],
    "created_at": ["created", "createdat", "date", "reporteddate"],
    "project": ["project", "projectname", "projectcode", "game"],
}

SEVERITY_MAP = {
    "p1": "P1", "blocker": "P1", "critical": "P1", "1": "P1",
    "p2": "P2", "major": "P2", "high": "P2", "2": "P2",
    "p3": "P3", "minor": "P3", "medium": "P3", "normal": "P3", "3": "P3",
    "p4": "P4", "trivial": "P4", "low": "P4", "4": "P4",
}

STATUS_MAP = {
    "open": "open", "new": "open", "reopened": "open", "unresolved": "open",
    "we'll put this in our backlog.": "open", "backlog": "open",
    "in_progress": "in_progress", "in progress": "in_progress", "assigned": "in_progress", "working": "in_progress",
    "fixed": "fixed", "qa ready": "fixed", "qaready": "fixed", "resolved": "fixed",
    "closed": "closed", "not a bug": "closed", "wontfix": "closed", "won't fix": "closed",
}


def extract_project_from_filename(filename: str) -> str | None:
    """Extract project title from filename if project column is missing."""
    clean = os.path.basename(filename)
    clean = re.sub(r'^(copy\s+of\s+)', '', clean, flags=re.IGNORECASE)
    clean = re.sub(r'\s*-\s*\d{4}.*$', '', clean, flags=re.IGNORECASE)
    clean = re.sub(r'\([^\)]*\)', '', clean)
    clean = re.sub(r'\.(csv|xlsx|xls)$', '', clean, flags=re.IGNORECASE)
    clean = clean.strip()
    
    # If clean filename is just a generic term, it cannot reliably identify a project
    tokens = set(re.findall(r'[a-zA-Z]+', clean.lower()))
    if not tokens or tokens.issubset(GENERIC_FILENAME_WORDS):
        return None

    return clean if clean else None


def _normalize_header(header: str) -> str:
    """Clean and normalize header text."""
    return re.sub(r'[^a-z0-9]', '', str(header).strip().lower())


def normalize_source_record_id(raw_val: Any) -> str | None:
    """
    Normalize Issue No into a clean internal string identifier.
    Examples:
      "1#"      -> "1"
      "#61"     -> "61"
      " 46# "   -> "46"
      "1042.0"  -> "1042"
      "BUG-123" -> "BUG-123"
    """
    if raw_val is None:
        return None

    val_str = str(raw_val).strip()
    if not val_str:
        return None

    # Handle float representations like "1042.0"
    if val_str.endswith(".0") and val_str[:-2].isdigit():
        val_str = val_str[:-2]

    # Strip leading/trailing '#' characters and whitespace
    clean_id = val_str.strip("#").strip()
    return clean_id if clean_id else None


def parse_created_date(raw_val: Any) -> tuple[datetime | None, str | None]:
    """
    Parse date into a timezone-aware datetime in UTC.
    Supports formats seen in actual workbooks:
      - datetime object
      - "15/09/2025" (DD/MM/YYYY)
      - "16/092025" (typo missing slash before year)
      - "2025-09-15" (ISO)
    """
    if raw_val is None:
        return None, None

    if isinstance(raw_val, datetime):
        if raw_val.tzinfo is None:
            return raw_val.replace(tzinfo=timezone.utc), None
        return raw_val.astimezone(timezone.utc), None

    val_str = str(raw_val).strip()
    if not val_str:
        return None, None

    # Fix typo format "16/092025" -> "16/09/2025"
    typo_match = re.match(r"^(\d{1,2})/(\d{2})(\d{4})$", val_str)
    if typo_match:
        val_str = f"{typo_match.group(1)}/{typo_match.group(2)}/{typo_match.group(3)}"

    # Try common formats
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%m/%d/%Y"):
        try:
            dt = datetime.strptime(val_str, fmt)
            return dt.replace(tzinfo=timezone.utc), None
        except ValueError:
            pass

    return None, f"Unparseable date format: '{val_str}'"


def parse_file_rows(file_bytes: bytes, filename: str) -> list[tuple[int, dict[str, Any]]]:
    """Parse raw file bytes (.csv or .xlsx/.xls) into (row_number, row_dict) tuples."""
    results: list[tuple[int, dict[str, Any]]] = []
    is_csv = filename.lower().endswith(".csv")

    if is_csv:
        content = file_bytes.decode("utf-8-sig", errors="replace")
        reader = csv.reader(io.StringIO(content))
        rows = list(reader)
        if not rows:
            return []

        raw_headers = rows[0]
        header_map = {}
        for idx, h in enumerate(raw_headers):
            norm = _normalize_header(h)
            if norm:
                header_map[idx] = (h.strip(), norm)

        for line_idx, row in enumerate(rows[1:], start=2):
            if not any(cell.strip() for cell in row if isinstance(cell, str)):
                continue
            row_dict = {}
            for idx, (orig_h, norm_h) in header_map.items():
                if idx < len(row):
                    row_dict[norm_h] = (orig_h, row[idx].strip())
            results.append((line_idx, row_dict))
    else:
        wb = openpyxl.load_workbook(filename=io.BytesIO(file_bytes), data_only=True)
        sheet_names = wb.sheetnames
        target_sheet_name = sheet_names[0]
        for name in sheet_names:
            if "bug" in name.lower() or "tracker" in name.lower():
                target_sheet_name = name
                break
        
        sheet = wb[target_sheet_name]
        all_rows = list(sheet.iter_rows(values_only=True))
        if not all_rows:
            return []

        raw_headers = all_rows[0]
        header_map = {}
        for idx, h in enumerate(raw_headers):
            if h is not None:
                norm = _normalize_header(str(h))
                if norm:
                    header_map[idx] = (str(h).strip(), norm)

        for line_idx, row in enumerate(all_rows[1:], start=2):
            if not row or not any(v is not None and str(v).strip() for v in row):
                continue
            row_dict = {}
            for idx, (orig_h, norm_h) in header_map.items():
                if idx < len(row) and row[idx] is not None:
                    row_dict[norm_h] = (orig_h, str(row[idx]).strip())
            results.append((line_idx, row_dict))

    return results


def parse_bug_file(
    file_bytes: bytes,
    filename: str,
    default_project: str | None = None,
    source_name: str = "excel"
) -> ImportParseResult:
    """
    Pure ingestion function that reads Excel or CSV files and returns
    a structured ImportParseResult without database writes.
    """
    raw_rows = parse_file_rows(file_bytes, filename)
    records: list[NormalizedBug] = []
    errors: list[ImportErrorItem] = []
    warnings: list[str] = []

    seen_ids: dict[tuple[str, str], int] = {}  # (source, source_record_id) -> first_row

    inferred_project = default_project or extract_project_from_filename(filename)

    for row_num, row_dict in raw_rows:
        # Helper to extract value by field alias
        def get_val(field_key: str) -> tuple[str | None, str | None]:
            aliases = COLUMN_ALIASES.get(field_key, [])
            for alias in aliases:
                norm = _normalize_header(alias)
                if norm in row_dict:
                    orig_h, val = row_dict[norm]
                    if val:
                        return val, orig_h
            return None, None

        # 1. Validate Issue No / source_record_id
        raw_issue_no, _ = get_val("source_record_id")
        source_rec_id = normalize_source_record_id(raw_issue_no)
        if not source_rec_id:
            errors.append(ImportErrorItem(
                row=row_num,
                field="Issue No",
                value=raw_issue_no,
                reason="Missing source record identifier"
            ))
            continue

        # Check for duplicate source_record_id within the file
        dup_key = (source_name.lower(), source_rec_id)
        if dup_key in seen_ids:
            warnings.append(
                f"Row {row_num}: Duplicate source_record_id '{source_rec_id}' (first seen at row {seen_ids[dup_key]})"
            )
        else:
            seen_ids[dup_key] = row_num

        # 2. Validate Title
        title_val, _ = get_val("title")
        if not title_val:
            errors.append(ImportErrorItem(
                row=row_num,
                field="Title",
                value=title_val,
                reason="Missing title"
            ))
            continue
        title = title_val[:300]  # Truncate to max 300 chars

        # 3. Validate Severity (Strict)
        sev_val, _ = get_val("severity")
        norm_sev = SEVERITY_MAP.get(str(sev_val).lower() if sev_val else "")
        if not norm_sev:
            errors.append(ImportErrorItem(
                row=row_num,
                field="Severity",
                value=sev_val,
                reason="Unrecognized severity value"
            ))
            continue

        # 4. Validate Status (Strict)
        status_val, _ = get_val("status")
        norm_status = STATUS_MAP.get(str(status_val).lower() if status_val else "")
        if not norm_status:
            errors.append(ImportErrorItem(
                row=row_num,
                field="Status",
                value=status_val,
                reason="Unrecognized status value"
            ))
            continue

        # 5. Project Resolution Priority (Column -> Default -> Filename -> Error)
        proj_val, _ = get_val("project")
        project = proj_val or inferred_project
        if not project:
            errors.append(ImportErrorItem(
                row=row_num,
                field="Project",
                value=None,
                reason="Project could not be determined for this file/row"
            ))
            continue

        # 6. Summary / Description
        summary_val, _ = get_val("summary")
        summary = summary_val if summary_val else title

        # 7. Created Date Parsing
        date_val, _ = get_val("created_at")
        created_dt, date_warn = parse_created_date(date_val)
        if date_warn:
            warnings.append(f"Row {row_num}: {date_warn}")

        # 8. Unmapped Columns -> dynamic_fields (Preserve all extra QA source fields)
        mapped_norms = set()
        for aliases in COLUMN_ALIASES.values():
            for a in aliases:
                mapped_norms.add(_normalize_header(a))

        dynamic_fields: dict[str, Any] = {
            "source": source_name.lower(),
            "source_record_id": source_rec_id,
        }
        for norm_h, (orig_h, val) in row_dict.items():
            if norm_h not in mapped_norms and val:
                dynamic_fields[orig_h] = val

        records.append(NormalizedBug(
            source=source_name.lower(),
            source_record_id=source_rec_id,
            project=project,
            title=title,
            summary=summary,
            severity=norm_sev,
            status=norm_status,
            created_at=created_dt,
            dynamic_fields=dynamic_fields,
        ))

    return ImportParseResult(
        records=records,
        errors=errors,
        warnings=warnings,
        total_rows=len(raw_rows),
    )


# ══════════════════════════════════════════════════════════════════════════
#  DATABASE PERSISTENCE & INFRASTRUCTURE HELPERS
# ══════════════════════════════════════════════════════════════════════════

def ensure_import_infrastructure(cur) -> str:
    """Ensure unique index and system import user exist in PostgreSQL. Returns system user UUID."""
    # 1. Check if System User already exists in bug_users
    cur.execute("SELECT id FROM bug_users WHERE id = %s OR name = %s OR email = %s LIMIT 1",
                (SYSTEM_REPORTER_UUID, SYSTEM_REPORTER_NAME, SYSTEM_REPORTER_EMAIL))
    existing_user = cur.fetchone()
    if existing_user:
        system_user_id = str(existing_user["id"])
    else:
        cur.execute("SELECT table_type FROM information_schema.tables WHERE table_name = 'bug_users'")
        tbl_info = cur.fetchone()
        is_view = tbl_info and tbl_info.get("table_type") == "VIEW"

        if is_view:
            try:
                cur.execute("""
                    INSERT INTO users (id, name, email, role, mfa_enabled, mfa_failed_attempts, mfa_last_used_timestamp, auth_provider)
                    VALUES (%s, %s, %s, 'tester', false, 0, 0, 'local')
                    ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name
                    RETURNING id;
                """, (SYSTEM_REPORTER_UUID, SYSTEM_REPORTER_NAME, SYSTEM_REPORTER_EMAIL))
                res = cur.fetchone()
                system_user_id = str(res["id"]) if res else SYSTEM_REPORTER_UUID
            except Exception:
                cur.execute("SELECT id FROM bug_users LIMIT 1")
                any_user = cur.fetchone()
                system_user_id = str(any_user["id"]) if any_user else SYSTEM_REPORTER_UUID
        else:
            cur.execute("""
                INSERT INTO bug_users (id, name, email)
                VALUES (%s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, email = EXCLUDED.email
                RETURNING id;
            """, (SYSTEM_REPORTER_UUID, SYSTEM_REPORTER_NAME, SYSTEM_REPORTER_EMAIL))
            res = cur.fetchone()
            system_user_id = str(res["id"]) if res else SYSTEM_REPORTER_UUID

    # 2. Unique Index for (project_id, source, source_record_id)
    cur.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_bug_reports_project_source_record
        ON bug_reports (
            project_id,
            (dynamic_fields->>'source'),
            (dynamic_fields->>'source_record_id')
        )
        WHERE dynamic_fields->>'source' IS NOT NULL
          AND dynamic_fields->>'source_record_id' IS NOT NULL;
    """)

    return system_user_id


def resolve_project_id(cur, project_name_or_code: str, default_user_id: str) -> str:
    """Lookup or insert project in bug_projects and return its UUID."""
    clean_name = project_name_or_code.strip()
    if not clean_name:
        clean_name = "Default Project"

    # Match by name or code (case-insensitive)
    cur.execute("""
        SELECT id FROM bug_projects 
        WHERE LOWER(name) = LOWER(%s) OR LOWER(code) = LOWER(%s) 
        LIMIT 1;
    """, (clean_name, clean_name))
    row = cur.fetchone()
    if row:
        return str(row["id"])

    # Check if bug_projects is a VIEW
    cur.execute("SELECT table_type FROM information_schema.tables WHERE table_name = 'bug_projects'")
    tbl_info = cur.fetchone()
    is_view = tbl_info and tbl_info.get("table_type") == "VIEW"

    code_abbr = (re.sub(r'[^A-Z0-9]', '', clean_name.upper())[:4] or "PRJ") + "_" + uuid.uuid4().hex[:6].upper()

    if is_view:
        try:
            cur.execute("""
                INSERT INTO projects (id, name, code, created_by)
                VALUES (gen_random_uuid(), %s, %s, %s)
                RETURNING id;
            """, (clean_name, code_abbr, default_user_id))
            new_row = cur.fetchone()
            if new_row:
                return str(new_row["id"])
        except Exception:
            cur.execute("SELECT id FROM bug_projects LIMIT 1")
            fallback = cur.fetchone()
            if fallback:
                return str(fallback["id"])
    else:
        cur.execute("""
            INSERT INTO bug_projects (id, name, code)
            VALUES (gen_random_uuid(), %s, %s)
            RETURNING id;
        """, (clean_name, code_abbr))
        new_row = cur.fetchone()
        if new_row:
            return str(new_row["id"])

    cur.execute("SELECT id FROM bug_projects LIMIT 1")
    return str(cur.fetchone()["id"])


def save_normalized_bugs(records: list[NormalizedBug], reporter_id: str | None = None) -> tuple[int, int]:
    """
    Persist normalized bug records to PostgreSQL using idempotent UPSERT via write_cursor().
    Returns (inserted_count, updated_count).
    """
    if not records:
        return 0, 0

    inserted_count = 0
    updated_count = 0

    with write_cursor() as cur:
        if not reporter_id:
            reporter_id = ensure_import_infrastructure(cur)

        # In-memory batch deduplication (keep last record per project_id + source + source_record_id)
        deduped_map: dict[tuple[str, str, str], NormalizedBug] = {}
        for rec in records:
            proj_id = rec.project
            # If rec.project is not a UUID string, resolve it
            if proj_id and not re.match(r'^[0-9a-fA-F-]{36}$', proj_id):
                proj_id = resolve_project_id(cur, proj_id, reporter_id)

            key = (str(proj_id), str(rec.source), str(rec.source_record_id))
            deduped_map[key] = NormalizedBug(
                source=rec.source,
                source_record_id=rec.source_record_id,
                project=proj_id,
                title=rec.title,
                summary=rec.summary,
                severity=rec.severity,
                status=rec.status,
                created_at=rec.created_at,
                dynamic_fields=rec.dynamic_fields,
            )

        upsert_sql = """
            INSERT INTO bug_reports (
                id,
                project_id,
                reported_by,
                title,
                summary,
                severity,
                status,
                dynamic_fields,
                created_at,
                updated_at
            ) VALUES (
                gen_random_uuid(),
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s::jsonb,
                COALESCE(%s, NOW()),
                NOW()
            )
            ON CONFLICT (
                project_id,
                ((dynamic_fields ->> 'source'::text)),
                ((dynamic_fields ->> 'source_record_id'::text))
            )
            WHERE dynamic_fields->>'source' IS NOT NULL 
              AND dynamic_fields->>'source_record_id' IS NOT NULL
            DO UPDATE SET
                title          = EXCLUDED.title,
                summary        = EXCLUDED.summary,
                severity       = EXCLUDED.severity,
                status         = EXCLUDED.status,
                dynamic_fields = EXCLUDED.dynamic_fields,
                updated_at     = NOW()
            RETURNING (xmax = 0) AS is_inserted;
        """

        for rec in deduped_map.values():
            df = dict(rec.dynamic_fields)
            df["source"] = rec.source
            df["source_record_id"] = rec.source_record_id

            cur.execute(upsert_sql, (
                rec.project,
                reporter_id,
                rec.title,
                rec.summary or rec.title,
                rec.severity,
                rec.status,
                json.dumps(df),
                rec.created_at
            ))
            res = cur.fetchone()
            if res and res.get("is_inserted"):
                inserted_count += 1
            else:
                updated_count += 1

    return inserted_count, updated_count


def import_bugs(
    file_bytes: bytes,
    filename: str,
    default_project: str | None = None,
    source_name: str = "excel"
) -> dict[str, Any]:
    """
    End-to-end bug import function:
      1. Parses file & validates fields -> ImportParseResult
      2. If valid records exist -> saves via PostgreSQL UPSERT using write_cursor()
      3. Returns structured execution summary:
         {
           "inserted": N,
           "updated": M,
           "skipped": S,
           "errors": [...],
           "warnings": [...]
         }
    """
    parse_res = parse_bug_file(file_bytes, filename, default_project=default_project, source_name=source_name)
    
    inserted, updated = save_normalized_bugs(parse_res.records) if parse_res.records else (0, 0)
    
    return {
        "inserted": inserted,
        "updated": updated,
        "skipped": len(parse_res.errors),
        "errors": [
            {
                "row": err.row,
                "field": err.field,
                "value": err.value,
                "reason": err.reason,
            }
            for err in parse_res.errors
        ],
        "warnings": parse_res.warnings,
        "total_rows": parse_res.total_rows,
    }

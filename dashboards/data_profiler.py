"""
Generic Data Profiling Engine for Bugsy / Bug Bot.

Inspects standard bug_reports fields and dynamic JSONB fields in PostgreSQL
to generate a structured data profile describing field types, sample values,
analytical roles, opportunities, and data quality metrics.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from psycopg2.extras import RealDictCursor
from . import replica_cursor

# Identifiers that MUST NOT be recommended as chart dimensions or measures
PROTECTED_IDENTIFIER_KEYS = {
    "source",
    "source_record_id",
    "issue_no",
    "issue_number",
    "issue no",
    "id",
    "bug_id",
    "uuid",
    "external_id",
}


def _is_protected_identifier(key_name: str) -> bool:
    clean_name = key_name.lower().strip()
    if clean_name in PROTECTED_IDENTIFIER_KEYS:
        return True
    if clean_name.endswith("_id") or clean_name.endswith("_number") or clean_name.endswith("_num"):
        return True
    return False


def _parse_date_string(val_str: str) -> Optional[datetime]:
    val_str = val_str.strip()
    date_formats = [
        "%Y-%m-%d",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%d/%m/%Y",
        "%m/%d/%Y",
        "%Y/%m/%d",
        "%Y-%m-%d %H:%M:%S",
    ]
    for fmt in date_formats:
        try:
            return datetime.strptime(val_str, fmt)
        except ValueError:
            pass
    return None


def _infer_field_type_and_roles(key_name: str, values: List[Any], total_records: int) -> Dict[str, Any]:
    """
    Deterministically infer data type, summary stats, distributions, and recommended roles for a list of sample values.
    """
    clean_values = [v for v in values if v is not None and str(v).strip() != ""]
    non_null_count = len(clean_values)
    null_count = total_records - non_null_count
    null_pct = round((null_count / total_records * 100.0), 1) if total_records > 0 else 0.0

    distinct_set = set(str(v).strip() for v in clean_values)
    distinct_count = len(distinct_set)
    sample_values = sorted(list(distinct_set))[:10]

    # Calculate distribution / value counts
    val_counts: Dict[str, int] = {}
    for v in clean_values:
        s_val = str(v).strip()
        val_counts[s_val] = val_counts.get(s_val, 0) + 1

    # 1. Protected Identifiers Check
    if _is_protected_identifier(key_name):
        return {
            "detected_type": "identifier",
            "recommended_roles": ["identifier"],
            "non_null_count": non_null_count,
            "null_count": null_count,
            "null_percentage": null_pct,
            "distinct_count": distinct_count,
            "distinct_values_sample": sample_values,
        }

    if non_null_count == 0:
        return {
            "detected_type": "unknown",
            "recommended_roles": ["detail"],
            "non_null_count": 0,
            "null_count": null_count,
            "null_percentage": null_pct,
            "distinct_count": 0,
            "distinct_values_sample": [],
        }

    # 2. Ratio / Score Check (e.g. "5/5", "3/10")
    ratio_matches = []
    ratio_pattern = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)\s*$")
    for v in clean_values:
        m = ratio_pattern.match(str(v))
        if m:
            try:
                num = float(m.group(1))
                den = float(m.group(2))
                if den != 0:
                    ratio_matches.append((num, den, num / den))
            except ValueError:
                pass

    if len(ratio_matches) / non_null_count >= 0.8:
        eval_values = [r[2] for r in ratio_matches]
        nums = [r[0] for r in ratio_matches]
        return {
            "detected_type": "ratio",
            "recommended_roles": ["filter", "measure"],
            "non_null_count": non_null_count,
            "null_count": null_count,
            "null_percentage": null_pct,
            "distinct_count": distinct_count,
            "distinct_values_sample": sample_values,
            "min": round(min(nums), 2),
            "max": round(max(nums), 2),
            "average": round(sum(nums) / len(nums), 2),
            "evaluated_average": round(sum(eval_values) / len(eval_values), 4),
            "distribution": val_counts,
        }

    # 3. Numeric Check
    parsed_numbers = []
    for v in clean_values:
        val_str = str(v).strip().rstrip("%")
        try:
            parsed_numbers.append(float(val_str))
        except ValueError:
            pass

    if len(parsed_numbers) / non_null_count >= 0.8:
        return {
            "detected_type": "numeric",
            "recommended_roles": ["filter", "measure"],
            "non_null_count": non_null_count,
            "null_count": null_count,
            "null_percentage": null_pct,
            "distinct_count": distinct_count,
            "distinct_values_sample": sample_values,
            "min": round(min(parsed_numbers), 2),
            "max": round(max(parsed_numbers), 2),
            "average": round(sum(parsed_numbers) / len(parsed_numbers), 2),
        }

    # 4. Boolean Check
    bool_set = {"true", "false", "yes", "no", "1", "0"}
    if all(str(v).strip().lower() in bool_set for v in clean_values):
        return {
            "detected_type": "boolean",
            "recommended_roles": ["filter", "dimension"],
            "non_null_count": non_null_count,
            "null_count": null_count,
            "null_percentage": null_pct,
            "distinct_count": distinct_count,
            "distinct_values_sample": sample_values,
            "distribution": val_counts,
        }

    # 5. Date / Datetime Check
    parsed_dates = []
    for v in clean_values:
        dt = _parse_date_string(str(v))
        if dt:
            parsed_dates.append(dt)

    if len(parsed_dates) / non_null_count >= 0.8:
        min_d = min(parsed_dates)
        max_d = max(parsed_dates)
        range_days = (max_d - min_d).days
        return {
            "detected_type": "datetime",
            "recommended_roles": ["filter", "time"],
            "non_null_count": non_null_count,
            "null_count": null_count,
            "null_percentage": null_pct,
            "distinct_count": distinct_count,
            "distinct_values_sample": sample_values,
            "min_date": min_d.isoformat(),
            "max_date": max_d.isoformat(),
            "range_days": range_days,
            "valid_count": len(parsed_dates),
            "invalid_count": non_null_count - len(parsed_dates),
        }

    # 6. Long Text Check
    avg_len = sum(len(str(v)) for v in clean_values) / non_null_count
    text_kw = {"comment", "step", "result", "desc", "detail", "summary"}
    if avg_len > 50 or any(kw in key_name.lower() for kw in text_kw):
        return {
            "detected_type": "text",
            "recommended_roles": ["detail", "text_analysis"],
            "non_null_count": non_null_count,
            "null_count": null_count,
            "null_percentage": null_pct,
            "distinct_count": distinct_count,
            "distinct_values_sample": sample_values[:3],
        }

    # 7. Categorical Check (Default for strings with reasonable cardinality)
    if distinct_count <= 30 or distinct_count < (non_null_count * 0.5):
        return {
            "detected_type": "categorical",
            "recommended_roles": ["filter", "dimension", "grouping"],
            "non_null_count": non_null_count,
            "null_count": null_count,
            "null_percentage": null_pct,
            "distinct_count": distinct_count,
            "distinct_values_sample": sample_values,
            "distribution": val_counts,
        }

    # Fallback High-Cardinality String
    return {
        "detected_type": "unknown",
        "recommended_roles": ["detail"],
        "non_null_count": non_null_count,
        "null_count": null_count,
        "null_percentage": null_pct,
        "distinct_count": distinct_count,
        "distinct_values_sample": sample_values[:5],
    }


def profile_project_data(
    project_id: str | None = None,
    filters: dict | None = None
) -> Dict[str, Any]:
    """
    Profile bug_reports dataset for a specific project or across all projects.

    Returns a structured dictionary containing field types, ranges, sample values,
    role recommendations, data quality alerts, analytical opportunities, and dataset summary.
    """
    # Sanitize & validate project_id if provided
    valid_proj_id: Optional[str] = None
    if project_id and str(project_id).strip():
        try:
            valid_proj_id = str(UUID(str(project_id).strip()))
        except ValueError:
            raise ValueError(f"Invalid project_id UUID format: '{project_id}'")

    with replica_cursor() as cur:
        # Resolve Project Information
        proj_meta = {"id": valid_proj_id, "name": "All Projects", "code": "ALL"}
        if valid_proj_id:
            cur.execute("SELECT id, name, code FROM bug_projects WHERE id = %s", (valid_proj_id,))
            p_row = cur.fetchone()
            if not p_row:
                cur.execute("SELECT project_id FROM bug_reports WHERE project_id = %s LIMIT 1", (valid_proj_id,))
                if not cur.fetchone():
                    raise ValueError(f"Project with ID '{valid_proj_id}' not found.")
                proj_meta = {"id": valid_proj_id, "name": f"Project {valid_proj_id[:8]}", "code": "PRJ"}
            else:
                proj_meta = {"id": str(p_row["id"]), "name": p_row["name"], "code": p_row["code"]}

        # Build WHERE clause
        where_conds = []
        where_params: List[Any] = []
        if valid_proj_id:
            where_conds.append("project_id = %s")
            where_params.append(valid_proj_id)

        # Handle filter context if supplied
        if filters:
            for k, v in filters.items():
                if v is None:
                    continue
                # Date range filters
                if k in ("start", "date_range_start", "created_after"):
                    where_conds.append("created_at >= %s")
                    where_params.append(v)
                elif k in ("end", "date_range_end", "created_before"):
                    where_conds.append("created_at <= %s")
                    where_params.append(v)
                elif k in ("severity", "status", "reported_by", "project_id"):
                    if isinstance(v, (list, tuple, set)):
                        v_list = [str(x) for x in v if x is not None]
                        if v_list:
                            where_conds.append(f"{k}::text = ANY(%s)")
                            where_params.append(v_list)
                    else:
                        if str(v).strip() != "":
                            where_conds.append(f"{k}::text = %s")
                            where_params.append(str(v))
                elif k in ("issue_no", "source_record_id", "bug"):
                    clean_v = str(v).strip()
                    alt_v = f"{clean_v}#" if not clean_v.endswith("#") else clean_v
                    raw_num = clean_v.strip("#").strip()
                    where_conds.append("(dynamic_fields->>'source_record_id' = %s OR dynamic_fields->>'issue_no' = %s OR dynamic_fields->>'clean_issue_no' = %s OR dynamic_fields->>'source_record_id' = %s)")
                    where_params.extend([clean_v, clean_v, raw_num, alt_v])
                else:
                    if isinstance(v, (list, tuple, set)):
                        v_list = [str(x) for x in v if x is not None]
                        if v_list:
                            where_conds.append("dynamic_fields->>%s = ANY(%s)")
                            where_params.extend([k, v_list])
                    else:
                        if str(v).strip() != "":
                            where_conds.append("dynamic_fields->>%s = %s")
                            where_params.extend([k, str(v)])

        where_clause = f"WHERE {' AND '.join(where_conds)}" if where_conds else ""

        # Query total record count
        cur.execute(f"SELECT COUNT(*)::int AS total FROM bug_reports {where_clause}", where_params)
        total_records = cur.fetchone()["total"]

        if total_records == 0:
            return {
                "project": proj_meta,
                "dataset_summary": {
                    "total_records": 0,
                    "projects": proj_meta["name"],
                    "date_range": {"min": None, "max": None},
                },
                "record_count": 0,
                "profiled_at": datetime.now().isoformat(),
                "standard_fields": [],
                "dynamic_fields": [],
                "analytical_opportunities": [],
                "data_quality": {
                    "total_records": 0,
                    "fields_with_missing_values": [],
                    "fields_with_high_cardinality": [],
                    "fields_with_invalid_dates": [],
                },
            }

        # Query global date bounds for dataset_summary
        cur.execute(f"SELECT MIN(created_at) AS min_d, MAX(created_at) AS max_d FROM bug_reports {where_clause}", where_params)
        ds_dates = cur.fetchone()
        ds_min = ds_dates["min_d"].isoformat() if ds_dates and ds_dates["min_d"] else None
        ds_max = ds_dates["max_d"].isoformat() if ds_dates and ds_dates["max_d"] else None

        # ── 1. Standard Fields Profiling ──
        standard_field_names = [
            "severity",
            "status",
            "created_at",
            "updated_at",
            "project_id",
            "reported_by",
            "title",
            "summary",
        ]
        standard_profiles: List[Dict[str, Any]] = []

        for f_name in standard_field_names:
            if f_name in ("created_at", "updated_at"):
                cur.execute(f"""
                    SELECT COUNT({f_name})::int AS non_null,
                           COUNT(DISTINCT {f_name})::int AS distinct_cnt,
                           MIN({f_name}) AS min_val,
                           MAX({f_name}) AS max_val
                    FROM bug_reports {where_clause}
                """, where_params)
                stats = cur.fetchone()
                non_null = stats["non_null"]
                null_cnt = total_records - non_null
                null_pct = round((null_cnt / total_records * 100.0), 1)
                min_d = stats["min_val"]
                max_d = stats["max_val"]
                range_days = (max_d - min_d).days if (min_d and max_d) else 0

                sub_conds = list(where_conds) + [f"{f_name} IS NOT NULL"]
                sub_where = f"WHERE {' AND '.join(sub_conds)}"
                cur.execute(f"""
                    SELECT DISTINCT {f_name}::text AS v
                    FROM bug_reports {sub_where}
                    LIMIT 10
                """, where_params)
                samples = [r["v"] for r in cur.fetchall()]

                standard_profiles.append({
                    "name": f_name,
                    "source": "standard",
                    "database_type": "timestamp with time zone",
                    "detected_type": "datetime",
                    "record_count": total_records,
                    "non_null_count": non_null,
                    "null_count": null_cnt,
                    "null_percentage": null_pct,
                    "distinct_count": stats["distinct_cnt"],
                    "distinct_values_sample": samples,
                    "min_date": min_d.isoformat() if min_d else None,
                    "max_date": max_d.isoformat() if max_d else None,
                    "range_days": range_days,
                    "recommended_roles": ["filter", "time"],
                })
            else:
                cur.execute(f"""
                    SELECT {f_name}::text AS val
                    FROM bug_reports {where_clause}
                """, where_params)
                vals = [r["val"] for r in cur.fetchall()]

                prof = _infer_field_type_and_roles(f_name, vals, total_records)
                prof["name"] = f_name
                prof["source"] = "standard"
                prof["database_type"] = "uuid" if f_name in ("project_id", "reported_by") else "text"
                prof["record_count"] = total_records

                # Override standard field specific roles if needed
                if f_name in ("severity", "status"):
                    prof["detected_type"] = "categorical"
                    prof["recommended_roles"] = ["filter", "dimension", "grouping"]
                elif f_name == "project_id":
                    prof["detected_type"] = "identifier"
                    prof["recommended_roles"] = ["filter"]
                elif f_name == "reported_by":
                    prof["detected_type"] = "identifier"
                    prof["recommended_roles"] = ["filter", "dimension"]
                elif f_name in ("title", "summary"):
                    prof["detected_type"] = "text"
                    prof["recommended_roles"] = ["detail", "text_analysis"]

                standard_profiles.append(prof)

        # ── 2. Dynamic JSONB Field Discovery & Profiling ──
        jsonb_conds = list(where_conds) + ["dynamic_fields IS NOT NULL"]
        jsonb_where = f"WHERE {' AND '.join(jsonb_conds)}"
        cur.execute(f"""
            SELECT DISTINCT jsonb_object_keys(dynamic_fields) AS key
            FROM bug_reports
            {jsonb_where}
            ORDER BY key
        """, where_params)
        jsonb_keys = [r["key"] for r in cur.fetchall()]

        dynamic_profiles: List[Dict[str, Any]] = []

        for key_name in jsonb_keys:
            cur.execute(f"""
                SELECT dynamic_fields->>%s AS val
                FROM bug_reports
                {where_clause}
            """, [key_name, *where_params])
            vals = [r["val"] for r in cur.fetchall()]

            prof = _infer_field_type_and_roles(key_name, vals, total_records)
            prof["name"] = key_name
            prof["source"] = "dynamic"
            prof["database_type"] = "jsonb"
            prof["record_count"] = total_records

            dynamic_profiles.append(prof)

        # ── 3. Analytical Opportunities Detection ──
        opportunities: List[Dict[str, Any]] = []
        all_fields = standard_profiles + dynamic_profiles

        categorical_fields = [
            f for f in all_fields
            if f["detected_type"] == "categorical" and "dimension" in f["recommended_roles"]
        ]
        time_fields = [f for f in all_fields if f["detected_type"] in ("datetime", "date")]
        numeric_fields = [f for f in all_fields if f["detected_type"] in ("numeric", "ratio")]

        for cf in categorical_fields:
            opportunities.append({
                "type": "categorical_distribution",
                "field": cf["name"],
                "reason": f"{cf['distinct_count']} distinct values with {100.0 - cf['null_percentage']:.1f}% data coverage",
            })

        for tf in time_fields:
            opportunities.append({
                "type": "time_series",
                "field": tf["name"],
                "reason": f"Temporal field available spanning {tf.get('range_days', 0)} days across {tf['non_null_count']} records",
            })

        for nf in numeric_fields:
            opportunities.append({
                "type": "numeric_analysis" if nf["detected_type"] == "numeric" else "ratio_analysis",
                "field": nf["name"],
                "reason": f"{nf['detected_type'].capitalize()} metric detected with range [{nf.get('min')}, {nf.get('max')}]",
            })

        if len(categorical_fields) >= 2:
            c_names = [cf["name"] for cf in categorical_fields[:3]]
            opportunities.append({
                "type": "cross_analysis",
                "fields": c_names,
                "reason": "Multiple low-cardinality categorical dimensions available for cross-tabulation",
            })

        # ── 4. Data Quality Section ──
        missing_vals = [
            {"field": f["name"], "null_percentage": f["null_percentage"]}
            for f in all_fields if f["null_percentage"] > 0
        ]

        high_cardinality = [
            {"field": f["name"], "distinct_count": f["distinct_count"]}
            for f in all_fields
            if f["distinct_count"] > 30 and f["detected_type"] not in ("text", "identifier", "datetime")
        ]

        invalid_dates = [
            {"field": f["name"], "invalid_count": f.get("invalid_count", 0)}
            for f in all_fields
            if f.get("invalid_count", 0) > 0
        ]

        data_quality = {
            "total_records": total_records,
            "fields_with_missing_values": missing_vals,
            "fields_with_high_cardinality": high_cardinality,
            "fields_with_invalid_dates": invalid_dates,
        }

        return {
            "project": proj_meta,
            "dataset_summary": {
                "total_records": total_records,
                "projects": proj_meta["name"],
                "date_range": {
                    "min": ds_min,
                    "max": ds_max,
                },
            },
            "record_count": total_records,
            "profiled_at": datetime.now().isoformat(),
            "standard_fields": standard_profiles,
            "dynamic_fields": dynamic_profiles,
            "analytical_opportunities": opportunities,
            "data_quality": data_quality,
        }


def query_dynamic_metric(
    field_name: str,
    project_id: str | None = None,
    metric: str = "count",
    filters: dict | None = None,
    limit: int = 20
) -> Dict[str, Any]:
    """
    Safely query standard or dynamic JSONB field values aggregated by metric.
    Strictly protects against protected identifiers and unvalidated SQL injection.
    """
    if _is_protected_identifier(field_name):
        raise ValueError(f"Protected identifier '{field_name}' cannot be queried as a dimension.")

    if not re.match(r"^[a-zA-Z0-9_ -]+$", field_name):
        raise ValueError(f"Invalid field_name format: '{field_name}'")

    standard_cols = {"severity", "status", "created_at", "updated_at", "reported_by", "project_id", "title", "summary"}
    is_standard = field_name.lower() in standard_cols

    with replica_cursor() as cur:
        where_conds = []
        where_params: List[Any] = []

        if project_id and str(project_id).strip():
            try:
                valid_proj_id = str(UUID(str(project_id).strip()))
                where_conds.append("project_id = %s")
                where_params.append(valid_proj_id)
            except ValueError:
                pass

        if filters:
            for k, v in filters.items():
                if v is None:
                    continue
                if k in ("severity", "status", "reported_by", "project_id"):
                    if isinstance(v, (list, tuple, set)):
                        v_list = [str(x) for x in v if x is not None]
                        if v_list:
                            where_conds.append(f"{k}::text = ANY(%s)")
                            where_params.append(v_list)
                    elif str(v).strip() != "":
                        where_conds.append(f"{k}::text = %s")
                        where_params.append(str(v))
                elif k in ("issue_no", "source_record_id", "bug"):
                    clean_v = str(v).strip()
                    alt_v = f"{clean_v}#" if not clean_v.endswith("#") else clean_v
                    raw_num = clean_v.strip("#").strip()
                    where_conds.append("(dynamic_fields->>'source_record_id' = %s OR dynamic_fields->>'issue_no' = %s OR dynamic_fields->>'clean_issue_no' = %s OR dynamic_fields->>'source_record_id' = %s)")
                    where_params.extend([clean_v, clean_v, raw_num, alt_v])
                else:
                    if isinstance(v, (list, tuple, set)):
                        v_list = [str(x) for x in v if x is not None]
                        if v_list:
                            where_conds.append("dynamic_fields->>%s = ANY(%s)")
                            where_params.extend([k, v_list])
                    elif str(v).strip() != "":
                        where_conds.append("dynamic_fields->>%s = %s")
                        where_params.extend([k, str(v)])

        if is_standard:
            field_expr = f"{field_name}::text"
            where_conds.append(f"{field_name} IS NOT NULL")
        else:
            field_expr = "dynamic_fields->>%s"
            where_params.insert(0, field_name)
            where_conds.append("dynamic_fields->>%s IS NOT NULL")
            where_params.append(field_name)

        where_clause = f"WHERE {' AND '.join(where_conds)}"

        cur.execute(f"""
            SELECT {field_expr} AS label, COUNT(*)::bigint AS value
            FROM bug_reports
            {where_clause}
            GROUP BY 1
            ORDER BY value DESC
            LIMIT %s
        """, [*where_params, limit])

        rows = [dict(r) for r in cur.fetchall()]
        return {
            "field": field_name,
            "metric": metric,
            "data": rows
        }



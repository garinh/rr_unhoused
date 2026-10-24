"""
Stage 1: Ingestion & Schema Alignment
All agency column mappings live in input/schemas/*.json — no hard-coded field names here.
New trading partners are onboarded by dropping a JSON schema file; no code changes needed.
"""

import json
import os

import pandas as pd

INPUT_DIR = os.path.join(os.path.dirname(__file__), "input")
SCHEMA_DIR = os.path.join(INPUT_DIR, "schemas")

DEMO_COLUMNS = [
    "unique_record_id",
    "source_system",
    "source_id",
    "first_name",
    "last_name",
    "dob",
    "ssn_last4",
    "encounter_date",
]

ENCOUNTER_COLUMNS = [
    "encounter_id",
    "unique_record_id",
    "source_system",
    "encounter_date",
    "service_category",
    "location_info",
    "location_zip",
]


def _path(filename: str) -> str:
    """Return absolute path to filename, checking input/ then input/archive/ as fallback."""
    primary = os.path.join(INPUT_DIR, filename)
    if os.path.exists(primary):
        return primary
    archive = os.path.join(INPUT_DIR, "archive", filename)
    return archive  # caller checks os.path.exists


def _load_schema_registry() -> list[dict]:
    """Return all agency schemas from input/schemas/*.json, sorted by filename."""
    schemas = []
    if not os.path.isdir(SCHEMA_DIR):
        return schemas
    for fn in sorted(os.listdir(SCHEMA_DIR)):
        if fn.endswith(".json"):
            with open(os.path.join(SCHEMA_DIR, fn), encoding="utf-8") as fh:
                schemas.append(json.load(fh))
    return schemas


# ── Field extraction helpers ──────────────────────────────────────────────────

def _extract_ssn(value, ssn_type: str) -> str:
    raw = str(value) if pd.notna(value) else ""
    if not raw or raw in ("nan", "None"):
        return ""
    if ssn_type == "full":
        digits = "".join(c for c in raw if c.isdigit())
        return digits[-4:] if len(digits) >= 4 else ""
    if ssn_type == "last4":
        try:
            int_val = str(int(float(raw)))
            return int_val.zfill(4)[-4:]
        except (ValueError, TypeError):
            return ""
    return ""  # "none" or unrecognised


def _resolve_first_name(row, cols: dict, special: str, special_config: dict) -> str:
    """Return first name, preferring alias column when special == 'alias_preferred'."""
    if special == "alias_preferred":
        alias_col = special_config.get("alias_col", "")
        if alias_col:
            alias = str(row.get(alias_col, "")).strip()
            if alias and alias not in ("nan", "None"):
                return alias
    fn_col = cols.get("first_name")
    if fn_col and pd.notna(row.get(fn_col)):
        return str(row[fn_col]).strip()
    return ""


def _resolve_initials(row, cols: dict) -> tuple[str, str]:
    """Split initials string ('J.S.' or 'JS') into (first_initial, last_initial)."""
    col = cols.get("first_name")
    raw = str(row.get(col, "")).replace(".", "").strip() if col else ""
    parts = raw.split()
    first = parts[0] if parts else (raw[0] if raw else "")
    last = parts[1] if len(parts) >= 2 else (raw[1:] if len(raw) >= 2 else "")
    return first, last


def _resolve_dob(row, cols: dict, special: str, special_config: dict) -> str:
    dob_col = cols.get("dob")
    if not dob_col or not pd.notna(row.get(dob_col)):
        return ""
    raw = row[dob_col]
    if special == "initials_and_birth_year" and special_config.get("dob_format") == "year_only":
        try:
            return f"{int(float(raw))}-01-01"
        except (ValueError, TypeError):
            return ""
    return str(raw)


# ── Generic agency loader ─────────────────────────────────────────────────────

def load_agency_from_schema(schema: dict) -> tuple[list[dict], list[dict]]:
    """Load one trading partner's client + services CSVs using its schema mapping."""
    demo: list[dict] = []
    encounters: list[dict] = []

    source_system = schema["source_system"]
    cols          = schema.get("columns", {})
    ssn_type      = schema.get("ssn_type", "none")
    special       = schema.get("special") or ""
    special_cfg   = schema.get("special_config") or {}

    client_path = _path(schema.get("client_file", ""))
    if not os.path.exists(client_path):
        return demo, encounters

    df = pd.read_csv(client_path, encoding="utf-8-sig")
    client_id_col   = cols.get("client_id")
    enc_date_col    = cols.get("encounter_date")
    ssn_col         = cols.get("ssn")
    last_name_col   = cols.get("last_name")

    for _, row in df.iterrows():
        client_id = str(row[client_id_col]).strip() if client_id_col and pd.notna(row.get(client_id_col)) else ""

        if special == "initials_and_birth_year":
            first_name, last_name = _resolve_initials(row, cols)
        else:
            first_name = _resolve_first_name(row, cols, special, special_cfg)
            last_name  = str(row[last_name_col]).strip() if last_name_col and pd.notna(row.get(last_name_col)) else ""

        demo.append({
            "unique_record_id": f"{source_system}::{client_id}",
            "source_system":    source_system,
            "source_id":        client_id,
            "first_name":       first_name,
            "last_name":        last_name,
            "dob":              _resolve_dob(row, cols, special, special_cfg),
            "ssn_last4":        _extract_ssn(row.get(ssn_col) if ssn_col else None, ssn_type),
            "encounter_date":   str(row[enc_date_col])[:10] if enc_date_col and pd.notna(row.get(enc_date_col)) else "",
        })

    # ── Services ─────────────────────────────────────────────────────────
    svc_cols  = schema.get("services_columns", {})
    svc_file  = schema.get("services_file", "")
    if not svc_cols or not svc_file:
        return demo, encounters

    svc_path = _path(svc_file)
    if not os.path.exists(svc_path):
        return demo, encounters

    df_svc = pd.read_csv(svc_path, encoding="utf-8-sig")
    enc_id_col      = svc_cols.get("encounter_id")
    svc_cid_col     = svc_cols.get("client_id")
    svc_date_col    = svc_cols.get("encounter_date")
    svc_cat_col     = svc_cols.get("service_category")
    svc_cat_static  = svc_cols.get("service_category_static")
    svc_cat_prefix  = svc_cols.get("service_category_prefix", "")
    loc_col         = svc_cols.get("location_info")
    loc_prefix      = svc_cols.get("location_info_prefix", "")
    loc_template    = svc_cols.get("location_info_template")
    zip_col         = svc_cols.get("location_zip")

    for _, row in df_svc.iterrows():
        enc_id   = str(row[enc_id_col]).strip()  if enc_id_col  and pd.notna(row.get(enc_id_col))  else ""
        svc_cid  = str(row[svc_cid_col]).strip() if svc_cid_col and pd.notna(row.get(svc_cid_col)) else ""
        svc_date = str(row[svc_date_col])         if svc_date_col and pd.notna(row.get(svc_date_col)) else ""

        if svc_cat_static:
            svc_cat = svc_cat_static
        elif svc_cat_col and pd.notna(row.get(svc_cat_col)):
            svc_cat = f"{svc_cat_prefix}{row[svc_cat_col]}"
        else:
            svc_cat = ""

        if loc_template:
            try:
                loc = loc_template.format(**{c: row.get(c, 0) for c in df_svc.columns})
            except (KeyError, ValueError):
                loc = ""
        elif loc_col and pd.notna(row.get(loc_col)):
            loc = f"{loc_prefix}{row[loc_col]}"
        else:
            loc = ""

        zip_val = str(row[zip_col]).strip() if zip_col and pd.notna(row.get(zip_col)) else ""

        encounters.append({
            "encounter_id":    enc_id,
            "unique_record_id": f"{source_system}::{svc_cid}",
            "source_system":   source_system,
            "encounter_date":  svc_date,
            "service_category": svc_cat,
            "location_info":   loc,
            "location_zip":    zip_val,
        })

    return demo, encounters


# ── Orchestrator ──────────────────────────────────────────────────────────────

def ingest() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load all trading partners via schema registry; return (df_demo, df_encounters)."""
    schemas = _load_schema_registry()
    assert schemas, "[AGENTIC CHECK FAILED] No schema files found in input/schemas/."

    all_demo: list[dict] = []
    all_encounters: list[dict] = []
    source_counts: dict[str, int] = {}

    for schema in schemas:
        demo_rows, enc_rows = load_agency_from_schema(schema)
        src = schema["source_system"]
        source_counts[src] = len(demo_rows)
        all_demo.extend(demo_rows)
        all_encounters.extend(enc_rows)

    df_demo       = pd.DataFrame(all_demo,       columns=DEMO_COLUMNS)
    df_encounters = pd.DataFrame(all_encounters, columns=ENCOUNTER_COLUMNS)

    # ── Agentic Validation ────────────────────────────────────────────────
    for schema in schemas:
        expected = schema.get("expected_count")
        if expected is not None:
            src    = schema["source_system"]
            actual = source_counts[src]
            assert actual == expected, (
                f"[AGENTIC CHECK FAILED] {schema['label']}: expected {expected} records, got {actual}"
            )

    assert df_demo["unique_record_id"].is_unique, (
        "[AGENTIC CHECK FAILED] Duplicate unique_record_id values detected:\n"
        + str(df_demo[df_demo["unique_record_id"].duplicated()]["unique_record_id"].tolist())
    )
    assert not df_demo["unique_record_id"].isnull().any(), \
        "[AGENTIC CHECK FAILED] Null unique_record_id values found."

    loaded = [s for s, c in source_counts.items() if c > 0]
    print(f"[AGENTIC CHECK PASSED] Ingested {len(df_demo)} demographic records across {len(loaded)} sources.")
    print(f"[AGENTIC CHECK PASSED] Ingested {len(df_encounters)} service encounter rows.")
    for schema in schemas:
        src   = schema["source_system"]
        count = source_counts.get(src, 0)
        status = f"{count} records" if count > 0 else "skipped (file absent)"
        print(f"  {schema['label']}: {status}")

    return df_demo, df_encounters


if __name__ == "__main__":
    df_demo, df_encounters = ingest()
    print("\nSample demographic output:")
    print(df_demo.head(3).to_string(index=False))
    print("\nSample encounter output:")
    print(df_encounters.head(3).to_string(index=False))

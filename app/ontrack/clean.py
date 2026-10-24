"""
Stage 2: Standardization & Cleaning
Receives the raw ingested dataframes from ingest.py and produces a cleaned
demographic dataframe with these additional columns:
  - first_name_clean : lowercase, alpha-only (spaces kept)
  - last_name_clean  : lowercase, alpha-only (spaces kept)
  - dob_clean        : YYYY-MM-DD string or "" if unparseable
  - ssn_clean        : exactly 4 digits or ""
  - encounter_date_clean : YYYY-MM-DD string or ""
"""

import re
import pandas as pd
from ingest import ingest


_DATE_CLEAN_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_SSN_CLEAN_RE  = re.compile(r"^\d{4}$")


def _normalize_name(series: pd.Series) -> pd.Series:
    return (
        series.astype(str)
        .str.strip()
        .str.lower()
        .str.replace(r"[^a-z\s]", "", regex=True)
        .str.strip()
    )


def _normalize_date(series: pd.Series) -> pd.Series:
    """Parse ISO and M/D/YYYY date formats into YYYY-MM-DD; invalid → ''.

    pandas 2.0 no longer auto-infers mixed formats, so we use format='mixed'
    with dayfirst=False to prefer M/D/YYYY over D/M/YYYY for ambiguous values.
    Genuinely invalid dates (month=00, month=13, etc.) coerce to NaT → ''.
    """
    parsed = pd.to_datetime(series, errors="coerce", format="mixed", dayfirst=False)
    return parsed.dt.strftime("%Y-%m-%d").fillna("")


def _normalize_ssn(series: pd.Series) -> pd.Series:
    """Extract up to 4 digits from raw ssn_last4 field; anything other than exactly 4 → ''."""
    def extract(val):
        raw = str(val).strip() if pd.notna(val) else ""
        digits = re.sub(r"\D", "", raw)
        # Take last 4 if we have ≥4, zero-pad if fewer
        if len(digits) == 0:
            return ""
        if len(digits) >= 4:
            return digits[-4:]
        return digits.zfill(4)  # e.g. "123" → "0123"

    cleaned = series.map(extract)
    # Blank out anything that still doesn't match ^\d{4}$
    return cleaned.where(cleaned.str.match(r"^\d{4}$", na=False), other="")


def clean(df_demo: pd.DataFrame) -> pd.DataFrame:
    """Apply all standardization rules and return an augmented dataframe."""
    df = df_demo.copy()

    df["first_name_clean"]      = _normalize_name(df["first_name"])
    df["last_name_clean"]       = _normalize_name(df["last_name"])
    df["dob_clean"]             = _normalize_date(df["dob"])
    df["ssn_clean"]             = _normalize_ssn(df["ssn_last4"])
    df["encounter_date_clean"]  = _normalize_date(df["encounter_date"])
    # Sorted-char fingerprint: anagram-equivalent names collapse to the same key
    # ("johnson" and "jonhson" both → "hjnnoos") — used as a Splink training block
    # so the Lev-1 last_name m-probability can be properly estimated.
    df["last_name_sorted_chars"] = df["last_name_clean"].apply(
        lambda x: "".join(sorted(x)) if x else ""
    )

    # ── Agentic Validation ──────────────────────────────────────────────

    # 1. No raw-format date strings should survive in dob_clean or encounter_date_clean
    bad_dob = df[df["dob_clean"].ne("") & ~df["dob_clean"].str.match(r"^\d{4}-\d{2}-\d{2}$")]
    assert bad_dob.empty, (
        f"[AGENTIC CHECK FAILED] {len(bad_dob)} dob_clean values not in YYYY-MM-DD:\n"
        f"{bad_dob[['unique_record_id','dob','dob_clean']].to_string(index=False)}"
    )

    bad_enc = df[df["encounter_date_clean"].ne("") & ~df["encounter_date_clean"].str.match(r"^\d{4}-\d{2}-\d{2}$")]
    assert bad_enc.empty, (
        f"[AGENTIC CHECK FAILED] {len(bad_enc)} encounter_date_clean values not in YYYY-MM-DD:\n"
        f"{bad_enc[['unique_record_id','encounter_date','encounter_date_clean']].to_string(index=False)}"
    )

    # 2. ssn_clean must be exactly 4 digits or empty string — nothing else allowed
    bad_ssn = df[df["ssn_clean"].ne("") & ~df["ssn_clean"].str.match(r"^\d{4}$")]
    assert bad_ssn.empty, (
        f"[AGENTIC CHECK FAILED] {len(bad_ssn)} ssn_clean values fail ^\\d{{4}}$ pattern:\n"
        f"{bad_ssn[['unique_record_id','ssn_last4','ssn_clean']].to_string(index=False)}"
    )

    # 3. Name clean columns must exist and contain no null values
    for col in ("first_name_clean", "last_name_clean"):
        assert col in df.columns, f"[AGENTIC CHECK FAILED] Missing column: {col}"
        assert df[col].notna().all(), f"[AGENTIC CHECK FAILED] Null values in {col}"

    # 4. Record count must be unchanged from input
    assert len(df) == len(df_demo), (
        f"[AGENTIC CHECK FAILED] Row count changed: {len(df_demo)} in → {len(df)} out"
    )

    # Summary stats
    ssn_populated   = df["ssn_clean"].ne("").sum()
    dob_populated   = df["dob_clean"].ne("").sum()
    dob_unparseable = df["dob"].ne("") & df["dob_clean"].eq("")

    print("[AGENTIC CHECK PASSED] All cleaning validations passed.")
    print(f"  Records cleaned          : {len(df)}")
    print(f"  dob_clean populated      : {dob_populated} / {len(df)}")
    print(f"  dob unparseable -> blank : {dob_unparseable.sum()}")
    print(f"  ssn_clean populated      : {ssn_populated} / {len(df)}")

    return df


if __name__ == "__main__":
    import os

    OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    df_demo, df_encounters = ingest()
    df_clean = clean(df_demo)

    # ── Write outputs ───────────────────────────────────────────────────
    demo_out = os.path.join(OUTPUT_DIR, "stage2_clean_demographics.csv")
    enc_out  = os.path.join(OUTPUT_DIR, "stage1_encounters_raw.csv")

    df_clean.to_csv(demo_out, index=False)
    df_encounters.to_csv(enc_out, index=False)

    print(f"\n[OUTPUT] {demo_out}  ({len(df_clean)} rows)")
    print(f"[OUTPUT] {enc_out}  ({len(df_encounters)} rows)")

    print("\nSample cleaned output (first 5 rows):")
    cols = ["unique_record_id", "first_name_clean", "last_name_clean", "dob_clean", "ssn_clean", "encounter_date_clean"]
    print(df_clean[cols].head(5).to_string(index=False))

    print("\nUnparseable DOBs (coerced to blank):")
    unparseable = df_clean[(df_clean["dob"].ne("")) & (df_clean["dob_clean"].eq(""))]
    if unparseable.empty:
        print("  None")
    else:
        print(unparseable[["unique_record_id", "source_system", "dob"]].to_string(index=False))

    print("\nSSN coverage by source:")
    print(
        df_clean.groupby("source_system")["ssn_clean"]
        .apply(lambda s: f"{s.ne('').sum()}/{len(s)} populated")
        .to_string()
    )

"""
Stage 5: Multi-Table CSV Suite Export
Joins cluster assignments, clean demographics, and raw encounters to produce
the 3-CSV handoff model in output/:

  dim_master_persons.csv   — one row per deduplicated person (MPI)
  bridge_record_links.csv  — every raw record mapped to its MPI
  fact_encounters.csv      — all service encounters joined to MPIs
"""

import os
import pandas as pd

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")

# Source priority for canonical name/DOB selection (higher index = lower priority)
SOURCE_PRIORITY = ["ACCESS_HUD", "ROGUE_RETREAT", "RECOVERY_CAFE", "JACKSON_COUNTY_SSP"]


def load_inputs() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    paths = {
        "demo":       os.path.join(OUTPUT_DIR, "stage2_clean_demographics.csv"),
        "clusters":   os.path.join(OUTPUT_DIR, "stage4_clusters.csv"),
        "encounters": os.path.join(OUTPUT_DIR, "stage1_encounters_raw.csv"),
    }
    for label, p in paths.items():
        assert os.path.exists(p), (
            f"[AGENTIC CHECK FAILED] Required input '{label}' not found: {p}"
        )

    df_demo      = pd.read_csv(paths["demo"],       dtype=str).fillna("")
    df_clusters  = pd.read_csv(paths["clusters"],   dtype=str).fillna("")
    df_encounters = pd.read_csv(paths["encounters"], dtype=str).fillna("")
    return df_demo, df_clusters, df_encounters


def _canonical_name(group: pd.DataFrame) -> pd.Series:
    """Pick canonical first/last name by majority vote (mode) across the cluster.

    Using the most-frequent name rather than the highest-priority source avoids
    promoting a single-source typo (e.g. 'iLnda' in ACCESS) over the majority
    spelling shared by other agencies.
    """
    first_mode = group["first_name_clean"][group["first_name_clean"].ne("")].mode()
    last_mode  = group["last_name_clean"][group["last_name_clean"].ne("")].mode()
    first = first_mode.iloc[0].strip().title() if not first_mode.empty else ""
    last  = last_mode.iloc[0].strip().title()  if not last_mode.empty  else ""
    return pd.Series({"canonical_first_name": first, "canonical_last_name": last})


def build_dim_master_persons(df_working: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for mpi, group in df_working.groupby("master_person_id"):
        names = _canonical_name(group)

        # Most common DOB wins; blank if all are empty
        dob_mode = group["dob_clean"][group["dob_clean"].ne("")].mode()
        canonical_dob = dob_mode.iloc[0] if not dob_mode.empty else ""

        # First non-empty SSN across cluster (prefer ACCESS, then RR)
        ssn_vals = group[group["ssn_clean"].ne("")].sort_values(
            "source_system",
            key=lambda s: s.map({v: i for i, v in enumerate(SOURCE_PRIORITY)})
        )
        canonical_ssn = ssn_vals["ssn_clean"].iloc[0] if not ssn_vals.empty else ""

        rows.append({
            "master_person_id":      mpi,
            "canonical_first_name":  names["canonical_first_name"],
            "canonical_last_name":   names["canonical_last_name"],
            "canonical_dob":         canonical_dob,
            "canonical_ssn_last4":   canonical_ssn,
            "total_linked_records":  len(group),
            "linked_sources_count":  group["source_system"].nunique(),
            "contributing_sources":  ", ".join(sorted(group["source_system"].unique())),
        })

    return pd.DataFrame(rows)


def build_bridge_record_links(df_working: pd.DataFrame) -> pd.DataFrame:
    return df_working[[
        "unique_record_id",
        "master_person_id",
        "source_system",
        "source_id",
        "match_confidence",
        "match_type",
    ]].copy()


def build_fact_encounters(df_encounters: pd.DataFrame, df_working: pd.DataFrame) -> pd.DataFrame:
    mpi_map = df_working.set_index("unique_record_id")["master_person_id"]
    df_fact = df_encounters.copy()
    df_fact["master_person_id"] = df_fact["unique_record_id"].map(mpi_map)

    return df_fact[[
        "encounter_id",
        "master_person_id",
        "unique_record_id",
        "source_system",
        "encounter_date",
        "service_category",
        "location_info",
        "location_zip",
    ]]


def export() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    df_demo, df_clusters, df_encounters = load_inputs()

    # Merge cluster assignments into the clean demographics
    df_working = df_demo.merge(
        df_clusters[["unique_record_id", "master_person_id", "match_confidence", "match_type"]],
        on="unique_record_id",
        how="left",
    )

    dim_master_persons  = build_dim_master_persons(df_working)
    bridge_record_links = build_bridge_record_links(df_working)
    fact_encounters     = build_fact_encounters(df_encounters, df_working)

    # ── Write outputs ────────────────────────────────────────────────────
    dim_path    = os.path.join(OUTPUT_DIR, "dim_master_persons.csv")
    bridge_path = os.path.join(OUTPUT_DIR, "bridge_record_links.csv")
    fact_path   = os.path.join(OUTPUT_DIR, "fact_encounters.csv")

    dim_master_persons.to_csv(dim_path,    index=False)
    bridge_record_links.to_csv(bridge_path, index=False)
    fact_encounters.to_csv(fact_path,      index=False)

    # ── Agentic Validation ───────────────────────────────────────────────

    # 1. All 3 files exist
    for label, p in [("dim_master_persons", dim_path),
                     ("bridge_record_links", bridge_path),
                     ("fact_encounters", fact_path)]:
        assert os.path.exists(p), f"[AGENTIC CHECK FAILED] {label}.csv was not generated."

    # 2. dim: every master_person_id is unique
    assert dim_master_persons["master_person_id"].is_unique, (
        "[AGENTIC CHECK FAILED] Duplicate master_person_id values in dim_master_persons."
    )

    # 3. bridge: every unique_record_id maps to exactly one master_person_id
    assert bridge_record_links["unique_record_id"].is_unique, (
        "[AGENTIC CHECK FAILED] Duplicate unique_record_ids in bridge_record_links."
    )
    bridge_nulls = bridge_record_links["master_person_id"].isna().sum()
    assert bridge_nulls == 0, (
        f"[AGENTIC CHECK FAILED] {bridge_nulls} records in bridge have no master_person_id."
    )

    # 4. bridge → dim FK integrity: every bridge MPI exists in dim
    bridge_mpis = set(bridge_record_links["master_person_id"])
    dim_mpis    = set(dim_master_persons["master_person_id"])
    orphan_mpis = bridge_mpis - dim_mpis
    assert not orphan_mpis, (
        f"[AGENTIC CHECK FAILED] {len(orphan_mpis)} MPIs in bridge not found in dim:\n"
        f"{sorted(orphan_mpis)[:5]}"
    )

    # 5. fact → dim FK integrity: every non-null MPI in fact exists in dim
    fact_mpis_set = set(fact_encounters["master_person_id"].dropna())
    orphan_fact   = fact_mpis_set - dim_mpis
    assert not orphan_fact, (
        f"[AGENTIC CHECK FAILED] {len(orphan_fact)} MPIs in fact_encounters not found in dim:\n"
        f"{sorted(orphan_fact)[:5]}"
    )

    # 6. fact encounters with no MPI (unique_record_id not in bridge) — warn, don't fail
    unmapped = fact_encounters["master_person_id"].isna().sum()
    if unmapped:
        print(f"  [WARN] {unmapped} encounter rows could not be mapped to an MPI "
              "(unique_record_id not present in demographics).")

    print("[AGENTIC CHECK PASSED] All 3 output CSVs generated and FK integrity verified.")
    print(f"  dim_master_persons  : {len(dim_master_persons)} rows  ({dim_master_persons['master_person_id'].nunique()} unique MPIs)")
    print(f"  bridge_record_links : {len(bridge_record_links)} rows")
    print(f"  fact_encounters     : {len(fact_encounters)} rows  ({fact_encounters['master_person_id'].notna().sum()} with MPI)")

    return dim_master_persons, bridge_record_links, fact_encounters


if __name__ == "__main__":
    dim, bridge, fact = export()

    print("\n── dim_master_persons (sample, multi-source clusters only) ──")
    multi = dim[dim["linked_sources_count"] > 1].head(8)
    print(multi[[
        "master_person_id", "canonical_first_name", "canonical_last_name",
        "canonical_dob", "total_linked_records", "contributing_sources"
    ]].to_string(index=False))

    print("\n── bridge_record_links (sample) ──")
    print(bridge.head(6).to_string(index=False))

    print("\n── fact_encounters (sample) ──")
    print(fact.head(6).to_string(index=False))

    print("\n── Cluster size distribution (from dim) ──")
    size_dist = (
        dim["total_linked_records"].value_counts().sort_index()
        .rename_axis("cluster_size").reset_index(name="num_master_persons")
    )
    print(size_dist.to_string(index=False))

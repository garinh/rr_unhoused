"""
generate_golden.py — Produce GOLDEN_PERSONS_ENCOUNTERS.csv

Joins dim_master_persons with fact_encounters so every service record
is enriched with canonical person attributes in one flat file.
Applies severed_links.csv splits before the join if present.

Requirements: pip install duckdb pandas  (already pipeline dependencies)
Usage: python generate_golden.py
"""

import os
import duckdb
import pandas as pd

DIM     = "output/dim_master_persons.csv"
BRIDGE  = "output/bridge_record_links.csv"
ENC     = "output/fact_encounters.csv"
SEVERED = "output/severed_links.csv"
OUT     = "output/GOLDEN_PERSONS_ENCOUNTERS.csv"

# Resolve effective source paths (apply severed_links splits if present)
_gdim   = DIM
_genc   = ENC

if os.path.exists(SEVERED) and os.path.exists(BRIDGE) and os.path.exists(DIM):
    sv_df = pd.read_csv(SEVERED, dtype=str)
    if not sv_df.empty:
        sv_map = dict(zip(sv_df["unique_record_id"], sv_df["split_mpi"]))

        bri_df = pd.read_csv(BRIDGE, dtype=str)
        bri_df["master_person_id"] = (
            bri_df["unique_record_id"].map(sv_map).fillna(bri_df["master_person_id"])
        )

        bri_grp = bri_df.groupby("master_person_id").agg(
            total_linked_records=("unique_record_id", "count"),
            linked_sources_count=("source_system", "nunique"),
            contributing_sources=("source_system", lambda x: ", ".join(sorted(set(x)))),
        ).reset_index()

        dim_df = pd.read_csv(DIM, dtype=str)

        seen_split: set[str] = set()
        new_rows = []
        for _, sv_row in sv_df.iterrows():
            split_mpi = sv_row["split_mpi"]
            orig_mpi  = sv_row["original_mpi"]
            if split_mpi in seen_split:
                continue
            seen_split.add(split_mpi)
            orig = dim_df[dim_df["master_person_id"] == orig_mpi]
            if not orig.empty:
                nr = orig.iloc[0].copy()
                nr["master_person_id"] = split_mpi
                new_rows.append(nr)

        if new_rows:
            extra = (
                pd.DataFrame(new_rows)
                .drop(columns=["total_linked_records", "linked_sources_count",
                               "contributing_sources"], errors="ignore")
            )
            dim_df = pd.concat([dim_df, extra], ignore_index=True)

        dim_df = dim_df.drop(
            columns=["total_linked_records", "linked_sources_count", "contributing_sources"],
            errors="ignore",
        )
        dim_df = dim_df.merge(bri_grp, on="master_person_id", how="inner")
        dim_df.to_csv("output/_sev_dim.csv", index=False)
        _gdim = "output/_sev_dim.csv"

        if os.path.exists(ENC):
            enc_df = pd.read_csv(ENC, dtype=str)
            enc_df["master_person_id"] = (
                enc_df["unique_record_id"].map(sv_map).fillna(enc_df["master_person_id"])
            )
            enc_df.to_csv("output/_sev_enc.csv", index=False)
            _genc = "output/_sev_enc.csv"

        print(f"[INFO] severed_links.csv applied — {len(sv_df)} split(s) reflected in output")

duckdb.sql(f"""
    COPY (
        SELECT
            m.master_person_id,
            m.canonical_first_name,
            m.canonical_last_name,
            m.canonical_dob,
            m.contributing_sources,
            m.total_linked_records,
            m.linked_sources_count,
            e.encounter_id,
            e.source_system,
            e.encounter_date,
            e.service_category,
            e.location_info
        FROM '{_gdim}' m
        JOIN '{_genc}' e USING (master_person_id)
        ORDER BY m.canonical_last_name, m.canonical_first_name, e.encounter_date
    ) TO '{OUT}' (HEADER, DELIMITER ',')
""")

row_count = duckdb.sql(f"SELECT COUNT(*) FROM '{OUT}'").fetchone()[0]
print(f"[OK] {OUT} — {row_count} encounter rows across all verified persons")

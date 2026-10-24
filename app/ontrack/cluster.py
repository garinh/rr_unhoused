"""
Stage 4: Identity Resolution & Graph Clustering
Loads Stage 2 (clean demographics) and Stage 3 (match pairs), builds a
NetworkX graph, finds connected components, and assigns each record a
deterministic UUID v5 Master Person ID (MPI).
"""

import os
import uuid
import networkx as nx
import pandas as pd

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")

# Deterministic namespace — fixed for this project so MPIs are reproducible
_MPI_NAMESPACE = uuid.UUID("d5a0e1f3-4c2b-4a8e-9b7d-1f2a3c4e5b6d")


def load_inputs() -> tuple[pd.DataFrame, pd.DataFrame]:
    demo_path  = os.path.join(OUTPUT_DIR, "stage2_clean_demographics.csv")
    pairs_path = os.path.join(OUTPUT_DIR, "stage3_match_pairs.csv")

    for p in (demo_path, pairs_path):
        assert os.path.exists(p), (
            f"[AGENTIC CHECK FAILED] Required input not found: {p}. "
            "Run clean.py and match.py first."
        )

    df_demo  = pd.read_csv(demo_path,  dtype=str).fillna("")
    df_pairs = pd.read_csv(pairs_path, dtype=str)
    df_pairs["match_probability"] = df_pairs["match_probability"].astype(float)
    return df_demo, df_pairs


def cluster(df_demo: pd.DataFrame, df_pairs: pd.DataFrame) -> pd.DataFrame:
    """
    Build a graph from matched pairs, find connected components, assign UUID v5
    MPIs, and return a dataframe with one row per record:
      unique_record_id | master_person_id | match_confidence | match_type
    """
    # ── Build graph ─────────────────────────────────────────────────────
    G = nx.Graph()

    # Every record is a node — even those with no matches become singleton clusters
    for rec_id in df_demo["unique_record_id"]:
        G.add_node(rec_id)

    for _, row in df_pairs.iterrows():
        G.add_edge(
            row["unique_record_id_l"],
            row["unique_record_id_r"],
            weight=row["match_probability"],
        )

    # ── Assign MPIs via connected components ────────────────────────────
    record_to_mpi        = {}
    record_to_confidence = {}

    for component in nx.connected_components(G):
        sorted_members = sorted(component)

        # Deterministic seed: sorted member IDs joined, so the same cluster
        # always produces the same UUID regardless of processing order
        seed = "rogue_raise_2026::" + "::".join(sorted_members)
        mpi  = str(uuid.uuid5(_MPI_NAMESPACE, seed))

        # Confidence = mean edge weight within the cluster; singletons → 1.0
        subgraph = G.subgraph(sorted_members)
        weights  = [d["weight"] for _, _, d in subgraph.edges(data=True) if "weight" in d]
        avg_conf = round(sum(weights) / len(weights), 4) if weights else 1.0

        for member in sorted_members:
            record_to_mpi[member]        = mpi
            record_to_confidence[member] = avg_conf

    # ── Build output dataframe ───────────────────────────────────────────
    df_out = df_demo[["unique_record_id", "source_system"]].copy()
    df_out["master_person_id"]  = df_out["unique_record_id"].map(record_to_mpi)
    df_out["match_confidence"]  = df_out["unique_record_id"].map(record_to_confidence)
    df_out["match_type"] = df_out["match_confidence"].apply(
        lambda c: "Direct_Single" if c == 1.0 else "Probabilistic_Splink"
    )

    # ── Agentic Validation ───────────────────────────────────────────────

    # 1. Every record has exactly one MPI — no nulls, no duplicates
    assert df_out["master_person_id"].notna().all(), (
        "[AGENTIC CHECK FAILED] Some records have no master_person_id (null)."
    )
    assert df_out["master_person_id"].ne("").all(), (
        "[AGENTIC CHECK FAILED] Some records have an empty master_person_id."
    )

    # 2. No orphaned records — all input unique_record_ids are covered
    missing = set(df_demo["unique_record_id"]) - set(df_out["unique_record_id"])
    assert not missing, (
        f"[AGENTIC CHECK FAILED] {len(missing)} records missing from cluster output:\n"
        f"{sorted(missing)[:10]}"
    )

    # 3. Record count unchanged
    assert len(df_out) == len(df_demo), (
        f"[AGENTIC CHECK FAILED] Row count changed: {len(df_demo)} in → {len(df_out)} out"
    )

    # 4. Each unique_record_id appears in exactly one cluster
    #    (guaranteed by graph structure, but verify the mapping is 1-to-1)
    assert df_out["unique_record_id"].is_unique, (
        "[AGENTIC CHECK FAILED] Duplicate unique_record_ids in cluster output."
    )

    # Summary stats
    n_clusters       = df_out["master_person_id"].nunique()
    n_singletons     = (df_out["match_type"] == "Direct_Single").sum()
    n_probabilistic  = (df_out["match_type"] == "Probabilistic_Splink").sum()
    cluster_sizes    = df_out.groupby("master_person_id").size()

    print("[AGENTIC CHECK PASSED] All clustering validations passed.")
    print(f"  Total records       : {len(df_out)}")
    print(f"  Unique MPIs (clusters): {n_clusters}")
    print(f"  Singleton records   : {n_singletons}  (matched to no other record)")
    print(f"  Linked records      : {n_probabilistic}  (probabilistically matched)")
    print(f"  Largest cluster     : {cluster_sizes.max()} records")
    print(f"  Avg cluster size    : {cluster_sizes.mean():.2f} records")

    return df_out


if __name__ == "__main__":
    df_demo, df_pairs = load_inputs()
    df_clustered = cluster(df_demo, df_pairs)

    out_path = os.path.join(OUTPUT_DIR, "stage4_clusters.csv")
    df_clustered.to_csv(out_path, index=False)
    print(f"\n[OUTPUT] {out_path}  ({len(df_clustered)} rows)")

    print("\nCluster size distribution:")
    size_dist = (
        df_clustered.groupby("master_person_id").size()
        .value_counts().sort_index()
        .rename_axis("cluster_size").reset_index(name="num_clusters")
    )
    print(size_dist.to_string(index=False))

    print("\nSample multi-record clusters:")
    sizes = df_clustered.groupby("master_person_id").size()
    multi_mpis = sizes[sizes > 1].index[:5]
    sample = df_clustered[df_clustered["master_person_id"].isin(multi_mpis)]
    print(
        sample[["master_person_id", "unique_record_id", "match_confidence", "match_type"]]
        .sort_values(["master_person_id", "unique_record_id"])
        .to_string(index=False)
    )

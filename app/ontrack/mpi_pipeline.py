"""
mpi_pipeline.py — Rogue Raise MPI Pipeline Orchestrator
End-to-end runner that executes all 5 validated stage modules in sequence,
saves intermediate outputs after each stage, and verifies final FK integrity.

Usage:
    python mpi_pipeline.py
    python mpi_pipeline.py --from-stage 3   # resume from Stage 3 onward
"""

import argparse
import os
import sys
import time
import traceback

import pandas as pd

# ── Output directory (shared by all stages) ─────────────────────────────────
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)


# ── Paths written between stages ────────────────────────────────────────────
_STAGE_PATHS = {
    "stage1_encounters": os.path.join(OUTPUT_DIR, "stage1_encounters_raw.csv"),
    "stage2_demo":       os.path.join(OUTPUT_DIR, "stage2_clean_demographics.csv"),
    "stage3_pairs":      os.path.join(OUTPUT_DIR, "stage3_match_pairs.csv"),
    "stage4_clusters":   os.path.join(OUTPUT_DIR, "stage4_clusters.csv"),
    "dim":               os.path.join(OUTPUT_DIR, "dim_master_persons.csv"),
    "bridge":            os.path.join(OUTPUT_DIR, "bridge_record_links.csv"),
    "fact":              os.path.join(OUTPUT_DIR, "fact_encounters.csv"),
}


# ── Helpers ──────────────────────────────────────────────────────────────────
def _banner(stage: int, title: str) -> None:
    bar = "=" * 68
    print(f"\n{bar}")
    print(f"  STAGE {stage}: {title}")
    print(bar)


def _ok(label: str, n_rows: int, elapsed: float) -> None:
    print(f"[OK] {label} — {n_rows:,} rows  ({elapsed:.1f}s)")


def _save(df: pd.DataFrame, path: str) -> None:
    df.to_csv(path, index=False)
    print(f"[SAVED] {os.path.relpath(path)}  ({len(df):,} rows)")


def _require_files(*keys: str) -> None:
    """Assert that intermediate stage files exist before a resume."""
    for key in keys:
        p = _STAGE_PATHS[key]
        if not os.path.exists(p):
            sys.exit(
                f"[ERROR] Required intermediate file missing for resume: {p}\n"
                f"        Re-run from an earlier stage."
            )


# ── Stage runners ────────────────────────────────────────────────────────────

def run_stage1() -> tuple[pd.DataFrame, pd.DataFrame]:
    _banner(1, "Ingestion & Schema Alignment")
    from ingest import ingest
    t0 = time.time()
    df_demo, df_encounters = ingest()
    elapsed = time.time() - t0
    _save(df_encounters, _STAGE_PATHS["stage1_encounters"])
    _ok("df_demo", len(df_demo), elapsed)
    _ok("df_encounters", len(df_encounters), elapsed)
    return df_demo, df_encounters


def run_stage2(df_demo: pd.DataFrame) -> pd.DataFrame:
    _banner(2, "Standardization & Cleaning")
    from clean import clean
    t0 = time.time()
    df_clean = clean(df_demo)
    elapsed = time.time() - t0
    _save(df_clean, _STAGE_PATHS["stage2_demo"])
    _ok("df_clean", len(df_clean), elapsed)
    return df_clean


def run_stage3(df_clean: pd.DataFrame) -> pd.DataFrame:
    _banner(3, "Probabilistic Matching (Splink / DuckDB)")
    from match import match
    t0 = time.time()
    df_matches = match(df_clean)
    elapsed = time.time() - t0
    _save(df_matches, _STAGE_PATHS["stage3_pairs"])
    _ok("df_matches", len(df_matches), elapsed)
    return df_matches


def run_stage4(df_clean: pd.DataFrame, df_matches: pd.DataFrame) -> pd.DataFrame:
    _banner(4, "Identity Resolution & Graph Clustering")
    from cluster import cluster
    t0 = time.time()
    df_clustered = cluster(df_clean, df_matches)
    elapsed = time.time() - t0
    _save(df_clustered, _STAGE_PATHS["stage4_clusters"])
    _ok("df_clustered", len(df_clustered), elapsed)
    return df_clustered


def run_stage5() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    _banner(5, "Multi-Table CSV Suite Export")
    from export import export
    t0 = time.time()
    dim, bridge, fact = export()
    elapsed = time.time() - t0
    _ok("dim_master_persons", len(dim), elapsed)
    _ok("bridge_record_links", len(bridge), elapsed)
    _ok("fact_encounters", len(fact), elapsed)
    return dim, bridge, fact


# ── Final summary ─────────────────────────────────────────────────────────────

def _print_summary(dim: pd.DataFrame, bridge: pd.DataFrame, fact: pd.DataFrame) -> None:
    bar = "=" * 68
    print(f"\n{bar}")
    print("  PIPELINE COMPLETE — FINAL SUMMARY")
    print(bar)

    n_persons    = len(dim)
    n_multi      = (dim["linked_sources_count"].astype(int) > 1).sum()
    n_singletons = n_persons - n_multi
    n_encounters = len(fact)
    mapped_pct   = fact["master_person_id"].notna().mean() * 100

    print(f"\n  Deduplicated Persons (MPIs)    : {n_persons:>6,}")
    print(f"    +- Multi-source linked        : {n_multi:>6,}")
    print(f"    +- Singletons (no match)      : {n_singletons:>6,}")
    print(f"\n  Raw Records (bridge)           : {len(bridge):>6,}")
    print(f"  Service Encounters (fact)      : {n_encounters:>6,}")
    print(f"    +- Mapped to an MPI          : {mapped_pct:.1f}%")

    print(f"\n  Source breakdown:")
    for src, grp in bridge.groupby("source_system"):
        n   = len(grp)
        pct = n / len(bridge) * 100
        print(f"    {src:<28}: {n:>4} records ({pct:.1f}%)")

    print(f"\n  Output files:")
    for label, key in [
        ("dim_master_persons.csv ", "dim"),
        ("bridge_record_links.csv", "bridge"),
        ("fact_encounters.csv     ", "fact"),
    ]:
        p = _STAGE_PATHS[key]
        size_kb = os.path.getsize(p) / 1024
        print(f"    output/{label}  {size_kb:>7.1f} KB")

    print(f"\n{bar}\n")


# ── Argument parsing & entry point ────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Rogue Raise MPI Pipeline Orchestrator")
    p.add_argument(
        "--from-stage",
        type=int,
        choices=[1, 2, 3, 4, 5],
        default=1,
        metavar="N",
        help="Resume pipeline from stage N (1–5). Intermediate files from earlier "
             "stages must already exist in output/.",
    )
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    start_stage = args.from_stage

    wall_start = time.time()
    print(f"\nRogue Raise MPI Pipeline  —  starting from Stage {start_stage}")

    # ── Stage 1 ──────────────────────────────────────────────────────────────
    if start_stage <= 1:
        df_demo, df_encounters = run_stage1()
    else:
        _require_files("stage2_demo", "stage1_encounters")
        print("[SKIP] Stage 1 — loading from disk")
        df_demo      = pd.read_csv(_STAGE_PATHS["stage2_demo"],       dtype=str).fillna("")
        df_encounters = pd.read_csv(_STAGE_PATHS["stage1_encounters"], dtype=str).fillna("")

    # ── Stage 2 ──────────────────────────────────────────────────────────────
    if start_stage <= 2:
        df_clean = run_stage2(df_demo)
    else:
        _require_files("stage2_demo")
        print("[SKIP] Stage 2 — loading from disk")
        df_clean = pd.read_csv(_STAGE_PATHS["stage2_demo"], dtype=str).fillna("")

    # ── Stage 3 ──────────────────────────────────────────────────────────────
    if start_stage <= 3:
        df_matches = run_stage3(df_clean)
    else:
        _require_files("stage3_pairs")
        print("[SKIP] Stage 3 — loading from disk")
        df_matches = pd.read_csv(_STAGE_PATHS["stage3_pairs"], dtype=str)
        df_matches["match_probability"] = df_matches["match_probability"].astype(float)

    # ── Stage 4 ──────────────────────────────────────────────────────────────
    if start_stage <= 4:
        df_clustered = run_stage4(df_clean, df_matches)
    else:
        _require_files("stage4_clusters")
        print("[SKIP] Stage 4 — loading from disk")
        df_clustered = pd.read_csv(_STAGE_PATHS["stage4_clusters"], dtype=str).fillna("")

    # ── Stage 5 ──────────────────────────────────────────────────────────────
    dim, bridge, fact = run_stage5()

    # ── Summary ──────────────────────────────────────────────────────────────
    _print_summary(dim, bridge, fact)
    print(f"Total wall-clock time: {time.time() - wall_start:.1f}s")


if __name__ == "__main__":
    try:
        main()
    except AssertionError as exc:
        print(f"\n{exc}", file=sys.stderr)
        sys.exit(1)
    except Exception:
        traceback.print_exc()
        sys.exit(2)

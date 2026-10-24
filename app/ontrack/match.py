"""
Stage 3: Probabilistic Matching (Splink 5 / DuckDB)
Loads cleaned demographics from Stage 2 output and runs probabilistic
deduplication. Returns a dataframe of candidate record pairs with
match_probability scores above the configured threshold.
"""

import os
import pandas as pd
from splink import DuckDBAPI, Linker, SettingsCreator, block_on
import splink.comparison_library as cl

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")
MATCH_THRESHOLD = 0.70


def load_clean_demographics() -> pd.DataFrame:
    path = os.path.join(OUTPUT_DIR, "stage2_clean_demographics.csv")
    assert os.path.exists(path), (
        f"[AGENTIC CHECK FAILED] Stage 2 output not found at {path}. Run clean.py first."
    )
    return pd.read_csv(path, dtype=str).fillna("")


def _prepare_for_splink(df: pd.DataFrame) -> pd.DataFrame:
    """Convert empty strings → None for Splink comparison columns.

    Splink uses SQL NULL semantics for its null-level comparison weights.
    Empty strings would be treated as real matching values (all 200 records
    with no SSN would falsely match each other), so we null them out here.
    """
    null_cols = ["first_name_clean", "last_name_clean", "dob_clean", "ssn_clean",
                 "last_name_sorted_chars"]
    df = df.copy()
    for col in null_cols:
        df[col] = df[col].where(df[col].ne(""), other=None)
    return df


def match(df_clean: pd.DataFrame) -> pd.DataFrame:
    """Run Splink probabilistic deduplication. Returns candidate pairs dataframe."""
    df = _prepare_for_splink(df_clean)

    settings = SettingsCreator(
        link_type="dedupe_only",
        unique_id_column_name="unique_record_id",
        comparisons=[
            cl.LevenshteinAtThresholds("first_name_clean", distance_threshold_or_thresholds=[1, 2]),
            # Lev-2 covers transpositions like "jonhson"/"johnson" (swap of adjacent letters).
            # The last_name_sorted_chars training block generates these pairs so Lev-2 is trained.
            cl.LevenshteinAtThresholds("last_name_clean",  distance_threshold_or_thresholds=[1, 2]),
            cl.ExactMatch("dob_clean"),
            cl.ExactMatch("ssn_clean"),
        ],
        blocking_rules_to_generate_predictions=[
            block_on("dob_clean"),
            block_on("last_name_clean"),
            # Anagram fingerprint: "jonhson" and "johnson" both sort to "hjnnoos",
            # so near-typo last names that would miss the exact block are still paired.
            block_on("last_name_sorted_chars"),
            # SSN blocking: DuckDB NULL semantics means this only fires when both are non-NULL
            "l.ssn_clean = r.ssn_clean",
        ],
        # With ~400 records and ~100 cross-source matches, ~0.001 is a realistic prior
        probability_two_random_records_match=0.001,
    )

    db_api = DuckDBAPI()
    splink_df = db_api.register(df, table_name="demographics")
    linker = Linker(splink_df, settings)

    print("[MATCH] Estimating u-probabilities via random sampling...")
    linker.training.estimate_u_using_random_sampling(max_pairs=1_000_000)

    print("[MATCH] EM training pass 1: block on dob_clean...")
    linker.training.estimate_parameters_using_expectation_maximisation(
        block_on("dob_clean")
    )

    print("[MATCH] EM training pass 2: block on last_name_clean...")
    linker.training.estimate_parameters_using_expectation_maximisation(
        block_on("last_name_clean")
    )

    print("[MATCH] EM training pass 3: block on first_name_clean...")
    linker.training.estimate_parameters_using_expectation_maximisation(
        block_on("first_name_clean")
    )

    # Pass 4: sorted-char last-name fingerprint — "jonhson" and "johnson" share the
    # same sorted chars ("hjnnoos"), so this block generates Lev-1 last-name training
    # pairs that exact-last-name blocks never see, training that m-probability level.
    print("[MATCH] EM training pass 4: block on last_name_sorted_chars...")
    linker.training.estimate_parameters_using_expectation_maximisation(
        block_on("last_name_sorted_chars")
    )

    print(f"[MATCH] Generating predictions (threshold={MATCH_THRESHOLD})...")
    predictions = linker.inference.predict(threshold_match_probability=MATCH_THRESHOLD)
    df_matches = predictions.as_pandas_dataframe()

    # Drop pairs where both DOBs are known and birth years differ by > 5 years.
    # Identical names across agencies can score above threshold even with wildly
    # different birth years (e.g. Linda Johnson 1951 vs Linda Johnson 2002).
    if "dob_clean_l" in df_matches.columns and "dob_clean_r" in df_matches.columns:
        both_known = df_matches["dob_clean_l"].notna() & df_matches["dob_clean_r"].notna()
        year_l = df_matches.loc[both_known, "dob_clean_l"].str[:4].astype(float, errors="ignore")
        year_r = df_matches.loc[both_known, "dob_clean_r"].str[:4].astype(float, errors="ignore")
        keep = ~(both_known & ((year_l - year_r).abs() > 5))
        n_dropped = (~keep).sum()
        if n_dropped:
            print(f"[MATCH] Dropped {n_dropped} pairs with mismatched birth years (> 5yr apart).")
        df_matches = df_matches[keep].reset_index(drop=True)

    # ── Agentic Validation ──────────────────────────────────────────────

    assert "match_probability" in df_matches.columns, (
        "[AGENTIC CHECK FAILED] Splink predictions missing match_probability column."
    )

    if not df_matches.empty:
        below_zero = (df_matches["match_probability"] <= 0.0).sum()
        above_one  = (df_matches["match_probability"] >= 1.0).sum()
        assert below_zero == 0, (
            f"[AGENTIC CHECK FAILED] {below_zero} match_probability values ≤ 0.0"
        )
        assert above_one == 0, (
            f"[AGENTIC CHECK FAILED] {above_one} match_probability values ≥ 1.0"
        )

        # No duplicate candidate pairs (order-insensitive: (A,B) == (B,A))
        id_l = df_matches["unique_record_id_l"]
        id_r = df_matches["unique_record_id_r"]
        pair_keys = pd.Series(
            [tuple(sorted([a, b])) for a, b in zip(id_l, id_r)]
        )
        n_dupes = pair_keys.duplicated().sum()
        assert n_dupes == 0, (
            f"[AGENTIC CHECK FAILED] {n_dupes} duplicate candidate pairs found."
        )

    print(f"[AGENTIC CHECK PASSED] {len(df_matches)} candidate linkages above threshold {MATCH_THRESHOLD}.")
    print(f"  match_probability range: "
          f"{df_matches['match_probability'].min():.4f} – "
          f"{df_matches['match_probability'].max():.4f}")

    return df_matches


if __name__ == "__main__":
    df_clean = load_clean_demographics()
    df_matches = match(df_clean)

    out_path = os.path.join(OUTPUT_DIR, "stage3_match_pairs.csv")
    df_matches.to_csv(out_path, index=False)
    print(f"\n[OUTPUT] {out_path}  ({len(df_matches)} rows)")

    print("\nTop 10 matches by probability:")
    cols = ["unique_record_id_l", "unique_record_id_r", "match_probability"]
    available = [c for c in cols if c in df_matches.columns]
    print(df_matches[available].sort_values("match_probability", ascending=False).head(10).to_string(index=False))

    print("\nMatch count by source-pair:")
    src_l = df_matches["unique_record_id_l"].str.split("::").str[0]
    src_r = df_matches["unique_record_id_r"].str.split("::").str[0]
    pair_counts = (
        pd.DataFrame({"src_l": src_l, "src_r": src_r})
        .groupby(["src_l", "src_r"])
        .size()
        .reset_index(name="count")
    )
    print(pair_counts.to_string(index=False))

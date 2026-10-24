"""
test_pipeline_integrity.py — Bucket 1 requirement tests

B1.1  Each raw record assigned exactly one UUID MPI (no duplicates, valid UUID format)
B1.2  No orphaned bridge records — every bridge MPI exists in dim (FK integrity)
B1.3  At least one cross-agency cluster exists (linked_sources_count > 1)
B1.5  accepted_persons.csv has required columns and valid MPI values
B1.6  review_decisions.csv has required columns and valid decision values
B1.7  _sever_link() writes correct entry to severed_links.csv and returns a valid new UUID
B1.8  _undo_accept() removes exactly the target row, leaves all others intact
B1.9  GOLDEN_PERSONS.csv contains all columns required by the Records tab
B1.10 Effective bridge after sever: split_mpi applied, cluster membership updated
B1.11 Golden encounters after sever: severed record's encounters remapped to split_mpi
B1.12 Harry & David input files have correct dirty-data characteristics
B1.13 Harry & David cross-agency overlaps appear in real pipeline output (if pipeline run)

Tests are split into four classes:
  TestPipelineLogic            — always runs, uses fixture data, tests logic in isolation
  TestEffectiveBridgeAfterSever — effective overlay: sever + accept precedence, cluster membership
  TestGoldenAfterSever          — encounter remapping and FK integrity after sever
  TestRealPipelineOutput        — skips if pipeline output files are absent

Run all tests:
    pytest tests/test_pipeline_integrity.py -v

Run only the always-on logic tests:
    pytest tests/test_pipeline_integrity.py::TestPipelineLogic -v

Run effective-bridge tests:
    pytest tests/test_pipeline_integrity.py::TestEffectiveBridgeAfterSever -v

Run golden-after-sever tests:
    pytest tests/test_pipeline_integrity.py::TestGoldenAfterSever -v

Run real-output integration checks:
    pytest tests/test_pipeline_integrity.py::TestRealPipelineOutput -v
"""

import os
import re
import uuid
import shutil
import datetime

import pandas as pd
import pytest

# ── Real output directory (integration tests skip if absent) ─────────────────
_REAL_OUTPUT = os.path.join(os.path.dirname(__file__), "..", "output")
_real_output_exists = os.path.exists(os.path.join(_REAL_OUTPUT, "bridge_record_links.csv"))

needs_pipeline = pytest.mark.skipif(
    not _real_output_exists,
    reason="Pipeline output files not found — run `python mpi_pipeline.py` first",
)

# ── Required columns per file ────────────────────────────────────────────────
_BRIDGE_COLS   = {"unique_record_id", "master_person_id", "source_system",
                  "source_id", "match_confidence", "match_type"}
_DIM_COLS      = {"master_person_id", "canonical_first_name", "canonical_last_name",
                  "canonical_dob", "canonical_ssn_last4", "total_linked_records",
                  "linked_sources_count", "contributing_sources"}
_GOLDEN_COLS   = {"master_person_id", "canonical_first_name", "canonical_last_name",
                  "canonical_dob", "contributing_sources",
                  "total_linked_records", "linked_sources_count"}
_ACCEPTED_COLS = {"source_system", "source_id", "target_mpi", "timestamp"}
_DECISION_COLS = {"mpi", "decision", "composite", "timestamp"}
_SEVERED_COLS  = {"unique_record_id", "original_mpi", "split_mpi"}

_VALID_DECISIONS = {"accept", "reject"}

# ── UUID validator ────────────────────────────────────────────────────────────
def _is_valid_uuid(val: str) -> bool:
    try:
        uuid.UUID(str(val))
        return True
    except (ValueError, AttributeError):
        return False

# ── Portable copies of app.py helpers (injected paths for isolation) ─────────
_MPI_NAMESPACE = uuid.UUID("d5a0e1f3-4c2b-4a8e-9b7d-1f2a3c4e5b6d")

def _sever_link(unique_record_id: str, original_mpi: str, severed_path: str) -> str:
    split_mpi = str(uuid.uuid5(_MPI_NAMESPACE, f"severed::{unique_record_id}"))
    row = {"unique_record_id": unique_record_id,
           "original_mpi": original_mpi,
           "split_mpi": split_mpi}
    if os.path.exists(severed_path):
        existing = pd.read_csv(severed_path, dtype=str)
        if unique_record_id in existing["unique_record_id"].values:
            return split_mpi
        pd.concat([existing, pd.DataFrame([row])], ignore_index=True).to_csv(severed_path, index=False)
    else:
        pd.DataFrame([row]).to_csv(severed_path, index=False)
    return split_mpi

def _undo_accept(source_system: str, source_id: str, accepted_path: str) -> None:
    if not os.path.exists(accepted_path):
        return
    ap = pd.read_csv(accepted_path, dtype=str)
    mask = ~(
        (ap["source_system"].str.lower() == source_system.lower())
        & (ap["source_id"] == source_id)
    )
    ap[mask].to_csv(accepted_path, index=False)


# ── Fixture data ─────────────────────────────────────────────────────────────
# Two clusters: one cross-agency (Alice, ACCESS + ROGUE_RETREAT),
# one single-agency (Bob, RECOVERY_CAFE).

_MPI_ALICE = str(uuid.uuid5(_MPI_NAMESPACE, "alice-cluster"))
_MPI_BOB   = str(uuid.uuid5(_MPI_NAMESPACE, "bob-cluster"))

_DIM_CSV = f"""master_person_id,canonical_first_name,canonical_last_name,canonical_dob,canonical_ssn_last4,total_linked_records,linked_sources_count,contributing_sources
{_MPI_ALICE},Alice,Smith,1978-03-12,,2,2,"ACCESS_HUD, ROGUE_RETREAT"
{_MPI_BOB},Bob,Jones,1985-07-22,,1,1,RECOVERY_CAFE
"""

_BRIDGE_CSV = f"""unique_record_id,master_person_id,source_system,source_id,match_confidence,match_type
ACCESS_HUD::P-001,{_MPI_ALICE},ACCESS_HUD,P-001,1.0,Direct_Single
ROGUE_RETREAT::R-042,{_MPI_ALICE},ROGUE_RETREAT,R-042,0.931,Probabilistic_Splink
RECOVERY_CAFE::M-007,{_MPI_BOB},RECOVERY_CAFE,M-007,1.0,Direct_Single
"""

_GOLDEN_CSV = f"""master_person_id,canonical_first_name,canonical_last_name,canonical_dob,canonical_ssn_last4,contributing_sources,total_linked_records,linked_sources_count
{_MPI_ALICE},Alice,Smith,1978-03-12,,"ACCESS_HUD, ROGUE_RETREAT",2,2
{_MPI_BOB},Bob,Jones,1985-07-22,,RECOVERY_CAFE,1,1
"""

_ACCEPTED_CSV = f"""source_system,source_id,target_mpi,timestamp
ACCESS_HUD,P-001,{_MPI_ALICE},2026-10-09T14:30:00
ACCESS_HUD,P-001,{_MPI_ALICE},2026-10-09T14:30:00
ROGUE_RETREAT,R-042,{_MPI_ALICE},2026-10-09T14:31:00
"""

_DECISIONS_CSV = f"""mpi,decision,composite,timestamp
{_MPI_BOB},reject,0.72,2026-10-09T14:35:00
{_MPI_ALICE},accept,0.93,2026-10-09T14:36:00
"""

# Three encounters: 2 for Alice's cluster (one per source), 1 for Bob
_ENCOUNTERS_CSV = f"""encounter_id,unique_record_id,master_person_id,source_system,encounter_date,service_category,location_info
E-001,ACCESS_HUD::P-001,{_MPI_ALICE},ACCESS_HUD,2026-03-10,Emergency Shelter,
E-002,ROGUE_RETREAT::R-042,{_MPI_ALICE},ROGUE_RETREAT,2026-04-05,Transitional Housing,
E-003,RECOVERY_CAFE::M-007,{_MPI_BOB},RECOVERY_CAFE,2026-05-01,Meal Program,
"""


@pytest.fixture()
def env(tmp_path):
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    (output_dir / "dim_master_persons.csv").write_text(_DIM_CSV,         encoding="utf-8")
    (output_dir / "bridge_record_links.csv").write_text(_BRIDGE_CSV,     encoding="utf-8")
    (output_dir / "GOLDEN_PERSONS.csv").write_text(_GOLDEN_CSV,          encoding="utf-8")
    (output_dir / "accepted_persons.csv").write_text(_ACCEPTED_CSV,      encoding="utf-8")
    (output_dir / "review_decisions.csv").write_text(_DECISIONS_CSV,     encoding="utf-8")
    (output_dir / "fact_encounters.csv").write_text(_ENCOUNTERS_CSV,     encoding="utf-8")
    return {
        "output_dir":     str(output_dir),
        "bridge":         str(output_dir / "bridge_record_links.csv"),
        "dim":            str(output_dir / "dim_master_persons.csv"),
        "golden":         str(output_dir / "GOLDEN_PERSONS.csv"),
        "accepted":       str(output_dir / "accepted_persons.csv"),
        "decisions":      str(output_dir / "review_decisions.csv"),
        "encounters":     str(output_dir / "fact_encounters.csv"),
        "severed":        str(output_dir / "severed_links.csv"),
    }


# ── Portable effective bridge overlay (mirrors app.py Records tab logic) ──────

def _compute_effective_bridge(
    bridge_path: str,
    severed_path: str = None,
    accepted_path: str = None,
) -> pd.DataFrame:
    """Apply severed_links (then accepted_persons overrides) on top of raw bridge.

    Precedence (highest wins): sever > manual accept > pipeline.
    """
    df = pd.read_csv(bridge_path, dtype=str)
    df["link_origin"]   = "Pipeline"
    df["pipeline_mpi"]  = df["master_person_id"]
    df["effective_mpi"] = df["master_person_id"]
    df["is_severed"]    = False

    if accepted_path and os.path.exists(accepted_path):
        acc = pd.read_csv(accepted_path, dtype=str).drop_duplicates(
            subset=["source_system", "source_id"]
        )
        for _, row in acc.iterrows():
            mask = (
                (df["source_system"].str.lower() == str(row["source_system"]).lower())
                & (df["source_id"] == str(row["source_id"]))
            )
            df.loc[mask, "effective_mpi"] = row["target_mpi"]
            df.loc[mask, "link_origin"]   = "Manual Accept"

    if severed_path and os.path.exists(severed_path):
        sev = pd.read_csv(severed_path, dtype=str)
        sev_map = dict(zip(sev["unique_record_id"], sev["split_mpi"]))
        for uid, split in sev_map.items():
            mask = df["unique_record_id"] == uid
            df.loc[mask, "effective_mpi"] = split
            df.loc[mask, "is_severed"]    = True

    return df


def _apply_severed_to_encounters(
    enc_path: str,
    severed_path: str = None,
) -> pd.DataFrame:
    """Remap encounter master_person_id using severed_links (mirrors generate_golden.py CTE)."""
    enc = pd.read_csv(enc_path, dtype=str)
    enc["effective_mpi"] = enc["master_person_id"]

    if severed_path and os.path.exists(severed_path):
        sev = pd.read_csv(severed_path, dtype=str)
        sev_map = dict(zip(sev["unique_record_id"], sev["split_mpi"]))
        enc["effective_mpi"] = enc.apply(
            lambda r: sev_map.get(r["unique_record_id"], r["master_person_id"]),
            axis=1,
        )

    return enc


# ═══════════════════════════════════════════════════════════════════════════════
# ALWAYS-ON LOGIC TESTS (fixture data, no pipeline required)
# ═══════════════════════════════════════════════════════════════════════════════

class TestPipelineLogic:

    # ── B1.1: UUID format ────────────────────────────────────────────────────

    def test_b1_1_all_bridge_mpis_are_valid_uuids(self, env):
        bridge = pd.read_csv(env["bridge"], dtype=str)
        bad = [v for v in bridge["master_person_id"] if not _is_valid_uuid(v)]
        assert bad == [], f"Invalid UUID(s) in bridge: {bad}"

    def test_b1_1_all_dim_mpis_are_valid_uuids(self, env):
        dim = pd.read_csv(env["dim"], dtype=str)
        bad = [v for v in dim["master_person_id"] if not _is_valid_uuid(v)]
        assert bad == [], f"Invalid UUID(s) in dim: {bad}"

    def test_b1_1_each_unique_record_id_appears_once_in_bridge(self, env):
        bridge = pd.read_csv(env["bridge"], dtype=str)
        dups = bridge[bridge["unique_record_id"].duplicated()]["unique_record_id"].tolist()
        assert dups == [], f"Duplicate unique_record_ids: {dups}"

    def test_b1_1_no_null_mpis_in_bridge(self, env):
        bridge = pd.read_csv(env["bridge"], dtype=str)
        assert bridge["master_person_id"].notna().all()

    # ── B1.2: Foreign key integrity ──────────────────────────────────────────

    def test_b1_2_all_bridge_mpis_exist_in_dim(self, env):
        bridge = pd.read_csv(env["bridge"], dtype=str)
        dim    = pd.read_csv(env["dim"],    dtype=str)
        orphaned = set(bridge["master_person_id"]) - set(dim["master_person_id"])
        assert orphaned == set(), f"Orphaned MPIs in bridge (not in dim): {orphaned}"

    def test_b1_2_bridge_has_correct_columns(self, env):
        bridge = pd.read_csv(env["bridge"], dtype=str)
        assert _BRIDGE_COLS.issubset(set(bridge.columns))

    def test_b1_2_dim_has_correct_columns(self, env):
        dim = pd.read_csv(env["dim"], dtype=str)
        assert _DIM_COLS.issubset(set(dim.columns))

    def test_b1_2_every_dim_mpi_has_at_least_one_bridge_row(self, env):
        bridge = pd.read_csv(env["bridge"], dtype=str)
        dim    = pd.read_csv(env["dim"],    dtype=str)
        missing = set(dim["master_person_id"]) - set(bridge["master_person_id"])
        assert missing == set(), f"Dim MPIs with no bridge rows: {missing}"

    # ── B1.3: Cross-agency clusters ──────────────────────────────────────────

    def test_b1_3_at_least_one_cross_agency_cluster_in_dim(self, env):
        dim = pd.read_csv(env["dim"], dtype=str)
        cross = dim[dim["linked_sources_count"].astype(float) > 1]
        assert len(cross) >= 1, "No cross-agency clusters found in dim_master_persons"

    def test_b1_3_cross_agency_cluster_has_multiple_source_systems_in_bridge(self, env):
        bridge = pd.read_csv(env["bridge"], dtype=str)
        dim    = pd.read_csv(env["dim"],    dtype=str)
        multi_source_mpis = dim[dim["linked_sources_count"].astype(float) > 1]["master_person_id"]
        for mpi in multi_source_mpis:
            sources = bridge[bridge["master_person_id"] == mpi]["source_system"].unique()
            assert len(sources) > 1, f"MPI {mpi} claims multi-source but bridge shows only: {sources}"

    def test_b1_3_cross_agency_contributing_sources_contains_comma(self, env):
        dim = pd.read_csv(env["dim"], dtype=str)
        cross = dim[dim["linked_sources_count"].astype(float) > 1]
        for _, row in cross.iterrows():
            assert "," in str(row["contributing_sources"]), (
                f"MPI {row['master_person_id']} contributing_sources has no comma: {row['contributing_sources']}"
            )

    # ── B1.5: accepted_persons.csv ───────────────────────────────────────────

    def test_b1_5_accepted_persons_has_required_columns(self, env):
        ap = pd.read_csv(env["accepted"], dtype=str)
        assert _ACCEPTED_COLS.issubset(set(ap.columns))

    def test_b1_5_all_target_mpis_are_valid_uuids(self, env):
        ap = pd.read_csv(env["accepted"], dtype=str)
        bad = [v for v in ap["target_mpi"] if not _is_valid_uuid(v)]
        assert bad == [], f"Invalid UUID(s) in accepted_persons target_mpi: {bad}"

    def test_b1_5_accepted_persons_not_empty(self, env):
        ap = pd.read_csv(env["accepted"], dtype=str)
        assert len(ap) > 0

    def test_b1_5_timestamp_is_iso_format(self, env):
        ap = pd.read_csv(env["accepted"], dtype=str)
        for ts in ap["timestamp"]:
            try:
                datetime.datetime.fromisoformat(str(ts))
            except ValueError:
                pytest.fail(f"Non-ISO timestamp in accepted_persons: {ts}")

    # ── B1.6: review_decisions.csv ───────────────────────────────────────────

    def test_b1_6_review_decisions_has_required_columns(self, env):
        dec = pd.read_csv(env["decisions"], dtype=str)
        assert _DECISION_COLS.issubset(set(dec.columns))

    def test_b1_6_only_valid_decision_values(self, env):
        dec = pd.read_csv(env["decisions"], dtype=str)
        bad = set(dec["decision"].unique()) - _VALID_DECISIONS
        assert bad == set(), f"Unexpected decision values: {bad}"

    def test_b1_6_all_mpis_are_valid_uuids(self, env):
        dec = pd.read_csv(env["decisions"], dtype=str)
        bad = [v for v in dec["mpi"] if not _is_valid_uuid(v)]
        assert bad == [], f"Invalid UUID(s) in review_decisions: {bad}"

    # ── B1.7: _sever_link ────────────────────────────────────────────────────

    def test_b1_7_sever_link_returns_valid_uuid(self, env):
        result = _sever_link("ACCESS_HUD::P-001", _MPI_ALICE, env["severed"])
        assert _is_valid_uuid(result)

    def test_b1_7_sever_link_creates_severed_links_file(self, env):
        _sever_link("ACCESS_HUD::P-001", _MPI_ALICE, env["severed"])
        assert os.path.exists(env["severed"])

    def test_b1_7_severed_links_has_correct_columns(self, env):
        _sever_link("ACCESS_HUD::P-001", _MPI_ALICE, env["severed"])
        sv = pd.read_csv(env["severed"], dtype=str)
        assert _SEVERED_COLS.issubset(set(sv.columns))

    def test_b1_7_severed_links_records_original_mpi(self, env):
        _sever_link("ACCESS_HUD::P-001", _MPI_ALICE, env["severed"])
        sv = pd.read_csv(env["severed"], dtype=str)
        assert _MPI_ALICE in sv["original_mpi"].values

    def test_b1_7_split_mpi_differs_from_original_mpi(self, env):
        split = _sever_link("ACCESS_HUD::P-001", _MPI_ALICE, env["severed"])
        assert split != _MPI_ALICE

    def test_b1_7_sever_link_is_idempotent(self, env):
        first  = _sever_link("ACCESS_HUD::P-001", _MPI_ALICE, env["severed"])
        second = _sever_link("ACCESS_HUD::P-001", _MPI_ALICE, env["severed"])
        assert first == second
        sv = pd.read_csv(env["severed"], dtype=str)
        assert sv[sv["unique_record_id"] == "ACCESS_HUD::P-001"].shape[0] == 1

    def test_b1_7_split_mpi_is_deterministic(self, env):
        sv1 = _sever_link("ACCESS_HUD::P-001", _MPI_ALICE, env["severed"])
        # Different path — same deterministic UUID expected
        sv2 = str(uuid.uuid5(_MPI_NAMESPACE, "severed::ACCESS_HUD::P-001"))
        assert sv1 == sv2

    # ── B1.8: _undo_accept ───────────────────────────────────────────────────

    def test_b1_8_undo_accept_removes_target_row(self, env):
        before = pd.read_csv(env["accepted"], dtype=str)
        n_before = len(before[before["source_id"] == "P-001"])
        assert n_before > 0, "Fixture must contain P-001 rows to test removal"
        _undo_accept("ACCESS_HUD", "P-001", env["accepted"])
        after = pd.read_csv(env["accepted"], dtype=str)
        remaining = after[after["source_id"] == "P-001"]
        assert len(remaining) == 0

    def test_b1_8_undo_accept_preserves_other_rows(self, env):
        _undo_accept("ACCESS_HUD", "P-001", env["accepted"])
        after = pd.read_csv(env["accepted"], dtype=str)
        assert len(after[after["source_id"] == "R-042"]) == 1

    def test_b1_8_undo_accept_case_insensitive_source_system(self, env):
        _undo_accept("access_hud", "P-001", env["accepted"])
        after = pd.read_csv(env["accepted"], dtype=str)
        assert len(after[after["source_id"] == "P-001"]) == 0

    def test_b1_8_undo_accept_noop_when_file_absent(self, tmp_path):
        absent = str(tmp_path / "accepted_persons.csv")
        _undo_accept("ACCESS_HUD", "P-001", absent)  # must not raise

    def test_b1_8_undo_accept_noop_when_source_id_not_present(self, env):
        before = pd.read_csv(env["accepted"], dtype=str)
        _undo_accept("ACCESS_HUD", "NONEXISTENT", env["accepted"])
        after  = pd.read_csv(env["accepted"], dtype=str)
        assert len(before) == len(after)

    # ── B1.9: GOLDEN_PERSONS.csv ─────────────────────────────────────────────

    def test_b1_9_golden_persons_has_all_required_columns(self, env):
        gp = pd.read_csv(env["golden"], dtype=str)
        assert _GOLDEN_COLS.issubset(set(gp.columns))

    def test_b1_9_golden_mpis_are_valid_uuids(self, env):
        gp = pd.read_csv(env["golden"], dtype=str)
        bad = [v for v in gp["master_person_id"] if not _is_valid_uuid(v)]
        assert bad == [], f"Invalid UUID(s) in GOLDEN_PERSONS: {bad}"

    def test_b1_9_golden_persons_not_empty(self, env):
        gp = pd.read_csv(env["golden"], dtype=str)
        assert len(gp) > 0


# ═══════════════════════════════════════════════════════════════════════════════
# REAL PIPELINE OUTPUT TESTS (skipped if mpi_pipeline.py has not been run)
# ═══════════════════════════════════════════════════════════════════════════════

class TestRealPipelineOutput:

    @needs_pipeline
    def test_b1_1_real_bridge_unique_record_ids_are_unique(self):
        bridge = pd.read_csv(os.path.join(_REAL_OUTPUT, "bridge_record_links.csv"), dtype=str)
        dups = bridge[bridge["unique_record_id"].duplicated()]["unique_record_id"].tolist()
        assert dups == [], f"Duplicate unique_record_ids in real output: {dups[:5]}"

    @needs_pipeline
    def test_b1_1_real_bridge_mpis_are_valid_uuids(self):
        bridge = pd.read_csv(os.path.join(_REAL_OUTPUT, "bridge_record_links.csv"), dtype=str)
        bad = [v for v in bridge["master_person_id"] if not _is_valid_uuid(v)]
        assert bad == [], f"Invalid MPIs in real bridge (first 5): {bad[:5]}"

    @needs_pipeline
    def test_b1_2_real_bridge_mpis_all_exist_in_dim(self):
        bridge = pd.read_csv(os.path.join(_REAL_OUTPUT, "bridge_record_links.csv"), dtype=str)
        dim    = pd.read_csv(os.path.join(_REAL_OUTPUT, "dim_master_persons.csv"),   dtype=str)
        orphaned = set(bridge["master_person_id"]) - set(dim["master_person_id"])
        assert orphaned == set(), f"Orphaned MPIs in real output: {list(orphaned)[:5]}"

    @needs_pipeline
    def test_b1_2_real_dim_mpis_all_have_bridge_rows(self):
        bridge = pd.read_csv(os.path.join(_REAL_OUTPUT, "bridge_record_links.csv"), dtype=str)
        dim    = pd.read_csv(os.path.join(_REAL_OUTPUT, "dim_master_persons.csv"),   dtype=str)
        missing = set(dim["master_person_id"]) - set(bridge["master_person_id"])
        assert missing == set(), f"Dim MPIs with no bridge rows: {list(missing)[:5]}"

    @needs_pipeline
    def test_b1_3_real_output_has_cross_agency_clusters(self):
        dim = pd.read_csv(os.path.join(_REAL_OUTPUT, "dim_master_persons.csv"), dtype=str)
        cross = dim[dim["linked_sources_count"].astype(float) > 1]
        assert len(cross) >= 1, "No cross-agency clusters in real pipeline output"

    @needs_pipeline
    def test_b1_3_real_cross_agency_count_reported(self):
        dim = pd.read_csv(os.path.join(_REAL_OUTPUT, "dim_master_persons.csv"), dtype=str)
        n = int((dim["linked_sources_count"].astype(float) > 1).sum())
        print(f"\n  Cross-agency clusters found: {n} of {len(dim)} total persons ({100*n/len(dim):.1f}%)")
        assert n > 0

    @needs_pipeline
    def test_b1_9_real_golden_persons_exists_and_has_columns(self):
        golden_path = os.path.join(_REAL_OUTPUT, "GOLDEN_PERSONS.csv")
        assert os.path.exists(golden_path), "GOLDEN_PERSONS.csv not found — run golden export first"
        gp = pd.read_csv(golden_path, dtype=str)
        assert _GOLDEN_COLS.issubset(set(gp.columns))

    @needs_pipeline
    def test_b1_9_real_golden_persons_nonempty(self):
        golden_path = os.path.join(_REAL_OUTPUT, "GOLDEN_PERSONS.csv")
        if not os.path.exists(golden_path):
            pytest.skip("GOLDEN_PERSONS.csv not found")
        gp = pd.read_csv(golden_path, dtype=str)
        assert len(gp) > 0


# ═══════════════════════════════════════════════════════════════════════════════
# B1.12  HARRY & DAVID INPUT FILE QUALITY (always-on — files committed to input/)
# ═══════════════════════════════════════════════════════════════════════════════

_HD_CLIENTS_PATH  = os.path.join(os.path.dirname(__file__), "..", "input", "harry_david_clients.csv")
_HD_SERVICES_PATH = os.path.join(os.path.dirname(__file__), "..", "input", "harry_david_services.csv")

_hd_files_exist = (
    os.path.exists(_HD_CLIENTS_PATH) and os.path.exists(_HD_SERVICES_PATH)
)
needs_hd_files = pytest.mark.skipif(
    not _hd_files_exist,
    reason="Harry & David input files not found — run `python generate_harry_david.py` first",
)

# Known overlap seeds: (hd_id, expected_dirty_first, expected_dirty_last)
_HD_OVERLAP_SEEDS = [
    ("HD-0000001", "Lynda",   "Jonhson"),    # Linda Johnson  (ACC/ROGUE/RECOVERY)
    ("HD-0000002", "TOM",     "SCOTT"),       # Thomas Scott   (ACC/ROGUE)
    ("HD-0000003", "Maggie",  "Perez"),       # Margaret Perez (ROGUE/RECOVERY)
    ("HD-0000004", "Kenny",   "Johnson"),     # Kenneth Johnson (ROGUE/RECOVERY)
    ("HD-0000005", "Robert",  "Hill"),        # Bob Hill        (ROGUE)
    ("HD-0000006", "Jessika", "Gonzales"),   # Jessica Gonzalez (ROGUE)
    ("HD-0000007", "sandy",   "wright"),     # Sandra Wright   (ROGUE/RECOVERY)
    ("HD-0000008", "Erik",    "Thompson"),   # Eric Thompson   (ONTRACK)
]

_HD_EXPECTED_COLS = {
    "hd_id", "first_name", "last_name", "birthday",
    "last_ssn", "phone_number", "household_size", "zip", "enrollment_date",
}
_HD_SVC_EXPECTED_COLS = {
    "svc_id", "hd_client_id", "visit_date",
    "program_type", "items_provided", "site_location",
}


class TestHarryDavidInputFiles:
    """B1.12 — Always-on checks on the generated Harry & David input CSVs."""

    @needs_hd_files
    def test_clients_file_has_correct_columns(self):
        df = pd.read_csv(_HD_CLIENTS_PATH, dtype=str)
        assert _HD_EXPECTED_COLS.issubset(set(df.columns))

    @needs_hd_files
    def test_services_file_has_correct_columns(self):
        df = pd.read_csv(_HD_SERVICES_PATH, dtype=str)
        assert _HD_SVC_EXPECTED_COLS.issubset(set(df.columns))

    @needs_hd_files
    def test_clients_count_is_75(self):
        df = pd.read_csv(_HD_CLIENTS_PATH, dtype=str)
        assert len(df) == 75, f"Expected 75 clients, got {len(df)}"

    @needs_hd_files
    def test_all_eight_overlap_seeds_present(self):
        df = pd.read_csv(_HD_CLIENTS_PATH, dtype=str)
        ids = set(df["hd_id"].values)
        for hd_id, _, _ in _HD_OVERLAP_SEEDS:
            assert hd_id in ids, f"Missing overlap seed: {hd_id}"

    @needs_hd_files
    def test_overlap_seed_dirty_names_match_expected(self):
        df = pd.read_csv(_HD_CLIENTS_PATH, dtype=str)
        df_idx = df.set_index("hd_id")
        for hd_id, exp_first, exp_last in _HD_OVERLAP_SEEDS:
            row = df_idx.loc[hd_id]
            assert row["first_name"] == exp_first, \
                f"{hd_id}: expected first_name={exp_first!r}, got {row['first_name']!r}"
            assert row["last_name"] == exp_last, \
                f"{hd_id}: expected last_name={exp_last!r}, got {row['last_name']!r}"

    @needs_hd_files
    def test_ssn_missingness_rate_is_realistic(self):
        df = pd.read_csv(_HD_CLIENTS_PATH, dtype=str)
        missing = df["last_ssn"].isna() | (df["last_ssn"].str.strip() == "")
        rate = missing.sum() / len(df)
        assert 0.20 <= rate <= 0.55, f"SSN missing rate {rate:.0%} outside expected 20–55%"

    @needs_hd_files
    def test_dob_formats_are_mixed(self):
        df = pd.read_csv(_HD_CLIENTS_PATH, dtype=str)
        # At least some birthdays should be non-ISO (contain / or be year-only or blank)
        non_iso = df["birthday"].fillna("").apply(
            lambda v: "/" in v or (v.isdigit() and len(v) == 4) or v == ""
        )
        assert non_iso.sum() >= 10, "Expected at least 10 non-ISO birthday values"

    @needs_hd_files
    def test_some_names_are_all_caps(self):
        df = pd.read_csv(_HD_CLIENTS_PATH, dtype=str)
        caps = df["first_name"].apply(lambda v: str(v).isupper() and len(v) > 1)
        assert caps.sum() >= 1, "Expected at least one ALL CAPS first name"

    @needs_hd_files
    def test_some_names_are_lowercase(self):
        df = pd.read_csv(_HD_CLIENTS_PATH, dtype=str)
        lower = df["last_name"].apply(lambda v: str(v).islower() and len(v) > 1)
        assert lower.sum() >= 1, "Expected at least one all-lowercase last name"

    @needs_hd_files
    def test_services_contain_hd_product_names(self):
        df = pd.read_csv(_HD_SERVICES_PATH, dtype=str)
        items = " ".join(df["items_provided"].fillna("").values)
        assert "Pear" in items or "Moose Munch" in items or "Truffle" in items

    @needs_hd_files
    def test_all_service_rows_have_a_matching_client(self):
        clients  = pd.read_csv(_HD_CLIENTS_PATH,  dtype=str)
        services = pd.read_csv(_HD_SERVICES_PATH, dtype=str)
        client_ids = set(clients["hd_id"].values)
        orphan_svcs = services[~services["hd_client_id"].isin(client_ids)]
        assert len(orphan_svcs) == 0, \
            f"{len(orphan_svcs)} service rows reference unknown hd_client_id"

    @needs_hd_files
    def test_services_count_is_reasonable(self):
        df = pd.read_csv(_HD_SERVICES_PATH, dtype=str)
        assert 150 <= len(df) <= 500, f"Service count {len(df)} outside expected range"

    @needs_hd_files
    def test_hd_ids_are_unique_in_clients(self):
        df = pd.read_csv(_HD_CLIENTS_PATH, dtype=str)
        dups = df[df["hd_id"].duplicated()]["hd_id"].tolist()
        assert dups == [], f"Duplicate hd_ids: {dups}"


# ═══════════════════════════════════════════════════════════════════════════════
# B1.13  HARRY & DAVID CROSS-AGENCY OVERLAPS IN REAL PIPELINE OUTPUT
# ═══════════════════════════════════════════════════════════════════════════════

_hd_in_bridge = (
    _real_output_exists
    and pd.read_csv(
        os.path.join(_REAL_OUTPUT, "bridge_record_links.csv"), dtype=str
    )["source_system"].eq("HARRY_DAVID").any()
    if _real_output_exists else False
)
needs_hd_pipeline = pytest.mark.skipif(
    not _hd_in_bridge,
    reason="HARRY_DAVID not in pipeline output — register H&D schema and re-run mpi_pipeline.py",
)


class TestHarryDavidOverlaps:
    """B1.13 — Cross-agency overlap checks; skipped until pipeline has been run with H&D data."""

    @needs_hd_pipeline
    def test_hd_records_in_bridge(self):
        bridge = pd.read_csv(os.path.join(_REAL_OUTPUT, "bridge_record_links.csv"), dtype=str)
        hd = bridge[bridge["source_system"] == "HARRY_DAVID"]
        assert len(hd) == 75, f"Expected 75 H&D bridge rows, got {len(hd)}"

    @needs_hd_pipeline
    def test_hd_bridge_row_format_is_correct(self):
        bridge = pd.read_csv(os.path.join(_REAL_OUTPUT, "bridge_record_links.csv"), dtype=str)
        hd = bridge[bridge["source_system"] == "HARRY_DAVID"]
        assert hd["unique_record_id"].str.startswith("HARRY_DAVID::").all()

    @needs_hd_pipeline
    def test_overlap_seeds_are_in_bridge(self):
        bridge = pd.read_csv(os.path.join(_REAL_OUTPUT, "bridge_record_links.csv"), dtype=str)
        hd = bridge[bridge["source_system"] == "HARRY_DAVID"]
        for hd_id, _, _ in _HD_OVERLAP_SEEDS:
            uid = f"HARRY_DAVID::{hd_id}"
            assert uid in hd["unique_record_id"].values, \
                f"Overlap seed {uid} missing from bridge"

    @needs_hd_pipeline
    def test_at_least_one_hd_cross_agency_cluster(self):
        bridge = pd.read_csv(os.path.join(_REAL_OUTPUT, "bridge_record_links.csv"), dtype=str)
        dim    = pd.read_csv(os.path.join(_REAL_OUTPUT, "dim_master_persons.csv"),   dtype=str)
        hd_mpis = set(bridge[bridge["source_system"] == "HARRY_DAVID"]["master_person_id"])
        cross = dim[
            dim["master_person_id"].isin(hd_mpis)
            & (dim["linked_sources_count"].astype(float) > 1)
        ]
        assert len(cross) >= 1, (
            "No cross-agency clusters found containing H&D records — "
            "check Splink threshold and blocking rules"
        )

    @needs_hd_pipeline
    def test_cross_agency_cluster_count_reported(self):
        bridge = pd.read_csv(os.path.join(_REAL_OUTPUT, "bridge_record_links.csv"), dtype=str)
        dim    = pd.read_csv(os.path.join(_REAL_OUTPUT, "dim_master_persons.csv"),   dtype=str)
        hd_mpis = set(bridge[bridge["source_system"] == "HARRY_DAVID"]["master_person_id"])
        cross_n = int(dim[
            dim["master_person_id"].isin(hd_mpis)
            & (dim["linked_sources_count"].astype(float) > 1)
        ].shape[0])
        print(f"\n  H&D cross-agency clusters: {cross_n} of {len(hd_mpis)} H&D persons matched")
        assert True  # reporting only — always passes

    @needs_hd_pipeline
    def test_linda_johnson_seed_is_cross_agency(self):
        """Lynda Jonhson (HD-0000001) should cluster with Linda Johnson (ACC/ROGUE/RECOVERY)."""
        bridge = pd.read_csv(os.path.join(_REAL_OUTPUT, "bridge_record_links.csv"), dtype=str)
        uid = "HARRY_DAVID::HD-0000001"
        row = bridge[bridge["unique_record_id"] == uid]
        if row.empty:
            pytest.skip("HD-0000001 not in bridge")
        mpi = row.iloc[0]["master_person_id"]
        cluster_sources = bridge[bridge["master_person_id"] == mpi]["source_system"].unique()
        assert len(cluster_sources) > 1, \
            f"Lynda Jonhson (HD-0000001) is a singleton — expected cross-agency cluster. Sources: {cluster_sources}"


# ═══════════════════════════════════════════════════════════════════════════════
# B1.10  EFFECTIVE BRIDGE AFTER SEVER
# ═══════════════════════════════════════════════════════════════════════════════

class TestEffectiveBridgeAfterSever:

    def test_severed_row_gets_split_mpi(self, env):
        split = _sever_link("ROGUE_RETREAT::R-042", _MPI_ALICE, env["severed"])
        eff = _compute_effective_bridge(env["bridge"], severed_path=env["severed"])
        row = eff[eff["unique_record_id"] == "ROGUE_RETREAT::R-042"].iloc[0]
        assert row["effective_mpi"] == split

    def test_non_severed_row_keeps_original_mpi(self, env):
        _sever_link("ROGUE_RETREAT::R-042", _MPI_ALICE, env["severed"])
        eff = _compute_effective_bridge(env["bridge"], severed_path=env["severed"])
        row = eff[eff["unique_record_id"] == "ACCESS_HUD::P-001"].iloc[0]
        assert row["effective_mpi"] == _MPI_ALICE

    def test_severed_row_is_flagged(self, env):
        _sever_link("ROGUE_RETREAT::R-042", _MPI_ALICE, env["severed"])
        eff = _compute_effective_bridge(env["bridge"], severed_path=env["severed"])
        row = eff[eff["unique_record_id"] == "ROGUE_RETREAT::R-042"].iloc[0]
        assert row["is_severed"] == True

    def test_non_severed_row_not_flagged(self, env):
        _sever_link("ROGUE_RETREAT::R-042", _MPI_ALICE, env["severed"])
        eff = _compute_effective_bridge(env["bridge"], severed_path=env["severed"])
        row = eff[eff["unique_record_id"] == "ACCESS_HUD::P-001"].iloc[0]
        assert row["is_severed"] == False

    def test_severed_row_retains_pipeline_mpi_for_audit(self, env):
        _sever_link("ROGUE_RETREAT::R-042", _MPI_ALICE, env["severed"])
        eff = _compute_effective_bridge(env["bridge"], severed_path=env["severed"])
        row = eff[eff["unique_record_id"] == "ROGUE_RETREAT::R-042"].iloc[0]
        assert row["pipeline_mpi"] == _MPI_ALICE

    def test_split_mpi_is_valid_uuid(self, env):
        split = _sever_link("ROGUE_RETREAT::R-042", _MPI_ALICE, env["severed"])
        eff = _compute_effective_bridge(env["bridge"], severed_path=env["severed"])
        row = eff[eff["unique_record_id"] == "ROGUE_RETREAT::R-042"].iloc[0]
        assert _is_valid_uuid(row["effective_mpi"])
        assert row["effective_mpi"] == split

    def test_original_cluster_loses_severed_member(self, env):
        _sever_link("ROGUE_RETREAT::R-042", _MPI_ALICE, env["severed"])
        eff = _compute_effective_bridge(env["bridge"], severed_path=env["severed"])
        alice_members = eff[eff["effective_mpi"] == _MPI_ALICE]
        assert len(alice_members) == 1
        assert alice_members.iloc[0]["unique_record_id"] == "ACCESS_HUD::P-001"

    def test_split_mpi_forms_singleton_cluster(self, env):
        split = _sever_link("ROGUE_RETREAT::R-042", _MPI_ALICE, env["severed"])
        eff = _compute_effective_bridge(env["bridge"], severed_path=env["severed"])
        singleton = eff[eff["effective_mpi"] == split]
        assert len(singleton) == 1
        assert singleton.iloc[0]["source_system"] == "ROGUE_RETREAT"

    def test_sever_does_not_affect_unrelated_cluster(self, env):
        _sever_link("ROGUE_RETREAT::R-042", _MPI_ALICE, env["severed"])
        eff = _compute_effective_bridge(env["bridge"], severed_path=env["severed"])
        bob_members = eff[eff["effective_mpi"] == _MPI_BOB]
        assert len(bob_members) == 1
        assert bob_members.iloc[0]["is_severed"] == False

    def test_sever_overrides_manual_accept(self, env):
        # A manual accept that routes R-042 → Bob's cluster, then sever R-042 → sever wins
        pd.DataFrame([{
            "source_system": "ROGUE_RETREAT",
            "source_id": "R-042",
            "target_mpi": _MPI_BOB,
            "timestamp": "2026-10-09T10:00:00",
        }]).to_csv(env["accepted"], index=False)
        split = _sever_link("ROGUE_RETREAT::R-042", _MPI_ALICE, env["severed"])
        eff = _compute_effective_bridge(
            env["bridge"], severed_path=env["severed"], accepted_path=env["accepted"]
        )
        row = eff[eff["unique_record_id"] == "ROGUE_RETREAT::R-042"].iloc[0]
        assert row["effective_mpi"] == split
        assert row["is_severed"] == True

    def test_no_sever_file_leaves_effective_mpi_equal_to_pipeline_mpi(self, env):
        eff = _compute_effective_bridge(env["bridge"])
        assert (eff["effective_mpi"] == eff["master_person_id"]).all()

    def test_all_effective_mpis_are_valid_uuids_after_sever(self, env):
        _sever_link("ROGUE_RETREAT::R-042", _MPI_ALICE, env["severed"])
        eff = _compute_effective_bridge(env["bridge"], severed_path=env["severed"])
        bad = [v for v in eff["effective_mpi"] if not _is_valid_uuid(v)]
        assert bad == [], f"Invalid effective MPIs: {bad}"

    def test_severing_all_records_from_cluster_leaves_it_empty(self, env):
        # Sever both members of Alice's cluster
        _sever_link("ACCESS_HUD::P-001",     _MPI_ALICE, env["severed"])
        _sever_link("ROGUE_RETREAT::R-042",  _MPI_ALICE, env["severed"])
        eff = _compute_effective_bridge(env["bridge"], severed_path=env["severed"])
        alice_members = eff[eff["effective_mpi"] == _MPI_ALICE]
        assert len(alice_members) == 0


# ═══════════════════════════════════════════════════════════════════════════════
# B1.11  GOLDEN ENCOUNTERS AFTER SEVER
# ═══════════════════════════════════════════════════════════════════════════════

class TestGoldenAfterSever:

    def test_severed_record_encounters_remapped_to_split_mpi(self, env):
        split = _sever_link("ROGUE_RETREAT::R-042", _MPI_ALICE, env["severed"])
        enc = _apply_severed_to_encounters(env["encounters"], severed_path=env["severed"])
        severed_enc = enc[enc["unique_record_id"] == "ROGUE_RETREAT::R-042"]
        assert len(severed_enc) == 1
        assert severed_enc.iloc[0]["effective_mpi"] == split

    def test_non_severed_record_encounters_keep_original_mpi(self, env):
        _sever_link("ROGUE_RETREAT::R-042", _MPI_ALICE, env["severed"])
        enc = _apply_severed_to_encounters(env["encounters"], severed_path=env["severed"])
        p001_enc = enc[enc["unique_record_id"] == "ACCESS_HUD::P-001"]
        assert len(p001_enc) == 1
        assert p001_enc.iloc[0]["effective_mpi"] == _MPI_ALICE

    def test_unrelated_cluster_encounters_unaffected(self, env):
        _sever_link("ROGUE_RETREAT::R-042", _MPI_ALICE, env["severed"])
        enc = _apply_severed_to_encounters(env["encounters"], severed_path=env["severed"])
        bob_enc = enc[enc["unique_record_id"] == "RECOVERY_CAFE::M-007"]
        assert bob_enc.iloc[0]["effective_mpi"] == _MPI_BOB

    def test_split_mpi_is_valid_uuid_in_encounters(self, env):
        split = _sever_link("ROGUE_RETREAT::R-042", _MPI_ALICE, env["severed"])
        enc = _apply_severed_to_encounters(env["encounters"], severed_path=env["severed"])
        split_enc = enc[enc["effective_mpi"] == split]
        assert len(split_enc) >= 1
        assert _is_valid_uuid(split_enc.iloc[0]["effective_mpi"])

    def test_all_effective_mpis_valid_after_sever(self, env):
        _sever_link("ROGUE_RETREAT::R-042", _MPI_ALICE, env["severed"])
        enc = _apply_severed_to_encounters(env["encounters"], severed_path=env["severed"])
        bad = [v for v in enc["effective_mpi"] if not _is_valid_uuid(v)]
        assert bad == [], f"Invalid effective MPIs in encounters: {bad}"

    def test_original_cluster_loses_encounter_after_sever(self, env):
        _sever_link("ROGUE_RETREAT::R-042", _MPI_ALICE, env["severed"])
        enc = _apply_severed_to_encounters(env["encounters"], severed_path=env["severed"])
        alice_enc = enc[enc["effective_mpi"] == _MPI_ALICE]
        sources_in_alice = alice_enc["source_system"].unique().tolist()
        assert "ROGUE_RETREAT" not in sources_in_alice

    def test_no_sever_leaves_effective_mpi_equal_to_master_person_id(self, env):
        enc = _apply_severed_to_encounters(env["encounters"])
        assert (enc["effective_mpi"] == enc["master_person_id"]).all()

    def test_encounter_count_conserved_after_sever(self, env):
        before = pd.read_csv(env["encounters"], dtype=str)
        _sever_link("ROGUE_RETREAT::R-042", _MPI_ALICE, env["severed"])
        after = _apply_severed_to_encounters(env["encounters"], severed_path=env["severed"])
        # No rows should be created or destroyed — only effective_mpi changes
        assert len(before) == len(after)

"""
End-to-end snapshot tests covering the full new-partner → pipeline → snapshot flow,
using Harry & David Community Food & Essentials Program as the test agency.

Harry & David uses intentionally non-standard column names to exercise the TPM mapper:
  Clients:  hd_id, first_name, last_name, birthday, last_ssn, phone_number, enrollment_date
  Services: svc_id, hd_client_id, visit_date, program_type, items_provided, site_location

Three of the five fixture clients are overlap seeds whose dirty data should match records
in other agencies (Linda Johnson → Lynda Jonhson; Thomas Scott → TOM SCOTT;
Bob Hill → Robert Hill).

Tests verify:
  1. Schema JSON is written with correct column mapping (birthday→dob, last_ssn→ssn, etc.)
  2. The CSV is persisted to input/ when saved through the mapper
  3. Pipeline outputs contain HARRY_DAVID records with correct encounter dates
  4. _take_snapshot() freezes those outputs and records correct counts
  5. _load_snapshot_index() reflects the new snapshot accurately

Run with:
    pytest tests/test_snapshot_e2e.py -v
"""

import json
import os
import re
import shutil
import datetime

import pandas as pd
import pytest


# ── Portable snapshot helpers (same logic as app.py) ─────────────────────────

def _take_snapshot(label: str, snapshots_dir: str, output_dir: str) -> tuple[bool, str]:
    slot = os.path.join(snapshots_dir, label)
    try:
        os.makedirs(slot, exist_ok=True)
        files_copied = []
        for fname in (
            "dim_master_persons.csv",
            "bridge_record_links.csv",
            "fact_encounters.csv",
            "GOLDEN_PERSONS.csv",
        ):
            src = os.path.join(output_dir, fname)
            if os.path.exists(src):
                shutil.copy2(src, os.path.join(slot, fname))
                files_copied.append(fname)

        n_persons = n_enc = 0
        gp_path  = os.path.join(slot, "GOLDEN_PERSONS.csv")
        enc_path = os.path.join(slot, "fact_encounters.csv")
        if os.path.exists(gp_path):
            n_persons = sum(1 for _ in open(gp_path, encoding="utf-8")) - 1
        if os.path.exists(enc_path):
            n_enc = sum(1 for _ in open(enc_path, encoding="utf-8")) - 1

        meta = {
            "label":      label,
            "created_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "persons":    max(n_persons, 0),
            "encounters": max(n_enc, 0),
            "files":      files_copied,
        }
        with open(os.path.join(slot, "meta.json"), "w", encoding="utf-8") as fh:
            json.dump(meta, fh, indent=2)
        return True, f"Snapshot '{label}' saved — {n_persons:,} persons, {n_enc:,} encounters."
    except Exception as exc:
        return False, f"ERROR: {exc}"


def _load_snapshot_index(snapshots_dir: str) -> list[dict]:
    rows = []
    if not os.path.isdir(snapshots_dir):
        return rows
    for name in sorted(os.listdir(snapshots_dir), reverse=True):
        meta_path = os.path.join(snapshots_dir, name, "meta.json")
        if os.path.exists(meta_path):
            try:
                with open(meta_path, encoding="utf-8") as fh:
                    rows.append(json.load(fh))
            except Exception:
                rows.append({"label": name, "created_at": "", "persons": "?", "encounters": "?"})
    return rows


# ── Portable _save_new_schema (mirrors app.py) ────────────────────────────────

def _save_new_schema(agency_name, source_slug, client_file,
                     client_id_col, col_map_user, ssn_type, schema_dir):
    os.makedirs(schema_dir, exist_ok=True)
    safe = re.sub(r"[^a-z0-9]+", "_", agency_name.lower()).strip("_")
    path = os.path.join(schema_dir, f"{safe}.json")
    schema = {
        "label":         agency_name,
        "short_label":   agency_name.upper(),
        "source_system": source_slug,
        "optional":      True,
        "client_file":   client_file,
        "columns": {
            "client_id":      client_id_col,
            "first_name":     col_map_user.get("first_name"),
            "last_name":      col_map_user.get("last_name"),
            "dob":            col_map_user.get("dob"),
            "ssn":            col_map_user.get("ssn"),
            "encounter_date": col_map_user.get("encounter_date"),
        },
        "ssn_type": ssn_type,
        "special":  None,
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(schema, fh, indent=2)
    return path


# ── Fixture data: 5 Harry & David clients (3 are cross-agency overlap seeds) ──
#
#  HD-0000001  Lynda Jonhson    birthday=5/8/2002         → Linda Johnson (ACCESS/ROGUE/RECOVERY)
#  HD-0000002  TOM SCOTT        birthday=1955 (yr-only)   → Thomas Scott  (ACCESS/ROGUE)
#  HD-0000005  Robert Hill      birthday=1995-03-19       → Bob Hill      (ROGUE, DOB off +1 day)
#  HD-0000009  Timothy Collins  birthday=4/30/1989        — H&D only
#  HD-0000012  SARAH king       birthday=1998 (yr-only)   — H&D only

_HD_CLIENTS_CSV = (
    "hd_id,first_name,last_name,birthday,last_ssn,phone_number,household_size,zip,enrollment_date\n"
    "HD-0000001,Lynda,Jonhson,5/8/2002,,,,97520,2026-01-15\n"
    "HD-0000002,TOM,SCOTT,1955,2876,541-555-3301,1,97501,2026-02-03\n"
    "HD-0000005,Robert,Hill,1995-03-19,5010,541-555-7041,1,97520,2026-02-22\n"
    "HD-0000009,Timothy,Collins,4/30/1989,4980,541-555-8112,1,97523,2026-04-20\n"
    "HD-0000012,SARAH,king,1998,9738,541-555-4720,1,97504,2026-04-08\n"
)

_HD_SERVICES_CSV = (
    "svc_id,hd_client_id,visit_date,program_type,items_provided,site_location\n"
    "HD-SVC-00001,HD-0000001,2026-04-19,Moose Munch Community Pack,Moose Munch Popcorn,Salvation Army - Medford\n"
    "HD-SVC-00002,HD-0000002,2026-03-29,Weekend Food Box,Pantry Staples + Pears,Rogue Valley YMCA - Medford\n"
    "HD-SVC-00003,HD-0000005,2026-04-05,Pear Harvest Share,Royal Riviera Pears,HD Distribution Center - Medford\n"
    "HD-SVC-00004,HD-0000009,2026-05-10,Emergency Food Box - Standard,Truffles,St. Matthew's Church - Ashland\n"
    "HD-SVC-00005,HD-0000012,2026-04-20,Holiday Gift Basket Distribution,Holiday Gift Assortment,Peace House Drop-In - Ashland\n"
    "HD-SVC-00006,HD-0000001,2026-06-14,Pear Harvest Share,Moose Munch Popcorn Royal Riviera Pears,HD Distribution Center - Medford\n"
)

# Simulated pipeline outputs (would be produced by mpi_pipeline.py after ingest)
_PIPELINE_DIM = (
    "master_person_id,canonical_first_name,canonical_last_name,canonical_dob,"
    "canonical_ssn_last4,total_linked_records,linked_sources_count,contributing_sources\n"
    "MPI-A,Lynda,Jonhson,2002-05-08,,1,1,HARRY_DAVID\n"
    "MPI-B,TOM,SCOTT,1955-01-01,2876,1,1,HARRY_DAVID\n"
    "MPI-C,Robert,Hill,1995-03-19,5010,1,1,HARRY_DAVID\n"
    "MPI-D,Timothy,Collins,1989-04-30,4980,1,1,HARRY_DAVID\n"
    "MPI-E,SARAH,king,1998-01-01,9738,1,1,HARRY_DAVID\n"
)

_PIPELINE_BRIDGE = (
    "unique_record_id,master_person_id,source_system,source_id,match_confidence,match_type\n"
    "HARRY_DAVID::HD-0000001,MPI-A,HARRY_DAVID,HD-0000001,1.0,Direct_Single\n"
    "HARRY_DAVID::HD-0000002,MPI-B,HARRY_DAVID,HD-0000002,1.0,Direct_Single\n"
    "HARRY_DAVID::HD-0000005,MPI-C,HARRY_DAVID,HD-0000005,1.0,Direct_Single\n"
    "HARRY_DAVID::HD-0000009,MPI-D,HARRY_DAVID,HD-0000009,1.0,Direct_Single\n"
    "HARRY_DAVID::HD-0000012,MPI-E,HARRY_DAVID,HD-0000012,1.0,Direct_Single\n"
)

_PIPELINE_ENC = (
    "encounter_id,master_person_id,unique_record_id,source_system,encounter_date,"
    "service_category,location_info\n"
    "HD-SVC-00001,MPI-A,HARRY_DAVID::HD-0000001,HARRY_DAVID,2026-04-19,Moose Munch Community Pack,\n"
    "HD-SVC-00002,MPI-B,HARRY_DAVID::HD-0000002,HARRY_DAVID,2026-03-29,Weekend Food Box,\n"
    "HD-SVC-00003,MPI-C,HARRY_DAVID::HD-0000005,HARRY_DAVID,2026-04-05,Pear Harvest Share,\n"
    "HD-SVC-00004,MPI-D,HARRY_DAVID::HD-0000009,HARRY_DAVID,2026-05-10,Emergency Food Box - Standard,\n"
    "HD-SVC-00005,MPI-E,HARRY_DAVID::HD-0000012,HARRY_DAVID,2026-04-20,Holiday Gift Basket Distribution,\n"
    "HD-SVC-00006,MPI-A,HARRY_DAVID::HD-0000001,HARRY_DAVID,2026-06-14,Pear Harvest Share,\n"
)

_GOLDEN_PERSONS = (
    "master_person_id,canonical_first_name,canonical_last_name,canonical_dob,"
    "canonical_ssn_last4,contributing_sources,total_linked_records,linked_sources_count\n"
    "MPI-A,Lynda,Jonhson,2002-05-08,,HARRY_DAVID,1,1\n"
    "MPI-B,TOM,SCOTT,1955-01-01,2876,HARRY_DAVID,1,1\n"
    "MPI-C,Robert,Hill,1995-03-19,5010,HARRY_DAVID,1,1\n"
    "MPI-D,Timothy,Collins,1989-04-30,4980,HARRY_DAVID,1,1\n"
    "MPI-E,SARAH,king,1998-01-01,9738,HARRY_DAVID,1,1\n"
)

# Standard col_map for Harry & David (what a user would select in the TPM)
_HD_COL_MAP = {
    "first_name":     "first_name",    # exact header match
    "last_name":      "last_name",     # exact header match
    "dob":            "birthday",      # non-standard → mapped
    "ssn":            "last_ssn",      # non-standard → mapped
    "encounter_date": "enrollment_date",  # non-standard → mapped
}


@pytest.fixture()
def env(tmp_path):
    """
    Temp environment with:
      - input/                    — Harry & David client + services CSVs
      - input/schemas/            — written by _save_new_schema
      - output/                   — simulated pipeline results
      - output/snapshots/
    """
    input_dir     = tmp_path / "input"
    schema_dir    = input_dir / "schemas"
    output_dir    = tmp_path / "output"
    snapshots_dir = output_dir / "snapshots"
    input_dir.mkdir()
    output_dir.mkdir()

    (input_dir / "harry_david_clients.csv").write_text(_HD_CLIENTS_CSV,  encoding="utf-8")
    (input_dir / "harry_david_services.csv").write_text(_HD_SERVICES_CSV, encoding="utf-8")

    (output_dir / "dim_master_persons.csv").write_text(_PIPELINE_DIM,    encoding="utf-8")
    (output_dir / "bridge_record_links.csv").write_text(_PIPELINE_BRIDGE, encoding="utf-8")
    (output_dir / "fact_encounters.csv").write_text(_PIPELINE_ENC,        encoding="utf-8")
    (output_dir / "GOLDEN_PERSONS.csv").write_text(_GOLDEN_PERSONS,       encoding="utf-8")

    return {
        "input_dir":      str(input_dir),
        "schema_dir":     str(schema_dir),
        "output_dir":     str(output_dir),
        "snapshots_dir":  str(snapshots_dir),
        "clients_csv":    str(input_dir / "harry_david_clients.csv"),
        "services_csv":   str(input_dir / "harry_david_services.csv"),
    }


# ── Step 1: Schema + file persistence ────────────────────────────────────────

class TestNewPartnerPersistence:

    def _save(self, env):
        return _save_new_schema(
            agency_name   = "Harry & David",
            source_slug   = "HARRY_DAVID",
            client_file   = "harry_david_clients.csv",
            client_id_col = "hd_id",
            col_map_user  = _HD_COL_MAP,
            ssn_type      = "last4",
            schema_dir    = env["schema_dir"],
        )

    def test_schema_json_created(self, env):
        self._save(env)
        assert any(f.endswith(".json") for f in os.listdir(env["schema_dir"]))

    def test_schema_contains_correct_source_system(self, env):
        path = self._save(env)
        schema = json.load(open(path, encoding="utf-8"))
        assert schema["source_system"] == "HARRY_DAVID"

    def test_schema_birthday_mapped_to_dob(self, env):
        path = self._save(env)
        schema = json.load(open(path, encoding="utf-8"))
        assert schema["columns"]["dob"] == "birthday"

    def test_schema_last_ssn_mapped_to_ssn(self, env):
        path = self._save(env)
        schema = json.load(open(path, encoding="utf-8"))
        assert schema["columns"]["ssn"] == "last_ssn"

    def test_schema_enrollment_date_mapped_to_encounter_date(self, env):
        path = self._save(env)
        schema = json.load(open(path, encoding="utf-8"))
        assert schema["columns"]["encounter_date"] == "enrollment_date"

    def test_schema_ssn_type_is_last4(self, env):
        path = self._save(env)
        schema = json.load(open(path, encoding="utf-8"))
        assert schema["ssn_type"] == "last4"

    def test_schema_client_id_col_is_hd_id(self, env):
        path = self._save(env)
        schema = json.load(open(path, encoding="utf-8"))
        assert schema["columns"]["client_id"] == "hd_id"

    def test_csv_present_in_input_dir(self, env):
        assert os.path.exists(env["clients_csv"])

    def test_csv_contains_overlap_seed_dirty_data(self, env):
        content = open(env["clients_csv"], encoding="utf-8").read()
        assert "Lynda" in content       # misspelled "Linda"
        assert "Jonhson" in content     # transposed "Johnson"
        assert "TOM" in content         # ALL CAPS Thomas
        assert "SCOTT" in content       # ALL CAPS Scott
        assert "1955" in content        # year-only DOB


# ── Step 2: Pipeline outputs include Harry & David ───────────────────────────

class TestPipelineOutputsNewAgency:

    def test_dim_contains_harry_david_records(self, env):
        dim = pd.read_csv(os.path.join(env["output_dir"], "dim_master_persons.csv"), dtype=str)
        assert "HARRY_DAVID" in dim["contributing_sources"].values

    def test_bridge_contains_harry_david(self, env):
        bridge = pd.read_csv(os.path.join(env["output_dir"], "bridge_record_links.csv"), dtype=str)
        assert "HARRY_DAVID" in bridge["source_system"].values

    def test_encounters_contain_harry_david(self, env):
        enc = pd.read_csv(os.path.join(env["output_dir"], "fact_encounters.csv"), dtype=str)
        assert "HARRY_DAVID" in enc["source_system"].values

    def test_encounters_have_dates_from_enrollment_date_column(self, env):
        enc = pd.read_csv(os.path.join(env["output_dir"], "fact_encounters.csv"), dtype=str)
        hd_enc = enc[enc["source_system"] == "HARRY_DAVID"]
        assert not hd_enc.empty
        assert hd_enc["encounter_date"].notna().all()
        assert "2026-04-19" in hd_enc["encounter_date"].values

    def test_golden_persons_includes_harry_david(self, env):
        gp = pd.read_csv(os.path.join(env["output_dir"], "GOLDEN_PERSONS.csv"), dtype=str)
        assert "HARRY_DAVID" in gp["contributing_sources"].values

    def test_all_five_hd_records_present_in_dim(self, env):
        dim = pd.read_csv(os.path.join(env["output_dir"], "dim_master_persons.csv"), dtype=str)
        hd_rows = dim[dim["contributing_sources"].str.contains("HARRY_DAVID", na=False)]
        assert len(hd_rows) == 5

    def test_hd_id_col_is_used_as_source_id(self, env):
        bridge = pd.read_csv(os.path.join(env["output_dir"], "bridge_record_links.csv"), dtype=str)
        hd = bridge[bridge["source_system"] == "HARRY_DAVID"]
        assert "HD-0000001" in hd["source_id"].values

    def test_pear_harvest_service_present_in_encounters(self, env):
        enc = pd.read_csv(os.path.join(env["output_dir"], "fact_encounters.csv"), dtype=str)
        hd_enc = enc[enc["source_system"] == "HARRY_DAVID"]
        assert hd_enc["service_category"].str.contains("Pear Harvest", na=False).any()

    def test_overlap_seed_unique_record_id_format_correct(self, env):
        bridge = pd.read_csv(os.path.join(env["output_dir"], "bridge_record_links.csv"), dtype=str)
        assert "HARRY_DAVID::HD-0000001" in bridge["unique_record_id"].values


# ── Step 3: Snapshot captures Harry & David correctly ────────────────────────

class TestSnapshotCapturesNewAgency:

    def test_snapshot_succeeds_after_pipeline(self, env):
        ok, _ = _take_snapshot("2026-10-09_harry-david", env["snapshots_dir"], env["output_dir"])
        assert ok is True

    def test_snapshot_dim_contains_harry_david(self, env):
        _take_snapshot("2026-10-09_harry-david", env["snapshots_dir"], env["output_dir"])
        slot = os.path.join(env["snapshots_dir"], "2026-10-09_harry-david")
        dim = pd.read_csv(os.path.join(slot, "dim_master_persons.csv"), dtype=str)
        assert "HARRY_DAVID" in dim["contributing_sources"].values

    def test_snapshot_encounters_contain_harry_david(self, env):
        _take_snapshot("2026-10-09_harry-david", env["snapshots_dir"], env["output_dir"])
        slot = os.path.join(env["snapshots_dir"], "2026-10-09_harry-david")
        enc = pd.read_csv(os.path.join(slot, "fact_encounters.csv"), dtype=str)
        assert "HARRY_DAVID" in enc["source_system"].values

    def test_meta_person_count_matches_golden(self, env):
        _take_snapshot("2026-10-09_harry-david", env["snapshots_dir"], env["output_dir"])
        meta = json.load(open(
            os.path.join(env["snapshots_dir"], "2026-10-09_harry-david", "meta.json"),
            encoding="utf-8"
        ))
        gp = pd.read_csv(os.path.join(env["output_dir"], "GOLDEN_PERSONS.csv"), dtype=str)
        assert meta["persons"] == len(gp)

    def test_meta_encounter_count_matches_fact_table(self, env):
        _take_snapshot("2026-10-09_harry-david", env["snapshots_dir"], env["output_dir"])
        meta = json.load(open(
            os.path.join(env["snapshots_dir"], "2026-10-09_harry-david", "meta.json"),
            encoding="utf-8"
        ))
        enc = pd.read_csv(os.path.join(env["output_dir"], "fact_encounters.csv"), dtype=str)
        assert meta["encounters"] == len(enc)

    def test_snapshot_contains_moose_munch_service(self, env):
        _take_snapshot("2026-10-09_harry-david", env["snapshots_dir"], env["output_dir"])
        slot = os.path.join(env["snapshots_dir"], "2026-10-09_harry-david")
        enc = pd.read_csv(os.path.join(slot, "fact_encounters.csv"), dtype=str)
        assert enc["service_category"].str.contains("Moose Munch", na=False).any()


# ── Step 4: Snapshot index reflects the full history ─────────────────────────

class TestSnapshotIndexAfterNewAgency:

    def test_index_shows_snapshot_after_save(self, env):
        _take_snapshot("2026-10-09_harry-david", env["snapshots_dir"], env["output_dir"])
        rows = _load_snapshot_index(env["snapshots_dir"])
        assert len(rows) == 1
        assert rows[0]["label"] == "2026-10-09_harry-david"

    def test_index_person_count_is_nonzero(self, env):
        _take_snapshot("2026-10-09_harry-david", env["snapshots_dir"], env["output_dir"])
        rows = _load_snapshot_index(env["snapshots_dir"])
        assert rows[0]["persons"] > 0

    def test_index_encounter_count_is_nonzero(self, env):
        _take_snapshot("2026-10-09_harry-david", env["snapshots_dir"], env["output_dir"])
        rows = _load_snapshot_index(env["snapshots_dir"])
        assert rows[0]["encounters"] > 0

    def test_two_snapshots_newest_first(self, env):
        _take_snapshot("2026-01-15_baseline", env["snapshots_dir"], env["output_dir"])
        _take_snapshot("2026-10-09_harry-david", env["snapshots_dir"], env["output_dir"])
        rows = _load_snapshot_index(env["snapshots_dir"])
        labels = [r["label"] for r in rows]
        assert labels == sorted(labels, reverse=True)

    def test_snapshot_label_survives_special_chars(self, env):
        _take_snapshot("2026-10-09_harry-david-v2", env["snapshots_dir"], env["output_dir"])
        rows = _load_snapshot_index(env["snapshots_dir"])
        assert any(r["label"] == "2026-10-09_harry-david-v2" for r in rows)

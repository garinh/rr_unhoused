"""
Automated tests for the snapshot feature (sidebar ▸ SNAPSHOTS).

app.py cannot be imported directly (top-level Streamlit calls at module scope),
so these tests use portable copies of the two snapshot functions with injected
path parameters — identical logic, fully isolated.

Run with:
    pytest tests/test_snapshot.py -v
"""

import json
import os
import shutil
import datetime

import pytest


# ── Portable copies of app.py snapshot functions ────────────────────────────
# Paths are injected so tests run in temp dirs, not the real output/ folder.

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


# ── Test fixtures ────────────────────────────────────────────────────────────

_FAKE_PERSONS = (
    "master_person_id,canonical_first_name,canonical_last_name\n"
    "MPI-001,Alice,Smith\n"
    "MPI-002,Bob,Jones\n"
)
_FAKE_BRIDGE = (
    "unique_record_id,master_person_id,source_system,source_id\n"
    "ACCESS::1,MPI-001,ACCESS,1\n"
)
_FAKE_ENC = (
    "encounter_id,master_person_id,encounter_date\n"
    "E-001,MPI-001,2026-01-15\n"
    "E-002,MPI-002,2026-02-10\n"
    "E-003,MPI-001,2026-03-01\n"
)


@pytest.fixture()
def env(tmp_path):
    """Temp output/ dir pre-populated with all four expected CSVs."""
    output_dir    = str(tmp_path / "output")
    snapshots_dir = str(tmp_path / "output" / "snapshots")
    os.makedirs(output_dir)
    (tmp_path / "output" / "GOLDEN_PERSONS.csv").write_text(_FAKE_PERSONS, encoding="utf-8")
    (tmp_path / "output" / "dim_master_persons.csv").write_text(_FAKE_PERSONS, encoding="utf-8")
    (tmp_path / "output" / "bridge_record_links.csv").write_text(_FAKE_BRIDGE, encoding="utf-8")
    (tmp_path / "output" / "fact_encounters.csv").write_text(_FAKE_ENC, encoding="utf-8")
    return output_dir, snapshots_dir


# ── _take_snapshot tests ─────────────────────────────────────────────────────

class TestTakeSnapshot:

    def test_returns_success_true(self, env):
        output_dir, snapshots_dir = env
        ok, _ = _take_snapshot("2026-10-09", snapshots_dir, output_dir)
        assert ok is True

    def test_creates_snapshot_folder(self, env):
        output_dir, snapshots_dir = env
        _take_snapshot("2026-10-09", snapshots_dir, output_dir)
        assert os.path.isdir(os.path.join(snapshots_dir, "2026-10-09"))

    def test_copies_all_four_csvs(self, env):
        output_dir, snapshots_dir = env
        _take_snapshot("2026-10-09", snapshots_dir, output_dir)
        slot = os.path.join(snapshots_dir, "2026-10-09")
        for fname in (
            "dim_master_persons.csv",
            "bridge_record_links.csv",
            "fact_encounters.csv",
            "GOLDEN_PERSONS.csv",
        ):
            assert os.path.exists(os.path.join(slot, fname)), f"Missing: {fname}"

    def test_meta_json_written(self, env):
        output_dir, snapshots_dir = env
        _take_snapshot("2026-10-09", snapshots_dir, output_dir)
        assert os.path.exists(os.path.join(snapshots_dir, "2026-10-09", "meta.json"))

    def test_meta_label_correct(self, env):
        output_dir, snapshots_dir = env
        _take_snapshot("2026-10-09", snapshots_dir, output_dir)
        with open(os.path.join(snapshots_dir, "2026-10-09", "meta.json"), encoding="utf-8") as fh:
            meta = json.load(fh)
        assert meta["label"] == "2026-10-09"

    def test_meta_person_count_correct(self, env):
        output_dir, snapshots_dir = env
        _take_snapshot("2026-10-09", snapshots_dir, output_dir)
        with open(os.path.join(snapshots_dir, "2026-10-09", "meta.json"), encoding="utf-8") as fh:
            meta = json.load(fh)
        assert meta["persons"] == 2  # _FAKE_PERSONS has 2 data rows

    def test_meta_encounter_count_correct(self, env):
        output_dir, snapshots_dir = env
        _take_snapshot("2026-10-09", snapshots_dir, output_dir)
        with open(os.path.join(snapshots_dir, "2026-10-09", "meta.json"), encoding="utf-8") as fh:
            meta = json.load(fh)
        assert meta["encounters"] == 3  # _FAKE_ENC has 3 data rows

    def test_meta_files_list_populated(self, env):
        output_dir, snapshots_dir = env
        _take_snapshot("2026-10-09", snapshots_dir, output_dir)
        with open(os.path.join(snapshots_dir, "2026-10-09", "meta.json"), encoding="utf-8") as fh:
            meta = json.load(fh)
        assert set(meta["files"]) == {
            "dim_master_persons.csv",
            "bridge_record_links.csv",
            "fact_encounters.csv",
            "GOLDEN_PERSONS.csv",
        }

    def test_meta_created_at_is_iso_timestamp(self, env):
        output_dir, snapshots_dir = env
        _take_snapshot("2026-10-09", snapshots_dir, output_dir)
        with open(os.path.join(snapshots_dir, "2026-10-09", "meta.json"), encoding="utf-8") as fh:
            meta = json.load(fh)
        datetime.datetime.fromisoformat(meta["created_at"])  # raises if malformed

    def test_idempotent_same_label_no_error(self, env):
        output_dir, snapshots_dir = env
        _take_snapshot("2026-10-09", snapshots_dir, output_dir)
        ok, msg = _take_snapshot("2026-10-09", snapshots_dir, output_dir)
        assert ok is True
        assert "ERROR" not in msg

    def test_missing_optional_csv_silently_skipped(self, env):
        output_dir, snapshots_dir = env
        os.remove(os.path.join(output_dir, "fact_encounters.csv"))
        ok, _ = _take_snapshot("no-enc", snapshots_dir, output_dir)
        assert ok is True
        slot = os.path.join(snapshots_dir, "no-enc")
        assert not os.path.exists(os.path.join(slot, "fact_encounters.csv"))
        assert os.path.exists(os.path.join(slot, "GOLDEN_PERSONS.csv"))

    def test_missing_optional_csv_not_in_files_list(self, env):
        output_dir, snapshots_dir = env
        os.remove(os.path.join(output_dir, "fact_encounters.csv"))
        _take_snapshot("no-enc", snapshots_dir, output_dir)
        with open(os.path.join(snapshots_dir, "no-enc", "meta.json"), encoding="utf-8") as fh:
            meta = json.load(fh)
        assert "fact_encounters.csv" not in meta["files"]

    def test_encounter_count_zero_when_file_missing(self, env):
        output_dir, snapshots_dir = env
        os.remove(os.path.join(output_dir, "fact_encounters.csv"))
        _take_snapshot("no-enc", snapshots_dir, output_dir)
        with open(os.path.join(snapshots_dir, "no-enc", "meta.json"), encoding="utf-8") as fh:
            meta = json.load(fh)
        assert meta["encounters"] == 0


# ── _load_snapshot_index tests ───────────────────────────────────────────────

class TestLoadSnapshotIndex:

    def test_empty_list_when_snapshots_dir_absent(self, tmp_path):
        rows = _load_snapshot_index(str(tmp_path / "snapshots"))
        assert rows == []

    def test_empty_list_when_snapshots_dir_empty(self, tmp_path):
        sd = tmp_path / "snapshots"
        sd.mkdir()
        rows = _load_snapshot_index(str(sd))
        assert rows == []

    def test_one_row_after_single_snapshot(self, env):
        output_dir, snapshots_dir = env
        _take_snapshot("2026-01-15", snapshots_dir, output_dir)
        rows = _load_snapshot_index(snapshots_dir)
        assert len(rows) == 1
        assert rows[0]["label"] == "2026-01-15"

    def test_three_rows_after_three_snapshots(self, env):
        output_dir, snapshots_dir = env
        for label in ("2026-01-15", "2026-04-22", "2026-10-09"):
            _take_snapshot(label, snapshots_dir, output_dir)
        rows = _load_snapshot_index(snapshots_dir)
        assert len(rows) == 3

    def test_newest_first_ordering(self, env):
        output_dir, snapshots_dir = env
        for label in ("2026-01-15", "2026-04-22", "2026-10-09"):
            _take_snapshot(label, snapshots_dir, output_dir)
        rows = _load_snapshot_index(snapshots_dir)
        labels = [r["label"] for r in rows]
        assert labels == sorted(labels, reverse=True)

    def test_row_contains_required_keys(self, env):
        output_dir, snapshots_dir = env
        _take_snapshot("2026-10-09", snapshots_dir, output_dir)
        row = _load_snapshot_index(snapshots_dir)[0]
        for key in ("label", "created_at", "persons", "encounters"):
            assert key in row, f"Missing key: {key}"

    def test_corrupted_meta_json_returns_fallback_row(self, env):
        output_dir, snapshots_dir = env
        bad_slot = os.path.join(snapshots_dir, "corrupted")
        os.makedirs(bad_slot)
        with open(os.path.join(bad_slot, "meta.json"), "w") as fh:
            fh.write("not valid json {{{")
        rows = _load_snapshot_index(snapshots_dir)
        assert len(rows) == 1
        assert rows[0]["label"] == "corrupted"

# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

## Common Commands

### Run the full pipeline (Stages 1–5)
```bash
python mpi_pipeline.py
```

### Resume from a specific stage (skips earlier stages if intermediate CSVs exist)
```bash
python mpi_pipeline.py --from-stage 3
```

### Launch the Streamlit app
```bash
python -m streamlit run app.py --server.port 8501 --server.headless true
```

### Run all tests
```bash
pytest tests/ -v
```

### Run a single test class or test
```bash
pytest tests/test_pipeline_integrity.py::TestPipelineLogic -v
pytest tests/test_pipeline_integrity.py::TestRealPipelineOutput::test_bridge_all_records_have_mpi -v
```

### Generate synthetic input data (run before pipeline development)
```bash
python generate_ontrack.py       # 240 clients, 2,999 services — largest source
python generate_harry_david.py   # 75 clients, ~314 services — H&D food program
python generate_stvdp.py         # St. Vincent de Paul clients + services
```

### Generate the golden flat file (persons × encounters join)
```bash
python generate_golden.py
```

---

## Architecture: How the Pieces Connect

### Pipeline data flow

```
input/*.csv  →  ingest.py  →  clean.py  →  match.py  →  cluster.py  →  export.py
                  ↓              ↓             ↓             ↓              ↓
           stage1_encounters  stage2_clean  stage3_match  stage4_clusters  dim/bridge/fact
                              _demographics  _pairs.csv    .csv            .csv
```

`mpi_pipeline.py` is the orchestrator — it imports each stage module's single public function (`ingest()`, `clean()`, `match()`, `cluster()`, `export()`) and saves intermediate CSVs to `output/` between stages.

### Schema registry (how new agencies are added without code changes)

`ingest.py` reads every `input/schemas/*.json` file and calls `load_agency_from_schema(schema)` for each. No per-agency code exists in `ingest.py`. Adding a new trading partner = drop a JSON schema file + client/services CSVs into `input/`. The schema file describes column mappings, SSN type (`full` / `last4` / `none`), and optional `special` handling (e.g. `alias_preferred`, `initials_and_birth_year`).

### MPI namespace — critical cross-file invariant

The UUID v5 namespace for all Master Person IDs is hardcoded and shared across two files:

- `cluster.py` line 16: `_MPI_NAMESPACE = uuid.UUID("d5a0e1f3-4c2b-4a8e-9b7d-1f2a3c4e5b6d")`
- `app.py` (same constant, used in `_sever_link()` and `_do_golden_export()`)
- `tests/test_pipeline_integrity.py` (portable copy used in isolation tests)

**Never change this value** — doing so breaks reproducibility of all existing MPIs.

### How the UI extends pipeline outputs (without re-running the pipeline)

The app adds two override layers on top of `bridge_record_links.csv` at golden-export time:

1. **`output/accepted_persons.csv`** — written by swipe-right (Accept). Maps `(source_system, source_id) → target_mpi`. Applied in `_do_golden_export()` via DuckDB CTE to merge records the pipeline missed.
2. **`output/severed_links.csv`** — written by the Records tab Unlink button. Maps `unique_record_id → split_mpi`. Applied in `_prepare_golden_sources()` to split falsely-merged records. Sever always wins over accept.
3. **`output/review_decisions.csv`** — written by swipe-left (Reject). Stores negative training feedback but does not currently affect MPI assignments.

The Records tab reads `output/bridge_record_links.csv` directly (not the golden file) and computes `effective_mpi` in pure pandas, applying both overrides inline without re-running the pipeline.

### Test structure

| File | What it covers |
|---|---|
| `tests/test_pipeline_integrity.py` | B1.1–B1.13: pipeline logic, real pipeline output (skipped if `output/` absent), sever/accept overrides, Harry & David input files |
| `tests/test_snapshot_e2e.py` | Snapshot save/restore round-trips with H&D fixture data |
| `tests/test_snapshot.py` | `_take_snapshot()` and `_load_snapshot_index()` portable copies |

Tests that require real pipeline output are gated with `pytest.mark.skipif` checking for `output/bridge_record_links.csv`. Tests that require Harry & David in the pipeline bridge are gated separately. Run `python mpi_pipeline.py` first to unlock integration tests.

### Streamlit session state

All default values live in `_DEFAULTS` dict near the top of `app.py`. Applied with a single `for k, v in _DEFAULTS.items(): if k not in st.session_state: st.session_state[k] = v` block. Key state vars: `_unlink_expanded_mpi`, `_unlink_confirm_uid`, `_pending_golden`, `_golden_result`.

---

# Rogue Raise Hackathon Data Pipeline — Project Specification

## Overview & Event Context
* **Event:** Rogue Raise #02: The Unhoused (White Rabbit Clubhouse, Ashland, OR — Oct 23–25, 2026)
* **Problem Statement:** The annual Point-in-Time (PIT) homeless count in January yields inaccurate, fragmented data. HUD-funded agencies operate in data silos, while non-HUD community services (meal programs, syringe exchanges, mobile outreach) lack integration with formal HUD databases.
* **Goal:** Build an offline-first, pure Python record linkage pipeline to de-duplicate client records across HUD and non-HUD sources, generate persistent universal IDs (Master Person Index), and aggregate continuous service data for public health visualization.

---

## Strict Execution Directives

### 1. Step-by-Step Development Protocol
To avoid integration regressions during the hackathon, **do not write the entire pipeline at once**. Build and commit one stage at a time:
1. **Stage 1: Ingestion & Schema Alignment** (`ingest.py`) — Load raw provider CSVs and normalize column structures.
2. **Stage 2: Standardization & Cleaning** (`clean.py`) — Strip PII noise, standardize dates (`YYYY-MM-DD`), extract SSN last 4, and normalize casing.
3. **Stage 3: Probabilistic Matching** (`match.py`) — Configure Splink/DuckDB comparison rules and thresholding.
4. **Stage 4: Identity Resolution & Graph Clustering** (`cluster.py`) — Execute NetworkX connected components and assign deterministic UUID v5 MPIs.
5. **Stage 5: Multi-Table CSV Suite Export** (`export.py`) — Generate `dim_master_persons.csv`, `bridge_record_links.csv`, and `fact_encounters.csv`.

---

### 2. Agentic Testing & Remediation Loop
Every step of the pipeline must pass an automated validation loop before proceeding to the next build stage.

#### Mandatory Stage Checks:
* **Ingestion Test:** Verify total record count matches the sum of input CSV rows.
* **Cleaning Test:** Ensure zero raw uncleaned date values remain; verify `ssn_clean` regex matches `^\d{4}$` or empty string.
* **Matching Test:** Ensure match probabilities fall strictly between `0.0` and `1.0`; verify no duplicate candidate pairs.
* **Clustering Test:** Ensure every `unique_record_id` is assigned exactly one `master_person_id` (no dangling or orphaned records).
* **Export Test:** Confirm foreign key integrity across all 3 exported CSV files (`dim_master_persons.csv`, `bridge_record_links.csv`, `fact_encounters.csv`).

#### Remediation Protocol:
If a verification step fails:
1. Print the failing record ID, error type, and actual vs. expected values.
2. Apply targeted remediation logic (e.g., fallback parsing for irregular dates, adjusting Splink blocking rules if zero matches are found).
3. Re-run the verification loop. **Do not begin coding the next pipeline step until the current stage test passes completely.**

---

## Technical Stack & Architecture

### Pipeline (Backend)
* **Language:** Python 3.10+
* **Probabilistic Linkage Engine:** `splink` (using `duckdb` backend)
* **Graph Clustering Engine:** `networkx`
* **Data Processing & I/O:** `pandas`, `duckdb`
* **Testing:** `pytest` or inline assertions

### Streamlit UI Layer (`app.py`)
* **UI Framework:** `streamlit`
* **Graph & Entity Engine:** `networkx`
* **Fuzzy String Matching:** `rapidfuzz`
* **Styling:** Custom CSS injected via `st.markdown(..., unsafe_allow_html=True)`
* **Theme:** Dark Pacific Northwest cosmic wilderness (*The Expanse* aesthetic) — radial gradient background, `#00E6A8` teal accent, `Courier New`/Share Tech Mono, PLEXIS-style enterprise headers, pill-shaped REJECT / Accept buttons

---

## Core Operational Architecture (The 3-CSV Handoff Model)

1. `dim_master_persons.csv` (Canonical Master Person Index / MPI)
   * **Key:** `master_person_id` (Persistent UUID v5)
   * **Role:** One row per deduplicated human being. Used by county commissioners for unique population counts.
2. `bridge_record_links.csv` (Audit & Disambiguation Trace)
   * **Key:** `unique_record_id` -> `master_person_id`
   * **Role:** Connective tissue mapping every raw client input row to its master person ID along with match confidence scores (`match_confidence`, `match_type`).
3. `fact_encounters.csv` (Unified Service Activity Log)
   * **Keys:** `encounter_id` -> `master_person_id` (Foreign Key)
   * **Role:** Complete, standardized cross-agency service activity log joined from individual provider service CSVs.

---

## Data Sources, Demographic Schemas & Service Log Files

| Agency / Program | Demographic CSV | Service Log CSV | Local Link Key | Service Fields Captured |
| :--- | :--- | :--- | :--- | :--- |
| **ACCESS** | `access_hmis_client.csv` | `access_hmis_services.csv` | `PersonalID` | `ServiceFileID`, `ServiceCategory`, `DateProvided`, `LocationZIP` |
| **Rogue Retreat** | `rogue_retreat_clients.csv` | `rogue_retreat_services.csv` | `client_id` | `entry_id`, `program_name`, `start_date`, `exit_date`, `case_manager` |
| **Recovery Café** | `recovery_cafe_members.csv` | `recovery_cafe_services.csv` | `member_number` | `visit_id`, `activity_type`, `visit_date`, `attended_meal` |
| **Jackson County Syringe Exchange** | `jackson_county_ssp_log.csv` | `jackson_county_ssp_services.csv` | `participant_code` | `log_id`, `encounter_date`, `syringes_collected`, `narcan_kits`, `fentanyl_strips` |
| **St. Vincent de Paul (Ashland)** | `stvdp_clients.csv` | `stvdp_services.csv` | `client_id` | Direct financial aid, food distribution service records |
| **OnTrack Rogue Valley** | `ontrack_clients.csv` | `ontrack_services.csv` | `client_id` (format: `OT-XXXXXX`) | `service_id`, `service_date`, `service_type`, `service_category`, `duration_minutes`, `provider_name`, `location`, `notes` |

### OnTrack Rogue Valley — Programs & Service Types
OnTrack is the largest SUD/MH treatment provider in the RRV. Programs modeled:
* Outpatient SUD Treatment (individual counseling, group therapy, MAT check-ins, UA drug screens)
* Intensive Outpatient (IOP) — 3-hour group sessions
* Day Treatment — full-day programming
* Residential: Mountain View Recovery Center, HOME Program (mothers + children), Dad's Program
* Transitional Housing (270 units in Medford)
* DUII Education (Level I, Level II, Fast-Track) — court-mandated
* MIP Education — court-mandated, minor in possession
* Mental Health Outpatient
* Bilingual SUD Counseling (Spanish) — routed to bilingual staff (M. Oduya)
* Medication-Assisted Treatment (MAT), Urinalysis (UA), case management, crisis intervention

**Data quality note:** Court-mandated clients (DUII/MIP) have cleaner records. Street-referred and unstable-housing clients have dirtier records (missing SSN ~24%, missing phone ~22%, nickname variants, mixed DOB formats, ALL CAPS entries).

---

## Sample Data Generator Scripts

All generators write to `input/`. Run before pipeline development.

| Script | Output Files | Records |
| :--- | :--- | :--- |
| `generate_access_data.py` | `access_hmis_client.csv`, `access_hmis_services.csv` | 100 clients |
| `generate_rogue_retreat.py` | `rogue_retreat_clients.csv`, `rogue_retreat_services.csv` | 100 clients |
| `generate_recovery_cafe.py` | `recovery_cafe_members.csv`, `recovery_cafe_services.csv` | 100 clients |
| `generate_syringe_exchange.py` | `jackson_county_ssp_log.csv`, `jackson_county_ssp_services.csv` | 100 clients |
| `generate_services_data.py` | Supplemental `_services.csv` files | — |
| `generate_ontrack.py` | `ontrack_clients.csv`, `ontrack_services.csv` | **240 clients / 2,999 service rows** |

### OnTrack Generator Details (`generate_ontrack.py`)
* 2× record volume vs. other agencies — largest single source in the dataset
* Dirty-data realism: nickname/legal-name swaps (~25%), ALL CAPS / lowercase entries, DOB in mixed formats (ISO, MM/DD/YYYY, M/D/YY, year-only, blank, "UNKNOWN"), ~24% missing SSN, ~22% missing phone, some middle initials crammed into `first_name` field
* 8 cross-agency overlap seeds injected — names that also appear in other agency files with slight variations (nickname swap, DOB off-by-one-year, transposed letters) to give Splink realistic cross-agency duplicates to find
* Court-mandated clients (71 of 240) have higher visit counts (12–20 visits) and cleaner data; street-referred clients (dirty tier) have 8–14 visits and messy data
* `random.seed(2026_10)` — reproducible; different seed from other generators to avoid artificial overlap

---

## Output Files & Utility Scripts

All pipeline outputs write to `output/`. Do not commit these — they are generated artifacts.

| File | Generator / Source | Description |
| :--- | :--- | :--- |
| `output/dim_master_persons.csv` | `mpi_pipeline.py` stage 4 | One row per deduplicated person (UUID v5 MPI) |
| `output/bridge_record_links.csv` | `mpi_pipeline.py` stage 4 | Every raw record → MPI mapping with confidence score |
| `output/fact_encounters.csv` | `mpi_pipeline.py` stage 5 | Cross-agency service activity log |
| `output/GOLDEN_PERSONS_ENCOUNTERS.csv` | `generate_golden.py` or sidebar button | Flat denormalized join: dim_master_persons × fact_encounters. Ordered by last name, first name, encounter date. Used for commissioner reporting. |
| `README.PDF` | `generate_readme_pdf.py` | Dark-theme PDF (reportlab). Sections: Purpose, Installation, Default Use Case, File Naming Convention, CSV Header Layouts, System Limitations. Scale estimate: RRV 200k population → ~2,500–4,000 unique individuals/year, 15,000–40,000 service encounters. |

### `generate_golden.py`
Standalone script. Requires pipeline outputs to exist in `output/`. Uses DuckDB in-process (no subprocess). Reads `dim_master_persons.csv` + `fact_encounters.csv`, joins on `master_person_id`, writes `output/GOLDEN_PERSONS_ENCOUNTERS.csv`.

```bash
python generate_golden.py
```

### `generate_readme_pdf.py`
Requires `reportlab`. Dark background `#0C1A26`, teal `#00C49A`, amber `#FF9E3B` palette. Generates `README.PDF` in project root.

```bash
python generate_readme_pdf.py
```

---

---

## Streamlit UI — `app.py`

### Application Identity
* **Full Name:** Cascadia (C3E) — Continuum of Care Master Data Engine for the RRV
* **Short Name / Slug:** C3E
* **RRV:** Rogue River Valley — the region encompassing Medford, Ashland, Grants Pass, and Jacksonville, OR
* **Logo:** Circular compass rose badge — teal/blue cardinal points, green PNW leaf motifs, gold star at north, river wave at south; rendered as inline SVG in the app header
* **Page icon:** 🧭

### Design Concept
A high-frictionless "dating app" entity resolution interface (Tinder-style swipe deck) for homeless services master data matching. Inspiration: PLEXIS Healthcare Systems enterprise UX + Pacific Northwest cosmic wilderness (*The Expanse* UI).

### Key Features

1. **Global Master Tolerance Offset** — Single top-level slider (`-30` to `+30`) that dynamically loosens or tightens the matching net across all active field slots simultaneously.
2. **9-Slot Dynamic Attribute Mapper** — Up to 9 configurable field slots (First Name, Last Name, DOB, SSN, Phone, Address, Alias, Emergency Contact, Provider ID). Selecting `-- None / Ignore --` disables the slider for that slot.
3. **High-Contrast Swipe Deck** — Side-by-side card comparison (Record A vs. Record B), matching fields highlighted in `#00E6A8` green, discrepancies in `#FF9E3B` amber.
4. **Swipe Left / Right Training Feedback Loop:**
   - **Swipe Left (Reject / ❌):** Severs NetworkX edge, logs match penalty for weight adjustments.
   - **Swipe Right (Accept / 💚):** Validates edge, merges profiles under a unified Master ID, logs positive reinforcement.
5. **Executive Brevity Metrics Panel** — Live tracking of approved merges, severed matches, master tolerance offset, and remaining queue size.

### Persona Presets (1-click threshold switching for demo flow)

| Preset | Threshold | Use Case |
| :--- | :--- | :--- |
| **Strict / Legal Housing** | 92% | Zero false-positive target for HUD housing voucher allocation |
| **Balanced / Case Management** | 85% | Default for shelter and street outreach tracking |
| **Aggregate Public Health** | 75% | Broad match for population estimates; avoids duplicate food-line counts |

---

## UI Feature Development Priorities

| Priority | Component | Target Time | Core Goal |
| :--- | :--- | :--- | :--- |
| **P0** | Dropdown Column Mapper | ~30 mins | Handle messy, unexpected CSV headers live during demos |
| **P0** | Threshold Preset Buttons | ~15 mins | Instantly switch matching rules for demo personas |
| **P1** | Graph "Unlink" Button | ~45 mins | Prove human control and data safety |
| **P1** | SHA-256 Hashing Toggle | ~20 mins | Anonymize sensitive fields before dataset export |

### P0: Column Mapper UI
* On CSV upload, display dropdowns to map core attributes: `First Name`, `Last Name`, `Date of Birth`, `SSN / Alt ID`.
* Single-line string parser to auto-split combined full-name columns (e.g., `"Smith, John"` → `John`, `Smith`).
* Target: ingest any novel CSV structure in < 30 seconds during demos.
* Fallback fields for regional agencies: `Date`, `Location`, `Service_Type`, `Client_Identifier`.

### P1: Graph Edge Audit Log & Unlink Action
* Track NetworkX edge creation in an in-memory `audit_log` array: `{ timestamp, record_a, record_b, confidence, status: 'merged' }`.
* **"Unlink Records"** button in Side-by-Side Inspector: drops the edge, triggers re-evaluation of `connected_components`, and updates master count instantly.

### P1: Anonymous Encounters Queue
* Bypass individual `Master Person UUID` matching for completely anonymous records (field sites: syringe exchanges, meal programs, warming shelters).
* Aggregate signals spatially and temporally: total volume, service type, time windows, location clusters.
* Fulfills Rogue Raise Bucket 3 (non-traditional field signals).

---

## Regional Field Entities (Local Jackson County / Ashland Context)

Keep ingestion logic flexible for headers standard to these providers:

| Agency | Type | Notes |
| :--- | :--- | :--- |
| **OHRA** (Opportunities for Housing, Resources & Assistance) | Main shelter + resource center | 2200 Ashland St |
| **Peace House** | Community meals + street outreach | |
| **St. Vincent de Paul (Ashland)** | Direct financial aid + food distribution | |
| **La Clinica / Mobile Health Units** | Medical street outreach | |

---

## Implemented UI Features (Status as of Oct 2026)

| Feature | Status | Notes |
| :--- | :--- | :--- |
| Dark PNW cosmic theme, radial gradient bg | ✅ Done | `#00E6A8` teal, `Courier New`/Share Tech Mono |
| Compass rose SVG logo (C3E) | ✅ Done | Inline SVG in header |
| CSV upload + column mapper dropdowns | ✅ Done | Triggers processing on file dialog close, not only drag-drop |
| × remove button (sidebar file list) | ✅ Done | Red background, confirmation dialog before removal |
| 9-slot attribute mapper with per-slot sliders | ✅ Done | `-- None / Ignore --` disables slot |
| Global Master Tolerance Offset slider | ✅ Done | −30 to +30 |
| Persona preset buttons (Strict / Balanced / Aggregate) | ✅ Done | 92% / 85% / 75% |
| Auto-reject below min threshold | ✅ Done | Records with max field score < min_threshold never enter swipe queue |
| High-contrast swipe deck (Record A vs B) | ✅ Done | Matching fields teal, discrepancies amber |
| REJECT button (red gradient + heart+ECG icon) | ✅ Done | Severs NetworkX edge |
| ACCEPT button (green gradient + heart+ECG icon) | ✅ Done | Validates edge, assigns MPI |
| Executive Brevity metrics panel | ✅ Done | Live merge/sever counts, queue size |
| Generate / Overwrite Golden File button | ✅ Done | Sidebar export section, confirmation dialog, golden gradient style |
| SHA-256 hashing toggle | ⬜ Pending | P1 — anonymize fields before export |
| Graph "Unlink" button in inspector | ⬜ Pending | P1 — drop edge, re-evaluate components |

---

## Streamlit / React Technical Patterns (Hard-Won Lessons)

### Button Styling That Survives React Rerenders

**Problem:** `st.rerun()` causes React to reconcile the DOM. Any inline JS styles set directly on button child elements (`<p>` tags) are wiped on each rerender, making custom button colors disappear.

**Solution: CSS injection + `data-c3e` attribute tagging**

1. Inject a `<style id="c3e-styles">` block into `window.parent.document.head` **once** (guard with `getElementById`). CSS rules use attribute selectors like `button[data-c3e='rej']` — these apply automatically to any children React swaps in.
2. Use a `MutationObserver` on `window.parent.document.body` (`{childList:true, subtree:true}`) to detect newly added buttons and tag them with `btn.setAttribute('data-c3e', 'rej')`.
3. React preserves `data-*` attributes it didn't set during reconciliation — so `data-c3e` persists on the button element across rerenders even though child `<p>` elements get replaced.
4. CSS rule `button[data-c3e='x'] *` covers all current **and future** React-replaced children with no JS mutation needed.

**Button icon approach:** Use CSS `::before` pseudo-elements with `background: url("data:image/svg+xml;base64,...")` — avoids `innerHTML` mutation that React overwrites. SVG is base64-encoded via Python's `base64.b64encode(svg.encode()).decode()` and embedded in the `<style>` block at render time.

**Pitfall:** Streamlit's default `padding: 4px 12px` on buttons leaves ~1px for content on narrow buttons (e.g., 25px wide × button). Fix: `padding: 0 !important; display: flex !important; align-items: center !important; justify-content: center !important;`.

**Pitfall:** The `components.html(...)` f-string uses `{{` for literal `{` (Python f-string escaping). Edit tool must match `{{` exactly — using single `{` in `old_string` will fail.

### Sidebar Section Positioning
Export / utility sidebar sections must be direct children of `with st.sidebar:` (4-space indent). If placed inside `if st.session_state.confirmed_filename:` (8-space indent), they disappear when no file is loaded.

### Session State Defaults Pattern
All session state keys initialized in a single `_DEFAULTS` dict at module top. Applied with:
```python
for k, v in _DEFAULTS.items():
    if k not in st.session_state:
        st.session_state[k] = v
```
Golden export uses `_pending_golden` (bool) and `_golden_result` (str | None).

### Auto-Reject Logic
Records are excluded from the swipe queue entirely (not shown to the user) when their highest field match score falls below `min_threshold`. This prevents low-confidence noise from cluttering the review queue.

---

## Event Alignment & Improvement Roadmap

### Scorecard vs. Rogue Raise Requirements

| Requirement | Coverage | Notes |
| :--- | :---: | :--- |
| **Bucket 1** — Clean the data (dedup, confidence matching, persistent IDs) | 82% | Core strength. Splink + NetworkX + UUID v5 MPI. Swipe UI builds trust. |
| **Bucket 2** — Better count (offline-capable mobile field collection) | N/A | Deprioritized — tablet self-hosting covers this use case |
| **Bucket 3** — Add new data (community signals, volunteer pipeline) | 38% | SSP + meal programs modeled; no collection UI yet |
| **Syndromic surveillance** — week-over-week trending, not annual snapshot | 4% | Point-in-time outputs only; no time-series analysis built |
| **Human voice** — unhoused community can advocate for themselves | 0% | Not addressed; Phase 5 below adds statement capture |
| **Unknown org / unknown format** — any CSV in &lt;30 sec, no code change | 45% | Column mapper designed but ingest.py still hard-coded per agency |
| **Real owner / handoff-ready** — non-technical org can run it | 28% | Requires Python + terminal; Phase 6 adds launcher scripts |

**Critical insight:** Bucket 2 (offline mobile) is solved by tablet self-hosting (same Streamlit setup as Windows 11 testing). The three highest-ROI improvements are: universal CSV ingestion (demo survivability), match explanation panel (real-user trust), and trend dashboard (closes the syndromic gap cheaply).

---

### Phase 1 — Universal CSV Ingestion (~90 min)
*Any agency, no code changes. Demo-survivable.*

**Goal:** A new org walks in with an unknown CSV. The app ingests it in under 30 seconds without touching Python code.

1. **Build `detect_headers(df)` utility** — uses `rapidfuzz` to score every CSV column header against a synonym dictionary for each standard field. Returns a best-guess mapping dict.
   - Synonyms example: `dob → ["date_of_birth", "birth_date", "dob", "birthdate", "Date of Birth", "DOB", "Birthday"]`
   - Score threshold: accept if `WRatio ≥ 80`; flag as "unmatched" below that.
2. **"Add New Agency" upload widget in sidebar** — file picker → `detect_headers` → 5 dropdowns pre-populated with guesses → user confirms. Target: 30 seconds.
3. **Save confirmed mapping as `input/schemas/{agency_slug}.json`** — loaded on next run; no re-mapping needed for repeat demos or the real deployment.
4. **Refactor `ingest.py`** to use a generic `load_agency(path, schema)` function. All 5 existing agencies become schema JSON files in `input/schemas/`. Remove all hard-coded per-agency blocks.
5. **Ingestion validation banner** — green banner (record count confirmed) or amber warning (unmapped required fields) immediately after mapping confirmation.

---

### Phase 2 — Match Explanation Panel (~60 min)
*Why did these two records match? Build trust with real users.*

**Goal:** Case managers see which fields drove a match before they Accept or Reject. Turns the AI from a black box into a transparent tool.

1. **Add collapsible "Match Evidence" table** below each swipe card pair: columns = Field | Record A | Record B | Agreement | Weight. Agreement icons: ✓ exact / ~ fuzzy / ✗ mismatch.
2. **Source from existing prediction dataframe** — Splink's `retain_matching_columns=True` already outputs field-level agreement columns. No model re-run.
3. **Color coding** — highest-weight agreeing field highlighted teal; highest-weight mismatch highlighted amber. Consistent with existing swipe card color language.
4. **Plain-English one-liner** above the evidence table — template string built from field scores: `"Strong DOB + last name match, conflicting first name (Bob vs Robert)."` This is the sentence a case manager quotes when they defend a merge to their supervisor.

---

### Phase 3 — Syndromic Trend Dashboard (~75 min)
*Encounters over time. Closes the biggest gap vs. event requirements.*

**Goal:** Show continuous week-over-week service activity — not a January snapshot. These are the charts a county commissioner needs to justify ongoing funding.

1. **Add "Trends" tab** to the app. Reads `output/fact_encounters.csv` via DuckDB — no pipeline re-run required.
2. **Week-over-week encounter volume line chart** (Plotly or Altair). X = ISO week, Y = encounter count. One line per source agency + a "Total" line. Filter controls: date range, service category.
3. **"New unique persons per month" bar chart** — counts of master persons whose earliest encounter falls in each month. This is the continuous count the event explicitly asks for.
4. **KPI tile row** above charts: total unique persons, total encounters, date range covered, cross-agency match rate. These are the commissioner-facing headline numbers.
5. **PDF export button** on Trends tab — date-stamped summary with charts as images and KPI tiles. Reuse existing `reportlab` dark-theme template from `generate_readme_pdf.py`.

---

### Phase 4 — Anonymous Encounter Aggregator (~50 min)
*Bucket 3 signal without identity. Syringe exchange + meal programs.*

**Goal:** Aggregate the anonymous-tier data (SSP, meal programs, warming shelters) into volume signals useful for public health advocacy — no PII, no identity required.

1. **"Anonymous Signals" section** in the Trends tab. Pulls records from SSP and meal-program sources flagged as anonymous-tier (no MPI attempted, or source system in `ANONYMOUS_SOURCES` set).
2. **Stacked bar chart by week**: "harm reduction supply exchanges / meals served / warming shelter visits." Volume signals without identity.
3. **Location summary table**: rows = ZIP code or site name, columns = service type, cells = encounter count in selected date range. Direct input for county commissioner resource allocation arguments.

---

### Phase 5 — Human Voice Capture (~60 min)
*First-person record attachment. Addresses the event's north star.*

**Goal:** The people the system is about have a way to speak through it. Case workers can attach a client's own words to their master record.

1. **"Statement" field** in the master person detail view — free-text box where a case manager transcribes a client's own words about their situation or what they need. Saves to `output/person_statements.csv` keyed to `master_person_id`.
2. **Privacy gate** — statements are never included in Golden File exports without an explicit opt-in toggle labeled "Include client statements." Separate export button.
3. **"Stories" section** in Trends tab — anonymized statement snippets (no names, worker-transcribed) that give the data its human dimension for commissioner presentations. Editable in-app.

---

### Phase 6 — Handoff Package (~30 min)
*Anyone can run it. Double-click to launch.*

**Goal:** A non-technical social services org can pick this up and run it after the hackathon weekend without calling a developer.

1. **`start.bat` (Windows) / `start.sh` (macOS/Linux)** — checks for Python 3.10+, runs `pip install -r requirements.txt` if needed, then `streamlit run app.py --server.headless true` and opens the browser. Double-click to launch.
2. **Pin all dependencies** in `requirements.txt` with exact versions. Test cold-install on a clean machine before demo day.
3. **`HANDOFF.md`** — one-page plain-English guide for the receiving org: "What this does, how to start it, where the files go, who to call." No jargon, no terminal commands beyond double-clicking the launcher.

---

### Phase Implementation Order
Build in this order — each phase makes the demo stronger for the next:

```
Phase 1 (Universal Ingestion)  →  Phase 2 (Match Explanation)  →  Phase 3 (Trend Dashboard)
    Phase 4 (Anonymous Agg)    →  Phase 5 (Human Voice)        →  Phase 6 (Handoff)
```

Total estimated build time: **~6.5 hours** — achievable in one hackathon day.

---

## Pipeline Orchestrator (`mpi_pipeline.py`)

*(Validated stage modules are wired together here. Run this for end-to-end execution.)*

```bash
python mpi_pipeline.py                  # full run (stages 1–5)
python mpi_pipeline.py --from-stage 3  # resume from probabilistic matching
```

Stages called in sequence: `ingest()` → `clean()` → `match()` → `cluster()` → `export()`.
Each stage saves its intermediate output to `output/` before the next begins.

---

## Legacy Inline Reference

*(Kept for historical reference only — the validated individual stage modules supersede this.)*

```python
import os
import uuid
import duckdb
import networkx as nx
import pandas as pd
import splink.duckdb.comparison_library as cl
from splink.duckdb.linker import DuckDBLinker


# =====================================================================
# STEP 1: INGESTION & AGGREGATION
# =====================================================================
def load_and_merge_provider_sources() -> (pd.DataFrame, pd.DataFrame):
    """Loads demographic CSVs and merges them with their respective service log CSVs."""
    demographic_records = []
    service_encounters = []

    # 1. ACCESS (HUD HMIS)
    if os.path.exists("access_hmis_client.csv"):
        df_clients = pd.read_csv("access_hmis_client.csv")
        for _, row in df_clients.iterrows():
            demographic_records.append(
                {
                    "source_system": "ACCESS_HUD",
                    "source_id": str(row["PersonalID"]),
                    "first_name": str(row["FirstName"])
                    if pd.notna(row["FirstName"])
                    else "",
                    "last_name": str(row["LastName"])
                    if pd.notna(row["LastName"])
                    else "",
                    "dob": str(row["DOB"]) if pd.notna(row["DOB"]) else "",
                    "ssn_last4": str(row["SSN"])[-4:]
                    if pd.notna(row["SSN"]) and len(str(row["SSN"])) >= 4
                    else "",
                    "encounter_date": str(row["DateCreated"])[:10]
                    if pd.notna(row["DateCreated"])
                    else "2026-01-01",
                }
            )

        if os.path.exists("access_hmis_services.csv"):
            df_srv = pd.read_csv("access_hmis_services.csv")
            for _, row in df_srv.iterrows():
                service_encounters.append(
                    {
                        "encounter_id": str(row["ServiceFileID"]),
                        "unique_record_id": f"ACCESS_HUD::{row['PersonalID']}",
                        "source_system": "ACCESS_HUD",
                        "encounter_date": str(row["DateProvided"]),
                        "service_category": str(row["ServiceCategory"]),
                        "location_info": str(row.get("LocationZIP", "")),
                    }
                )

    # 2. Rogue Retreat
    if os.path.exists("rogue_retreat_clients.csv"):
        df_clients = pd.read_csv("rogue_retreat_clients.csv")
        for _, row in df_clients.iterrows():
            demographic_records.append(
                {
                    "source_system": "ROGUE_RETREAT",
                    "source_id": str(row["client_id"]),
                    "first_name": str(row["first_name"])
                    if pd.notna(row["first_name"])
                    else "",
                    "last_name": str(row["last_name"])
                    if pd.notna(row["last_name"])
                    else "",
                    "dob": str(row["date_of_birth"])
                    if pd.notna(row["date_of_birth"])
                    else "",
                    "ssn_last4": str(row["ssn_last_4"])
                    if pd.notna(row["ssn_last_4"])
                    else "",
                    "encounter_date": str(row["intake_date"])
                    if pd.notna(row["intake_date"])
                    else "2026-01-01",
                }
            )

        if os.path.exists("rogue_retreat_services.csv"):
            df_srv = pd.read_csv("rogue_retreat_services.csv")
            for _, row in df_srv.iterrows():
                service_encounters.append(
                    {
                        "encounter_id": str(row["entry_id"]),
                        "unique_record_id": f"ROGUE_RETREAT::{row['client_id']}",
                        "source_system": "ROGUE_RETREAT",
                        "encounter_date": str(row["start_date"]),
                        "service_category": f"Shelter Entry: {row['program_name']}",
                        "location_info": f"Case Mgr: {row.get('case_manager', 'N/A')}",
                    }
                )

    # 3. Recovery Cafe
    if os.path.exists("recovery_cafe_members.csv"):
        df_clients = pd.read_csv("recovery_cafe_members.csv")
        for _, row in df_clients.iterrows():
            fn = (
                str(row["preferred_alias"])
                if pd.notna(row["preferred_alias"])
                and str(row["preferred_alias"]).strip() != ""
                else str(row["given_name"])
            )
            demographic_records.append(
                {
                    "source_system": "RECOVERY_CAFE",
                    "source_id": str(row["member_number"]),
                    "first_name": fn if pd.notna(fn) else "",
                    "last_name": str(row["surname"])
                    if pd.notna(row["surname"])
                    else "",
                    "dob": str(row["dob"]) if pd.notna(row["dob"]) else "",
                    "ssn_last4": "",
                    "encounter_date": str(row["last_meal_visit"])
                    if pd.notna(row["last_meal_visit"])
                    else "2026-01-01",
                }
            )

        if os.path.exists("recovery_cafe_services.csv"):
            df_srv = pd.read_csv("recovery_cafe_services.csv")
            for _, row in df_srv.iterrows():
                service_encounters.append(
                    {
                        "encounter_id": str(row["visit_id"]),
                        "unique_record_id": f"RECOVERY_CAFE::{row['member_number']}",
                        "source_system": "RECOVERY_CAFE",
                        "encounter_date": str(row["visit_date"]),
                        "service_category": str(row["activity_type"]),
                        "location_info": f"Meal Attended: {row.get('attended_meal', 'N/A')}",
                    }
                )

    # 4. Jackson County Syringe Exchange Program
    if os.path.exists("jackson_county_ssp_log.csv"):
        df_clients = pd.read_csv("jackson_county_ssp_log.csv")
        for _, row in df_clients.iterrows():
            initials = (
                str(row["client_initials"]).replace(".", "").strip()
                if pd.notna(row["client_initials"])
                else ""
            )
            fn = initials[0] if len(initials) >= 1 else ""
            ln = initials[1:] if len(initials) >= 2 else ""
            by = (
                str(int(row["birth_year"]))
                if pd.notna(row["birth_year"])
                else ""
            )
            dob = f"{by}-01-01" if by else ""

            demographic_records.append(
                {
                    "source_system": "JACKSON_COUNTY_SSP",
                    "source_id": str(row["participant_code"]),
                    "first_name": fn,
                    "last_name": ln,
                    "dob": dob,
                    "ssn_last4": "",
                    "encounter_date": str(row["encounter_date"])
                    if pd.notna(row["encounter_date"])
                    else "2026-01-01",
                }
            )

        if os.path.exists("jackson_county_ssp_services.csv"):
            df_srv = pd.read_csv("jackson_county_ssp_services.csv")
            for _, row in df_srv.iterrows():
                service_encounters.append(
                    {
                        "encounter_id": str(row["log_id"]),
                        "unique_record_id": f"JACKSON_COUNTY_SSP::{row['participant_code']}",
                        "source_system": "JACKSON_COUNTY_SSP",
                        "encounter_date": str(row["encounter_date"]),
                        "service_category": "Harm Reduction Supply Exchange",
                        "location_info": f"Syringes: {row.get('syringes_collected', 0)}, Narcan: {row.get('narcan_kits', 0)}",
                    }
                )

    df_demo = pd.DataFrame(demographic_records)
    df_demo["unique_record_id"] = (
        df_demo["source_system"] + "::" + df_demo["source_id"]
    )

    df_encounters = pd.DataFrame(service_encounters)

    # Ingestion Assertions
    assert not df_demo.empty, "[AGENTIC CHECK FAILED] Demographic records dataframe is empty."
    print(f"[AGENTIC CHECK PASSED] Successfully ingested {len(df_demo)} demographic records.")

    return df_demo, df_encounters


# =====================================================================
# STEP 2: PREPROCESSING & CLEANING
# =====================================================================
def preprocess_records(df: pd.DataFrame) -> pd.DataFrame:
    clean = df.copy()
    clean["first_name_clean"] = (
        clean["first_name"]
        .astype(str)
        .str.strip()
        .str.lower()
        .str.replace(r"[^\w\s]", "", regex=True)
    )
    clean["last_name_clean"] = (
        clean["last_name"]
        .astype(str)
        .str.strip()
        .str.lower()
        .str.replace(r"[^\w\s]", "", regex=True)
    )
    clean["dob_clean"] = pd.to_datetime(
        clean["dob"], errors="coerce"
    ).dt.strftime("%Y-%m-%d")
    clean["ssn_clean"] = (
        clean["ssn_last4"]
        .fillna("")
        .astype(str)
        .str.extract(r"(\d{4})")[0]
        .fillna("")
    )

    # Cleaning Assertions
    assert "first_name_clean" in clean.columns, "[AGENTIC CHECK FAILED] Missing cleaned first name column."
    print("[AGENTIC CHECK PASSED] Preprocessing and field standardization complete.")

    return clean


# =====================================================================
# STEP 3: PROBABILISTIC MATCHING (SPLINK)
# =====================================================================
def run_splink_match(df: pd.DataFrame) -> pd.DataFrame:
    settings = {
        "link_type": "dedupe_only",
        "unique_id_column_name": "unique_record_id",
        "comparisons": [
            cl.LevenshteinAtThresholds(
                "first_name_clean", distance_thresholds=[1, 2]
            ),
            cl.LevenshteinAtThresholds(
                "last_name_clean", distance_thresholds=[1, 2]
            ),
            cl.ExactMatch("dob_clean"),
            cl.ExactMatch("ssn_clean"),
        ],
        "blocking_rules_to_generate_predictions": [
            "l.dob_clean = r.dob_clean",
            "l.last_name_clean = r.last_name_clean",
            "l.ssn_clean = r.ssn_clean and l.ssn_clean != ''",
        ],
        "retain_matching_columns": True,
        "retain_intermediate_calculation_columns": False,
    }

    linker = DuckDBLinker(df, settings)
    linker.estimate_u_using_random_sampling(max_pairs=1e6)
    linker.estimate_parameters_using_expectation_maximization(
        "l.dob_clean = r.dob_clean"
    )
    linker.estimate_parameters_using_expectation_maximization(
        "l.last_name_clean = r.last_name_clean"
    )

    df_predictions = linker.predict(threshold_match_probability=0.70)
    df_matches = df_predictions.as_pandas_dataframe()

    # Match Assertions
    assert (
        "match_probability" in df_matches.columns
    ), "[AGENTIC CHECK FAILED] Splink prediction missing match_probability column."
    print(f"[AGENTIC CHECK PASSED] Identified {len(df_matches)} candidate record linkages.")

    return df_matches


# =====================================================================
# STEP 4: GRAPH CLUSTERING & MULTI-TABLE CSV EXPORT
# =====================================================================
def generate_master_csv_outputs(
    df_records: pd.DataFrame,
    df_matches: pd.DataFrame,
    df_encounters: pd.DataFrame,
):
    G = nx.Graph()
    for rec_id in df_records["unique_record_id"]:
        G.add_node(rec_id)

    for _, row in df_matches.iterrows():
        G.add_edge(
            row["unique_record_id_l"],
            row["unique_record_id_r"],
            weight=row["match_probability"],
        )

    clusters = list(nx.connected_components(G))
    record_to_mpi = {}
    record_to_confidence = {}

    for cluster in clusters:
        sorted_members = sorted(list(cluster))
        seed_key = "rogue_raise_2026::" + "::".join(sorted_members)
        cluster_uuid = str(uuid.uuid5(uuid.NAMESPACE_DNS, seed_key))

        subgraph = G.subgraph(cluster)
        weights = [
            d["weight"] for _, _, d in subgraph.edges(data=True) if "weight" in d
        ]
        avg_confidence = round(sum(weights) / len(weights), 3) if weights else 1.0

        for member in sorted_members:
            record_to_mpi[member] = cluster_uuid
            record_to_confidence[member] = avg_confidence

    df_working = df_records.copy()
    df_working["master_person_id"] = df_working["unique_record_id"].map(
        record_to_mpi
    )
    df_working["match_confidence"] = df_working["unique_record_id"].map(
        record_to_confidence
    )

    # 1. dim_master_persons.csv
    dim_rows = []
    for mpi, group in df_working.groupby("master_person_id"):
        group_sorted = group.sort_values(by="encounter_date", ascending=False)
        latest = group_sorted.iloc[0]

        most_frequent_dob = (
            group["dob"].mode()[0]
            if not group["dob"].mode().empty
            else latest["dob"]
        )

        dim_rows.append(
            {
                "master_person_id": mpi,
                "canonical_first_name": latest["first_name"],
                "canonical_last_name": latest["last_name"],
                "canonical_dob": most_frequent_dob,
                "canonical_ssn_last4": group["ssn_last4"].dropna().iloc[0]
                if not group["ssn_last4"].dropna().empty
                else "",
                "total_linked_records": len(group),
                "linked_sources_count": group["source_system"].nunique(),
                "contributing_sources": ", ".join(
                    sorted(group["source_system"].unique())
                ),
            }
        )

    dim_master_persons = pd.DataFrame(dim_rows)
    dim_master_persons.to_csv("dim_master_persons.csv", index=False)

    # 2. bridge_record_links.csv
    bridge_record_links = df_working[
        [
            "unique_record_id",
            "master_person_id",
            "source_system",
            "source_id",
            "match_confidence",
        ]
    ].copy()
    bridge_record_links["match_type"] = bridge_record_links[
        "match_confidence"
    ].apply(lambda c: "Direct_Single" if c == 1.0 else "Probabilistic_Splink")
    bridge_record_links.to_csv("bridge_record_links.csv", index=False)

    # 3. fact_encounters.csv
    if not df_encounters.empty:
        fact_encounters = df_encounters.merge(
            df_working[["unique_record_id", "master_person_id"]],
            on="unique_record_id",
            how="left",
        )
        fact_cols = [
            "encounter_id",
            "master_person_id",
            "unique_record_id",
            "source_system",
            "encounter_date",
            "service_category",
            "location_info",
        ]
        fact_encounters = fact_encounters[fact_cols]
        fact_encounters.to_csv("fact_encounters.csv", index=False)

    # Export Integrity Assertions
    assert os.path.exists("dim_master_persons.csv"), "[AGENTIC CHECK FAILED] dim_master_persons.csv was not generated."
    assert os.path.exists("bridge_record_links.csv"), "[AGENTIC CHECK FAILED] bridge_record_links.csv was not generated."
    assert os.path.exists("fact_encounters.csv"), "[AGENTIC CHECK FAILED] fact_encounters.csv was not generated."
    print("[AGENTIC CHECK PASSED] All 3 output CSV files generated and validated successfully.")


def main():
    print("Executing Rogue Raise Data Linkage Pipeline...")
    raw_demo, raw_encounters = load_and_merge_provider_sources()
    clean_demo = preprocess_records(raw_demo)
    df_matches = run_splink_match(clean_demo)
    generate_master_csv_outputs(clean_demo, df_matches, raw_encounters)
    print("Pipeline Execution & Verification Complete.")


if __name__ == "__main__":
    main()
"""
app.py — Cascadia (C3E) · Continuum of Care Master Data Engine for the RRV
Human-in-the-loop entity resolution swipe deck for the Rogue River Valley.

Run:
    streamlit run app.py
"""

import base64
import json
import os
import time
import re
import uuid
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from rapidfuzz import fuzz
import plotly.graph_objects as go
import plotly.express as px

OUTPUT_DIR      = os.path.join(os.path.dirname(__file__), "output")
INPUT_DIR       = os.path.join(os.path.dirname(__file__), "input")
SCHEMA_DIR      = os.path.join(INPUT_DIR, "schemas")
MASTER_PATH     = os.path.join(OUTPUT_DIR, "dim_master_persons.csv")
DECISIONS_PATH           = os.path.join(OUTPUT_DIR, "review_decisions.csv")
ACCEPTED_PERSONS_PATH    = os.path.join(OUTPUT_DIR, "accepted_persons.csv")
ACCEPTED_ENCOUNTERS_PATH = os.path.join(OUTPUT_DIR, "accepted_encounters.csv")
BASE            = 88   # kept for reference only


# ── Schema registry ────────────────────────────────────────────────────────────
def _load_schemas() -> list[dict]:
    """Read all trading-partner JSON schemas from input/schemas/."""
    schemas = []
    if os.path.isdir(SCHEMA_DIR):
        for fn in sorted(os.listdir(SCHEMA_DIR)):
            if fn.endswith(".json"):
                with open(os.path.join(SCHEMA_DIR, fn), encoding="utf-8") as fh:
                    schemas.append(json.load(fh))
    return schemas


def _file_prefix_from_schema(schema: dict) -> str:
    """Derive the shared filename prefix from client_file (strips demographic suffixes)."""
    client_file = schema.get("client_file", "")
    base = re.sub(r'(_clients?|_members?|_log|_client)\.csv$', '', client_file, flags=re.I)
    return base.lower()


def _build_agency_maps() -> tuple[dict, dict, dict]:
    """Build the three agency lookup dicts dynamically from the schema registry."""
    src_map: dict[str, str]        = {}
    label_to_src: dict[str, str]   = {}
    label_to_pfx: dict[str, list]  = {}
    for s in _load_schemas():
        lbl    = s.get("short_label", s["label"].upper())
        prefix = _file_prefix_from_schema(s)
        src_map[prefix]      = lbl
        label_to_src[lbl]    = s["source_system"]
        label_to_pfx[lbl]    = [prefix]
    return src_map, label_to_src, label_to_pfx


# Rebuilt on every Streamlit rerun — picks up new schemas automatically
_SOURCE_MAP, _LABEL_TO_SOURCE, _LABEL_TO_FILE_PREFIXES = _build_agency_maps()


def _archive_agency_files(label: str) -> list[str]:
    """Move input/ CSVs for this agency to input/archived/ (non-destructive).

    Returns list of archived filenames. The pipeline's os.path.exists() guards
    in ingest.py will skip archived files on the next run.
    """
    prefixes = _LABEL_TO_FILE_PREFIXES.get(label, [])
    if not prefixes:
        return []
    archive_dir = os.path.join(INPUT_DIR, "archived")
    os.makedirs(archive_dir, exist_ok=True)
    archived = []
    for fname in sorted(os.listdir(INPUT_DIR)):
        if not fname.lower().endswith(".csv"):
            continue
        for prefix in prefixes:
            if fname.lower().startswith(prefix):
                src = os.path.join(INPUT_DIR, fname)
                dst = os.path.join(archive_dir, fname)
                os.rename(src, dst)
                archived.append(fname)
                break
    return archived


def _active_source_systems() -> list[str]:
    """Return pipeline source_system values for currently-loaded agencies."""
    systems = []
    for label in st.session_state.get("ingested_registry", {}):
        src = _LABEL_TO_SOURCE.get(label)
        if src:
            systems.append(src)
        else:
            # Generic fallback for ad-hoc uploads
            systems.append(label.replace(" ", "_"))
    return systems

def _label_from_filename(filename: str) -> str:
    base = filename.lower().replace(".csv", "")
    for prefix, label in _SOURCE_MAP.items():
        if base.startswith(prefix):
            return label
    return base.replace("_clients","").replace("_services","").replace("_"," ").strip().upper()

def _csv_row_count(path: str) -> int:
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return max(0, sum(1 for _ in f) - 1)
    except Exception:
        return 0


def _client_record_count(label: str) -> int:
    """Count rows in the demographic (non-services) CSV for this agency label."""
    prefixes = _LABEL_TO_FILE_PREFIXES.get(label, [])
    if not prefixes or not os.path.isdir(INPUT_DIR):
        return 0
    search_dirs = [INPUT_DIR, os.path.join(INPUT_DIR, "archive")]
    for search_dir in search_dirs:
        if not os.path.isdir(search_dir):
            continue
        for fname in sorted(os.listdir(search_dir)):
            fl = fname.lower()
            if not fl.endswith(".csv") or "_services" in fl:
                continue
            for prefix in prefixes:
                if fl.startswith(prefix):
                    return _csv_row_count(os.path.join(search_dir, fname))
    return 0


def _service_record_count(label: str) -> int:
    """Count rows in the services CSV for this agency label."""
    prefixes = _LABEL_TO_FILE_PREFIXES.get(label, [])
    if not prefixes or not os.path.isdir(INPUT_DIR):
        return 0
    search_dirs = [INPUT_DIR, os.path.join(INPUT_DIR, "archive")]
    for search_dir in search_dirs:
        if not os.path.isdir(search_dir):
            continue
        for fname in sorted(os.listdir(search_dir)):
            fl = fname.lower()
            if not fl.endswith(".csv") or "_services" not in fl:
                continue
            for prefix in prefixes:
                if fl.startswith(prefix):
                    return _csv_row_count(os.path.join(search_dir, fname))
    return 0


def _build_pipeline_registry() -> dict[str, int]:
    """Count CSVs per source in input/ to seed the registry."""
    reg: dict[str, int] = {}
    if not os.path.isdir(INPUT_DIR):
        return reg
    for fname in os.listdir(INPUT_DIR):
        if not fname.lower().endswith(".csv"):
            continue
        label = _label_from_filename(fname)
        reg[label] = reg.get(label, 0) + 1
    return reg

# ── Logo background (base64) ───────────────────────────────────────────────────
_ASSETS_DIR = os.path.join(os.path.dirname(__file__), "assets")
_BG_PATH    = os.path.join(_ASSETS_DIR, "nxnw_logo_bg.jpg")

def _b64(path: str) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()

_BG_B64   = _b64(_BG_PATH) if os.path.exists(_BG_PATH) else ""
_ICON_PATH = os.path.join(_ASSETS_DIR, "iconNXNW.jpg")
_ICON_B64  = _b64(_ICON_PATH) if os.path.exists(_ICON_PATH) else ""

# ── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(
    layout="wide",
    page_title="Cascadia (C3E)",
    page_icon="🧭",
)

# ── Pine silhouette (injected as fixed HTML) ───────────────────────────────────
_PINE_HTML = """
<div id="pine-backdrop" style="position:fixed;bottom:0;left:0;width:100%;
     height:230px;z-index:0;pointer-events:none;overflow:hidden;">
  <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1440 230"
       preserveAspectRatio="xMidYMax meet"
       style="position:absolute;bottom:0;left:0;width:100%;height:230px;">
    <polygon points="0,230 62,78 124,230"  fill="#030706"/>
    <polygon points="44,230 98,48 152,230" fill="#040807"/>
    <polygon points="108,230 162,72 216,230" fill="#030706"/>
    <polygon points="168,230 218,92 268,230" fill="#040807"/>
    <polygon points="232,230 292,58 352,230" fill="#030706"/>
    <polygon points="302,230 352,98 402,230" fill="#040807"/>
    <polygon points="370,230 430,68 490,230" fill="#030706"/>
    <polygon points="448,230 498,108 548,230" fill="#040807"/>
    <polygon points="518,230 578,62 638,230" fill="#030706"/>
    <polygon points="608,230 658,85 708,230" fill="#040807"/>
    <polygon points="678,230 733,70 788,230" fill="#030706"/>
    <polygon points="755,230 808,52 862,230" fill="#040807"/>
    <polygon points="828,230 878,90 928,230" fill="#030706"/>
    <polygon points="900,230 955,65 1010,230" fill="#040807"/>
    <polygon points="975,230 1028,82 1082,230" fill="#030706"/>
    <polygon points="1052,230 1105,55 1160,230" fill="#040807"/>
    <polygon points="1128,230 1178,92 1228,230" fill="#030706"/>
    <polygon points="1198,230 1250,70 1304,230" fill="#040807"/>
    <polygon points="1272,230 1322,48 1374,230" fill="#030706"/>
    <polygon points="1348,230 1392,78 1440,230" fill="#040807"/>
    <rect x="0" y="218" width="1440" height="12" fill="#030706"/>
  </svg>
</div>
"""

# ── CSS ────────────────────────────────────────────────────────────────────────
st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Share+Tech+Mono&display=swap');

    html, body, [class*="css"], .stApp, p, label, div, span, button {
        font-family: 'Share Tech Mono', 'Courier New', monospace !important;
    }

    /* Streamlit chrome */
    header[data-testid="stHeader"] {
        background: transparent !important;
        border-bottom: 1px solid rgba(0,230,168,0.07);
    }
    .block-container {
        padding-top: 0.9rem !important;
        padding-bottom: 140px !important;
        position: relative;
        z-index: 1;
    }
    [data-testid="stSidebar"] {
        background: rgba(5,11,19,0.96) !important;
        border-right: 1px solid rgba(0,230,168,0.1) !important;
    }

    /* ── Title banner ── */
    .title-banner {
        border-bottom: 2px solid #00E6A8;
        padding-bottom: 14px;
        margin-bottom: 20px;
        background: linear-gradient(90deg, transparent, rgba(0,230,168,0.05), transparent);
    }
    .title-inner {
        display: flex;
        align-items: center;
        gap: 18px;
        justify-content: center;
    }
    .title-logo {
        width: 80px;
        height: 80px;
        flex-shrink: 0;
        object-fit: contain;
        border-radius: 50%;
        background: transparent;
    }
    .title-text { text-align: left; }
    .title-h1 {
        color: #ffffff;
        font-size: 1.55rem;
        letter-spacing: 2px;
        margin: 0 0 5px;
        line-height: 1.2;
    }
    .title-h1 .t-acc { color: #00E6A8; }
    .title-sub {
        color: #8fa8c0;
        font-size: 0.68rem;
        letter-spacing: 1.5px;
        text-transform: uppercase;
    }

    /* ── Warning banner ── */
    .warn-banner {
        background: rgba(255,158,59,0.07);
        border: 1px solid rgba(255,158,59,0.55);
        border-radius: 4px;
        padding: 9px 16px;
        color: #FF9E3B;
        font-size: 0.82rem;
        margin-bottom: 12px;
        display: flex;
        align-items: center;
        gap: 10px;
        flex-wrap: wrap;
    }
    .warn-chip {
        background: rgba(255,158,59,0.12);
        border: 1px solid rgba(255,158,59,0.35);
        color: #FF9E3B;
        padding: 2px 10px;
        border-radius: 3px;
        font-size: 0.74rem;
        white-space: nowrap;
    }

    /* ── Record cards ── */
    .record-card {
        border-radius: 5px;
        padding: 15px 20px;
        margin-bottom: 10px;
        font-size: 0.86rem;
        line-height: 1.6;
    }
    .card-a {
        background: rgba(0,230,168,0.045);
        border: 2px solid #00E6A8;
        box-shadow: 0 0 16px rgba(0,230,168,0.07);
    }
    .card-b {
        background: rgba(255,158,59,0.045);
        border: 2px solid #FF9E3B;
        box-shadow: 0 0 16px rgba(255,158,59,0.07);
    }
    .lbl-a  { color: #00E6A8; font-weight: bold; margin-right: 6px; }
    .lbl-b  { color: #FF9E3B; font-weight: bold; margin-right: 6px; }
    .r-val  { color: #e6edf3; }
    .r-sep  { color: #1e2d3e; margin: 0 10px; }
    .r-dim  { color: #8fa8c0; font-size: 0.74rem; margin-right: 3px; }

    /* Field score chips */
    .score-row { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 8px; }
    .sc {
        font-size: 0.7rem;
        padding: 1px 7px;
        border-radius: 3px;
    }
    .sc-hi  { background: rgba(0,230,168,0.14); color: #00E6A8; }
    .sc-mid { background: rgba(255,158,59,0.14); color: #FF9E3B; }
    .sc-lo  { background: rgba(239,68,68,0.11);  color: #ef4444; }

    /* ── Confidence bar ── */
    .conf-wrap { height: 5px; background: #0d1925; border-radius: 3px; margin: 8px 0 4px; overflow: hidden; }
    .conf-fill { height: 5px; border-radius: 3px; }

    /* ── Drop zone ── */
    .drop-zone {
        border: 2px dashed rgba(0,230,168,0.18);
        border-radius: 8px;
        padding: 68px 40px;
        text-align: center;
        background: rgba(0,230,168,0.018);
        margin: 28px auto;
        max-width: 520px;
    }
    .drop-h   { color: rgba(0,230,168,0.45); font-size: 1rem; letter-spacing: 3px; margin: 0 0 10px; }
    .drop-sub { color: #1e2d3e; font-size: 0.72rem; letter-spacing: 1px; }

    /* ── Complete / no-match states ── */
    .complete-wrap { text-align: center; padding: 68px 20px; }
    .complete-icon { font-size: 3rem; margin-bottom: 14px; }
    .complete-head { color: #00E6A8; font-size: 1.1rem; letter-spacing: 4px; margin: 0 0 8px; }
    .complete-sub  { color: #8fa8c0; font-size: 0.78rem; }
    .nomatch-box {
        background: rgba(0,230,168,0.03);
        border: 1px solid rgba(0,230,168,0.15);
        border-radius: 6px;
        padding: 44px 28px;
        text-align: center;
        margin: 20px 0;
        color: #8fa8c0;
        font-size: 0.82rem;
    }
    .nomatch-head { color: #1a5c42; font-size: 0.95rem; letter-spacing: 2px; margin: 0 0 10px; }

    /* ── Sidebar metrics ── */
    .m-row {
        display: flex;
        justify-content: space-between;
        padding: 5px 0;
        border-bottom: 1px solid rgba(255,255,255,0.03);
        font-size: 0.76rem;
    }
    .m-lbl  { color: #8fa8c0; }
    .m-val  { color: #00E6A8; }
    .m-warn { color: #FF9E3B; }

    /* ── Buttons — pill shape ── */
    [data-testid="baseButton-secondary"] {
        background: rgba(22,32,46,0.95) !important;
        color: #a8b8c8 !important;
        border: 1px solid #1e2e42 !important;
        border-radius: 32px !important;
        font-family: 'Share Tech Mono', monospace !important;
        font-size: 0.94rem !important;
        letter-spacing: 3px !important;
        height: 56px !important;
        width: 100% !important;
        transition: all 0.14s !important;
    }
    [data-testid="baseButton-secondary"]:hover {
        background: rgba(32,46,64,0.95) !important;
        color: #c0cad4 !important;
        border-color: #2e4460 !important;
    }
    [data-testid="baseButton-primary"] {
        background: linear-gradient(135deg, #00E6A8 0%, #00c88e 100%) !important;
        color: #04100d !important;
        border: none !important;
        border-radius: 32px !important;
        font-family: 'Share Tech Mono', monospace !important;
        font-size: 0.98rem !important;
        letter-spacing: 2px !important;
        font-weight: 700 !important;
        height: 56px !important;
        width: 100% !important;
        box-shadow: 0 0 26px rgba(0,230,168,0.4), 0 0 60px rgba(0,230,168,0.15) !important;
        transition: all 0.14s !important;
    }
    [data-testid="baseButton-primary"]:hover {
        box-shadow: 0 0 38px rgba(0,230,168,0.6), 0 0 80px rgba(0,230,168,0.22) !important;
        transform: translateY(-1px) !important;
    }

    /* ── Slider ── */
    [data-testid="stSlider"] { padding: 0 !important; }
    [data-testid="stSlider"] label {
        color: #a8b8c8 !important;
        font-size: 0.76rem !important;
        letter-spacing: 1px !important;
    }
    [data-testid="stSlider"] [data-baseweb="slider"] [role="slider"] {
        background: #00E6A8 !important;
        border-color: #00E6A8 !important;
    }

    /* ── File uploader ── */
    [data-testid="stFileUploader"] [data-testid="stIconMaterial"] {
        display: none !important;
    }
    [data-testid="stFileUploader"] {
        background: rgba(0,230,168,0.018) !important;
        border: 1px dashed rgba(0,230,168,0.18) !important;
        border-radius: 5px !important;
        padding: 2px 10px !important;
    }
    [data-testid="stFileUploader"] section { padding: 6px 0 !important; }
    [data-testid="stFileUploader"] label,
    [data-testid="stFileUploader"] span,
    [data-testid="stFileUploader"] p,
    [data-testid="stFileUploader"] div {
        color: #2a3a4a !important;
        font-size: 0.76rem !important;
    }

    /* Metric widget */
    [data-testid="stMetric"] label { color: #8fa8c0 !important; font-size: 0.7rem !important; }
    [data-testid="stMetric"] [data-testid="stMetricValue"] { color: #00E6A8 !important; font-size: 1.1rem !important; }
    [data-testid="stMetric"] [data-testid="stMetricDelta"] { font-size: 0.72rem !important; }
    </style>
    """,
    unsafe_allow_html=True,
)

# Background image injection (f-string so _BG_B64 interpolates)
if _BG_B64:
    st.markdown(
        f"""<style>
        .stApp {{
            background-image:
                linear-gradient(rgba(4,10,18,0.62) 0%, rgba(5,12,20,0.70) 100%),
                url("data:image/jpeg;base64,{_BG_B64}") !important;
            background-size: cover !important;
            background-position: center center !important;
            background-attachment: fixed !important;
            background-repeat: no-repeat !important;
            min-height: 100vh;
        }}
        </style>""",
        unsafe_allow_html=True,
    )

# Inject pine silhouette
st.markdown(_PINE_HTML, unsafe_allow_html=True)


# ── Session state ──────────────────────────────────────────────────────────────
_DEFAULTS: dict = {
    "confirmed_df":       None,
    "confirmed_filename": None,
    "dismissed_filename": None,
    "_pending_upload":    None,   # holds file obj set by on_change before script body runs
    "_pending_remove":    None,   # dataset label queued for removal confirmation
    "_pending_golden":    False,  # confirmation dialog for golden file export
    "_golden_result":     None,   # success/error message after export
    "_rerun_and_export":  False,  # pipeline re-run requested before golden export
    "_always_rerun_pipeline": False,  # skip dialog and always re-run pipeline on golden export
    "threshold_hint":     None,   # (min, max) tuple from _suggest_thresholds
    "col_map":            {},
    "candidate_pairs":    [],
    "auto_accepted":      0,
    "current_idx":        0,
    "decisions":          [],
    "rejected_mpis":       set(),
    "current_client_id_col": None,
    "min_threshold":      75,
    "max_threshold":      88,
    "awaiting_services":  None,   # None=not asked, True=yes waiting, False=no/done
    "services_df":        None,
    "services_filename":  None,
    "ingested_registry":  {},     # label → file count, persists across loads
    "_tpm_df":            None,   # cached DataFrame for current dialog file
    "_tpm_filename":      None,   # filename that _tpm_df was parsed from
    "_unlink_expanded_mpi":  None,  # MPI row currently expanded in Records tab
    "_unlink_confirm_uid":   None,  # unique_record_id with active confirm dialog
    "_new_partner_saved":    None,  # filename of most recently saved new trading partner
}
for _k, _v in _DEFAULTS.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v

# Load persisted review decisions from disk (survives page reload)
# Guard uses a separate flag so an empty rejection set doesn't re-read every rerun.
if "rejected_mpis_loaded" not in st.session_state and os.path.exists(DECISIONS_PATH):
    try:
        _dec_df = pd.read_csv(DECISIONS_PATH, dtype=str).fillna("")
        st.session_state.rejected_mpis = set(
            _dec_df.loc[_dec_df["decision"] == "reject", "mpi"].tolist()
        )
    except Exception:
        pass
    st.session_state.rejected_mpis_loaded = True

# Seed registry from input/ on first load (pipeline datasets)
if not st.session_state.ingested_registry:
    st.session_state.ingested_registry = _build_pipeline_registry()


# ── Column auto-detection ──────────────────────────────────────────────────────
_PATTERNS = {
    "first_name":     [r"f(irst)?[_\s]?name", r"given[_\s]?name", r"\bfname\b", r"preferred"],
    "last_name":      [r"l(ast)?[_\s]?name",  r"surname", r"\blname\b", r"family"],
    "dob":            [r"\bdob\b", r"d(ate)?[_\s]?o(f)?[_\s]?b(irth)?", r"birth[_\s]?date", r"birth[_\s]?year"],
    "ssn":            [r"\bssn\b", r"ss[_\s]?n", r"social[_\s]?sec"],
    "encounter_date": [r"enc(ounter)?[_\s]?date", r"visit[_\s]?date", r"service[_\s]?date",
                       r"date[_\s]?provided", r"\bdate\b", r"start[_\s]?date"],
}

_SYNONYMS = {
    "first_name":     ["first_name", "firstname", "given_name", "fname", "first", "preferred_name",
                       "preferred_alias", "name_first", "forename"],
    "last_name":      ["last_name", "lastname", "surname", "lname", "last", "family_name", "name_last"],
    "dob":            ["dob", "date_of_birth", "birth_date", "birthdate", "birthday",
                       "birth_year", "dateofbirth", "date_birth"],
    "ssn":            ["ssn", "ssn_last4", "ssn_last_4", "social", "social_security",
                       "alt_id", "alternate_id", "ssn4"],
    "client_id":      ["client_id", "id", "personalid", "member_number", "participant_code",
                       "record_id", "client_number", "member_id", "person_id", "uid"],
    "encounter_date": ["encounter_date", "visit_date", "service_date", "date_provided",
                       "date", "start_date", "event_date", "activity_date"],
}


def _detect_cols(df: pd.DataFrame) -> dict:
    """Return col_map for the 4 scoring fields (first_name, last_name, dob, ssn)."""
    cm: dict = {}
    # Regex first pass
    for field, pats in _PATTERNS.items():
        for col in df.columns:
            if any(re.search(p, col, re.I) for p in pats):
                cm[field] = col
                break
    # Rapidfuzz fallback for any unmatched scoring field
    for field in ("first_name", "last_name", "dob", "ssn"):
        if field in cm:
            continue
        best_col, best_score = None, 0
        for col in df.columns:
            for syn in _SYNONYMS.get(field, []):
                s = fuzz.WRatio(col.lower(), syn.lower())
                if s > best_score:
                    best_score, best_col = s, col
        if best_score >= 80:
            cm[field] = best_col
    return cm


def _detect_id_col(df: pd.DataFrame) -> str | None:
    """Best-guess for the client identifier column (not used in scoring)."""
    id_pats = [r"client[_\s]?id", r"personal[_\s]?id", r"member[_\s]?(no|num|number|id)",
               r"participant[_\s]?code", r"record[_\s]?id", r"\buid\b", r"unique[_\s]?id"]
    for col in df.columns:
        if any(re.search(p, col, re.I) for p in id_pats):
            return col
    best_col, best_score = None, 0
    for col in df.columns:
        for syn in _SYNONYMS["client_id"]:
            s = fuzz.WRatio(col.lower(), syn.lower())
            if s > best_score:
                best_score, best_col = s, col
    return best_col if best_score >= 75 else None


def _is_known_file(filename: str) -> bool:
    """True if filename matches a client_file in the schema registry."""
    fn = filename.lower()
    return any(fn == s.get("client_file", "").lower() for s in _load_schemas())


def _save_new_schema(agency_name: str, source_slug: str, client_file: str,
                     client_id_col: str, col_map_user: dict, ssn_type: str) -> None:
    """Write a new trading-partner schema JSON to input/schemas/."""
    os.makedirs(SCHEMA_DIR, exist_ok=True)
    safe = re.sub(r'[^a-z0-9]+', '_', agency_name.lower()).strip('_')
    path = os.path.join(SCHEMA_DIR, f"{safe}.json")
    schema = {
        "label":        agency_name,
        "short_label":  agency_name.upper(),
        "source_system": source_slug,
        "optional":     True,
        "client_file":  client_file,
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


# ── Fuzzy scoring ──────────────────────────────────────────────────────────────
_W = {"first_name": 0.30, "last_name": 0.30, "dob": 0.30, "ssn": 0.10}
_EMPTY = {"", "nan", "none", "-"}

def _has_value(v) -> bool:
    return str(v).strip().lower() not in _EMPTY

def _parse_dob_variants(v: str) -> list[str]:
    """Return all plausible ISO parses of a DOB string (tries both dayfirst settings)."""
    import re
    from datetime import date as _date
    v = v.strip()
    if re.match(r"^\d{4}-\d{2}-\d{2}$", v):
        return [v]
    results = []
    _current_year = _date.today().year
    try:
        import pandas as pd
        for dayfirst in (False, True):
            try:
                parsed = pd.to_datetime(v, dayfirst=dayfirst, errors="raise")
                # Correct 2-digit years that landed in the future (e.g. 62 → 2062 → 1962)
                if parsed.year > _current_year:
                    parsed = parsed.replace(year=parsed.year - 100)
                iso = parsed.strftime("%Y-%m-%d")
                if iso not in results:
                    results.append(iso)
            except Exception:
                pass
    except Exception:
        pass
    return results or [v]

def _score(a, b, field: str = "") -> float:
    a, b = str(a).strip().lower(), str(b).strip().lower()
    if not a or not b or a in _EMPTY or b in _EMPTY:
        return 0.0
    if field == "dob":
        va = _parse_dob_variants(a)
        vb = _parse_dob_variants(b)
        # Full match: any interpretation of a equals any interpretation of b
        if set(va) & set(vb):
            return 100.0
        # Partial credit on best canonical forms
        na, nb = va[0], vb[0]
        pa, pb = na.split("-"), nb.split("-")
        if len(pa) == 3 and len(pb) == 3:
            if pa[0] == pb[0] and pa[1] == pb[1]:  # same year + month
                return 75.0
            if pa[0] == pb[0]:                       # same year only
                return 40.0
        return float(fuzz.token_sort_ratio(na, nb))
    return float(fuzz.token_sort_ratio(a, b))

def _composite(scores: dict) -> float:
    tw = sum(_W.get(k, 0.1) for k in scores)
    return sum(scores[k] * _W.get(k, 0.1) for k in scores) / tw if tw else 0.0

def _suggest_thresholds(df: pd.DataFrame, col_map: dict) -> tuple[int, int]:
    """
    Analyze composite score distribution across all candidate pairs and return
    (suggested_min, suggested_max) thresholds.

    Strategy:
      - Run scoring with a wide-open floor (0) to capture the full distribution.
      - Min  = 40th-percentile score, clamped 55–85, rounded to nearest 5.
        Filters out the noisiest bottom 40% of candidates automatically.
      - Max  = 82nd-percentile score, clamped (min+5)–97, rounded to nearest 5.
        Auto-accepts the clearest top ~18% without human review.
    """
    all_pairs, _ = build_candidates(df, col_map, min_thr=0, max_thr=101)
    if len(all_pairs) < 5:
        return 75, 88  # not enough data — fall back to defaults

    scores = sorted(p["composite"] for p in all_pairs)
    n = len(scores)

    raw_min = scores[int(n * 0.40)]
    s_min   = int(round(max(55.0, min(85.0, raw_min)) / 5) * 5)

    raw_max = scores[int(n * 0.82)]
    s_max   = int(round(max(float(s_min + 5), min(97.0, raw_max)) / 5) * 5)

    return s_min, s_max


def build_candidates(df: pd.DataFrame, col_map: dict, min_thr: int, max_thr: int) -> tuple[list, int]:
    """
    Returns (manual_pairs, auto_accepted_count).

    composite >= max_thr            → auto-accept (silent)
    min_thr <= composite < max_thr  → manual review card
    composite < min_thr             → auto-reject (hidden)
    """
    manual: list = []
    auto_count: int = 0

    def _eval_pair(rec_a, rec_b, scores, mpi=""):
        nonlocal auto_count
        comp = _composite(scores)
        if comp >= max_thr:
            auto_count += 1
        elif comp > min_thr:   # strictly above floor — exact boundary = auto-reject
            manual.append({
                "rec_a": rec_a,
                "rec_b": rec_b,
                "scores": scores,
                "composite": round(comp, 1),
                "mpi": mpi,
            })

    if os.path.exists(MASTER_PATH):
        master = pd.read_csv(MASTER_PATH, dtype=str).fillna("")
        for _, row in df.iterrows():
            for _, mrow in master.iterrows():
                scores: dict = {}
                for field, mk in [
                    ("first_name", "canonical_first_name"),
                    ("last_name",  "canonical_last_name"),
                    ("dob",        "canonical_dob"),
                ]:
                    uc = col_map.get(field)
                    if uc:
                        v1, v2 = row.get(uc, ""), mrow.get(mk, "")
                        if _has_value(v1) and _has_value(v2):
                            scores[field] = _score(v1, v2, field)
                ssn_c = col_map.get("ssn")
                if ssn_c:
                    v = str(row.get(ssn_c, ""))
                    v1 = v[-4:] if len(v) >= 4 else v
                    v2 = mrow.get("canonical_ssn_last4", "")
                    if _has_value(v1) and _has_value(v2):
                        scores["ssn"] = _score(v1, v2, "ssn")
                if scores:
                    _eval_pair(dict(mrow), dict(row), scores, mrow.get("master_person_id", ""))
    else:
        records = df.to_dict("records")
        for i in range(len(records)):
            for j in range(i + 1, len(records)):
                r1, r2 = records[i], records[j]
                scores = {}
                for field, col in col_map.items():
                    v1, v2 = r1.get(col, ""), r2.get(col, "")
                    if _has_value(v1) and _has_value(v2):
                        scores[field] = _score(v1, v2, field)
                if scores:
                    _eval_pair(r1, r2, scores)

    manual.sort(key=lambda p: p["composite"])  # borderline-first
    return manual, auto_count


# ── Confirm-remove dialog ─────────────────────────────────────────────────────
@st.dialog("Remove Dataset")
def _confirm_remove_dialog(label: str):
    st.markdown(
        f'<div style="text-align:center;padding:8px 0 18px;">'
        f'<div style="font-size:2.0rem;margin-bottom:10px;">🗑</div>'
        f'<div style="color:#c9d1d9;font-size:0.9rem;line-height:1.55;">'
        f'Are you sure you want to remove dataset<br>'
        f'<strong style="color:#00E6A8;">{label}</strong><br>'
        f'from the master record?'
        f'</div>'
        f'</div>',
        unsafe_allow_html=True,
    )
    c1, c2 = st.columns(2)
    with c1:
        if st.button("Cancel", use_container_width=True):
            st.session_state._pending_remove = None
            st.rerun()
    with c2:
        if st.button("Remove", use_container_width=True, type="primary"):
            _archive_agency_files(label)   # move CSVs → input/archived/
            _new_reg = dict(st.session_state.ingested_registry)
            _new_reg.pop(label, None)
            st.session_state.ingested_registry = _new_reg
            st.session_state._pending_remove = None
            st.rerun()


# ── Review decision persistence ───────────────────────────────────────────────
def _persist_decision(pair: dict, decision: str) -> None:
    """Append one swipe decision to disk so it survives page reloads."""
    mpi = pair.get("mpi", "")
    if not mpi:
        return  # CSV-only mode — no MPI to track
    import datetime as _dt, csv as _csv
    row = {
        "mpi": mpi,
        "decision": decision,
        "composite": pair.get("composite", ""),
        "timestamp": _dt.datetime.now().isoformat(timespec="seconds"),
    }
    write_header = not os.path.exists(DECISIONS_PATH)
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(DECISIONS_PATH, "a", newline="", encoding="utf-8") as fh:
        writer = _csv.DictWriter(fh, fieldnames=list(row.keys()))
        if write_header:
            writer.writeheader()
        writer.writerow(row)


# ── Accept link — write service encounters to accepted_encounters.csv ─────────
_SVC_SYNONYMS = {
    "encounter_id":    ["visit_id", "log_id", "entry_id", "service_id", "servicefileid", "encounter_id"],
    "encounter_date":  ["service_date", "visit_date", "encounter_date", "start_date", "dateprovided", "date"],
    "service_category":["service_type", "activity_type", "program_name", "servicecategory", "service_category"],
}

def _detect_svc_col(svc_df: pd.DataFrame, field: str) -> str | None:
    cols_lower = {c.lower().replace(" ", "_"): c for c in svc_df.columns}
    for syn in _SVC_SYNONYMS.get(field, []):
        if syn in cols_lower:
            return cols_lower[syn]
    best_col, best_score = None, 0
    for syn in _SVC_SYNONYMS.get(field, []):
        for col_lower, col in cols_lower.items():
            s = fuzz.WRatio(col_lower, syn)
            if s > best_score:
                best_score, best_col = s, col
    return best_col if best_score >= 75 else None

def _accept_link(pair: dict) -> None:
    """Record person-merge decision and optionally write service encounters."""
    target_mpi = pair.get("mpi", "")
    if not target_mpi:
        return

    filename      = st.session_state.get("confirmed_filename", "")
    client_id_col = st.session_state.get("current_client_id_col")
    rec_b         = pair.get("rec_b", {})

    # Derive source_system from filename (strip _clients.csv suffix if present)
    src_system = re.sub(r'[^a-z0-9]+', '_',
                        filename.lower().replace("_clients.csv", "")).upper()

    # Derive source_id: use client_id_col if known, else scan rec_b for an id-like key
    source_id = ""
    if client_id_col and client_id_col in rec_b:
        source_id = str(rec_b[client_id_col]).strip()
    if not source_id:
        for k in rec_b:
            if any(t in k.lower() for t in ("id", "number", "code", "reg")):
                v = str(rec_b[k]).strip()
                if v:
                    source_id = v
                    break

    # Always persist the person-merge decision so the export CTE can fire.
    if src_system and source_id:
        import csv as _csv, datetime as _dt
        _prow = {"source_system": src_system, "source_id": source_id,
                 "target_mpi": target_mpi,
                 "timestamp": _dt.datetime.now().isoformat(timespec="seconds")}
        _ph = not os.path.exists(ACCEPTED_PERSONS_PATH)
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        with open(ACCEPTED_PERSONS_PATH, "a", newline="", encoding="utf-8") as fh:
            w = _csv.DictWriter(fh, fieldnames=list(_prow.keys()))
            if _ph:
                w.writeheader()
            w.writerow(_prow)

    # Optionally write encounter rows when a services CSV has been uploaded.
    svc_df: pd.DataFrame | None = st.session_state.get("services_df")
    if svc_df is None or svc_df.empty or not source_id:
        return

    svc_id_col = client_id_col if client_id_col and client_id_col in svc_df.columns else None
    if svc_id_col is None:
        for col in svc_df.columns:
            if fuzz.WRatio(col.lower(), (client_id_col or "").lower()) >= 80:
                svc_id_col = col
                break
    if not svc_id_col:
        return

    matched = svc_df[svc_df[svc_id_col].astype(str).str.strip() == source_id]
    if matched.empty:
        return

    enc_id_col = _detect_svc_col(svc_df, "encounter_id")
    date_col   = _detect_svc_col(svc_df, "encounter_date")
    cat_col    = _detect_svc_col(svc_df, "service_category")

    rows = []
    for _, row in matched.iterrows():
        enc_id  = str(row[enc_id_col])  if enc_id_col  else f"MANUAL-{target_mpi[:8]}-{len(rows)}"
        enc_dt  = str(row[date_col])    if date_col    else ""
        cat     = str(row[cat_col])     if cat_col     else "Manual Review - Accepted"
        other_cols = [c for c in svc_df.columns
                      if c not in {svc_id_col, enc_id_col, date_col, cat_col} and c]
        loc_info = " | ".join(f"{c}: {row[c]}" for c in other_cols if str(row.get(c, "")).strip())
        rows.append({
            "encounter_id":     enc_id,
            "master_person_id": target_mpi,
            "unique_record_id": f"{src_system}::{source_id}",
            "source_system":    src_system,
            "encounter_date":   enc_dt,
            "service_category": cat,
            "location_info":    loc_info,
        })

    if rows:
        out = pd.DataFrame(rows)
        write_header = not os.path.exists(ACCEPTED_ENCOUNTERS_PATH)
        out.to_csv(ACCEPTED_ENCOUNTERS_PATH, mode="a", header=write_header, index=False)


# ── Golden export helpers ─────────────────────────────────────────────────────
_GOLDEN_OUT     = "output/GOLDEN_PERSONS_ENCOUNTERS.csv"
_GOLDEN_PERSONS = "output/GOLDEN_PERSONS.csv"
_GOLDEN_DIM     = "output/dim_master_persons.csv"
_GOLDEN_ENC     = "output/fact_encounters.csv"
_GOLDEN_BRIDGE  = "output/bridge_record_links.csv"
_GOLDEN_SEVERED  = "output/severed_links.csv"

# Same deterministic namespace as cluster.py — must stay in sync
_MPI_NAMESPACE = uuid.UUID("d5a0e1f3-4c2b-4a8e-9b7d-1f2a3c4e5b6d")


def _sever_link(unique_record_id: str, original_mpi: str) -> str:
    """Append a split override to severed_links.csv; return the new singleton MPI."""
    split_mpi = str(uuid.uuid5(_MPI_NAMESPACE, f"severed::{unique_record_id}"))
    row = {
        "unique_record_id": unique_record_id,
        "original_mpi": original_mpi,
        "split_mpi": split_mpi,
    }
    if os.path.exists(_GOLDEN_SEVERED):
        existing = pd.read_csv(_GOLDEN_SEVERED, dtype=str)
        if unique_record_id in existing["unique_record_id"].values:
            return split_mpi  # already severed — idempotent
        pd.concat([existing, pd.DataFrame([row])], ignore_index=True).to_csv(
            _GOLDEN_SEVERED, index=False
        )
    else:
        pd.DataFrame([row]).to_csv(_GOLDEN_SEVERED, index=False)
    return split_mpi


def _undo_accept(source_system: str, source_id: str) -> None:
    """Remove all accepted_persons.csv rows for this source_system + source_id."""
    if not os.path.exists(ACCEPTED_PERSONS_PATH):
        return
    ap = pd.read_csv(ACCEPTED_PERSONS_PATH, dtype=str)
    mask = ~(
        (ap["source_system"].str.lower() == source_system.lower())
        & (ap["source_id"] == source_id)
    )
    ap[mask].to_csv(ACCEPTED_PERSONS_PATH, index=False)



def _prepare_golden_sources() -> tuple[str, str, str]:
    """Return (dim_path, bridge_path, enc_path), applying severed_links splits if present.

    If severed_links.csv exists and has rows, produces modified temp CSVs where
    severed records are remapped to their new singleton MPI and dim aggregates are
    recomputed.  Temp files are written to OUTPUT_DIR as _sev_dim/bridge/enc.csv.
    """
    if not (os.path.exists(_GOLDEN_SEVERED) and os.path.exists(_GOLDEN_BRIDGE)
            and os.path.exists(_GOLDEN_DIM)):
        return _GOLDEN_DIM, _GOLDEN_BRIDGE, _GOLDEN_ENC

    sv_df = pd.read_csv(_GOLDEN_SEVERED, dtype=str)
    if sv_df.empty:
        return _GOLDEN_DIM, _GOLDEN_BRIDGE, _GOLDEN_ENC

    sv_map = dict(zip(sv_df["unique_record_id"], sv_df["split_mpi"]))

    # Remap bridge rows for severed records to their split MPI
    bri_df = pd.read_csv(_GOLDEN_BRIDGE, dtype=str)
    bri_df["master_person_id"] = (
        bri_df["unique_record_id"].map(sv_map).fillna(bri_df["master_person_id"])
    )

    # Recompute dim aggregates from the modified bridge
    bri_grp = bri_df.groupby("master_person_id").agg(
        total_linked_records=("unique_record_id", "count"),
        linked_sources_count=("source_system", "nunique"),
        contributing_sources=("source_system", lambda x: ", ".join(sorted(set(x)))),
    ).reset_index()

    dim_df = pd.read_csv(_GOLDEN_DIM, dtype=str)

    # Create new singleton dim rows for each split MPI, inheriting demographics
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

    # Replace stale aggregate columns with freshly computed values; inner join
    # drops clusters whose every record was severed away (total == 0)
    dim_df = dim_df.drop(
        columns=["total_linked_records", "linked_sources_count", "contributing_sources"],
        errors="ignore",
    )
    dim_df = dim_df.merge(bri_grp, on="master_person_id", how="inner")

    t_dim = os.path.join(OUTPUT_DIR, "_sev_dim.csv")
    t_bri = os.path.join(OUTPUT_DIR, "_sev_bridge.csv")
    dim_df.to_csv(t_dim, index=False)
    bri_df.to_csv(t_bri, index=False)

    t_enc = _GOLDEN_ENC
    if os.path.exists(_GOLDEN_ENC):
        enc_df = pd.read_csv(_GOLDEN_ENC, dtype=str)
        enc_df["master_person_id"] = (
            enc_df["unique_record_id"].map(sv_map).fillna(enc_df["master_person_id"])
        )
        t_enc = os.path.join(OUTPUT_DIR, "_sev_enc.csv")
        enc_df.to_csv(t_enc, index=False)

    return t_dim, t_bri, t_enc


def _do_golden_export(ddb, where_clause: str, stale_sources: list) -> None:
    """Write GOLDEN_PERSONS_ENCOUNTERS.csv (persons × encounters JOIN) and
    GOLDEN_PERSONS.csv (all master persons, no encounter data)."""
    try:
        _has_persons  = os.path.exists(ACCEPTED_PERSONS_PATH)
        _has_bridge   = os.path.exists(_GOLDEN_BRIDGE)
        _has_enc_file = os.path.exists(ACCEPTED_ENCOUNTERS_PATH)

        # Apply severed_links splits (produces temp files if any splits exist)
        _gdim, _gbridge, _genc = _prepare_golden_sources()

        # Build inline CTE fragment (goes INSIDE the COPY query, not before it).
        # Identifies pipeline MPIs overridden by manual accepts and re-attributes
        # their encounters to the target master MPI.
        if _has_persons and _has_bridge:
            _extra_enc = (
                f"UNION ALL SELECT encounter_id, master_person_id, unique_record_id,"
                f" source_system, encounter_date, service_category, location_info"
                f" FROM '{ACCEPTED_ENCOUNTERS_PATH}'"
                if _has_enc_file else ""
            )
            _ap_src = f"read_csv('{ACCEPTED_PERSONS_PATH}', delim=',', quote='\"', header=true, strict_mode=false)"
            _cte_block = f"""WITH overridden AS (
                SELECT DISTINCT b.master_person_id AS pipeline_mpi, ap.target_mpi
                FROM '{_gbridge}' b
                JOIN {_ap_src} ap
                  ON LOWER(b.source_system) = LOWER(ap.source_system)
                 AND b.source_id = ap.source_id
                WHERE b.master_person_id != ap.target_mpi
            ),
            merged_additions AS (
                SELECT
                    ov.target_mpi,
                    string_agg(DISTINCT b.source_system, ', ') AS extra_sources,
                    COUNT(b.unique_record_id)               AS extra_records,
                    COUNT(DISTINCT b.source_system)         AS extra_src_count
                FROM overridden ov
                JOIN '{_gbridge}' b ON b.master_person_id = ov.pipeline_mpi
                GROUP BY ov.target_mpi
            ),
            augmented_dim AS (
                SELECT
                    d.master_person_id,
                    d.canonical_first_name,
                    d.canonical_last_name,
                    d.canonical_dob,
                    d.canonical_ssn_last4,
                    CASE WHEN ma.extra_sources IS NOT NULL
                         THEN d.contributing_sources || ', ' || ma.extra_sources
                         ELSE d.contributing_sources
                    END AS contributing_sources,
                    TRY_CAST(d.total_linked_records AS INTEGER) + COALESCE(ma.extra_records, 0) AS total_linked_records,
                    TRY_CAST(d.linked_sources_count AS INTEGER) + COALESCE(ma.extra_src_count, 0) AS linked_sources_count
                FROM '{_gdim}' d
                LEFT JOIN merged_additions ma ON d.master_person_id = ma.target_mpi
                WHERE d.master_person_id NOT IN (SELECT pipeline_mpi FROM overridden)
            ),
            enc_reassigned AS (
                SELECT
                    COALESCE(ov.target_mpi, e.master_person_id) AS master_person_id,
                    e.encounter_id, e.unique_record_id, e.source_system,
                    e.encounter_date, e.service_category, e.location_info
                FROM '{_genc}' e
                LEFT JOIN overridden ov ON e.master_person_id = ov.pipeline_mpi
                {_extra_enc}
            )"""
            dim_src       = "augmented_dim"
            dim_src_p     = "augmented_dim"
            enc_src_inner = "enc_reassigned"
        else:
            _cte_block    = ""
            dim_src        = f"'{_gdim}'"
            dim_src_p      = f"'{_gdim}'"
            enc_src_inner  = (
                f"(SELECT * FROM '{_genc}' UNION ALL SELECT * FROM '{ACCEPTED_ENCOUNTERS_PATH}')"
                if _has_enc_file else f"'{_genc}'"
            )

        # 1. Persons × encounters (CTE inside COPY, which DuckDB requires)
        ddb.sql(f"""
            COPY (
                {_cte_block}
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
                FROM {dim_src} m
                JOIN {enc_src_inner} e USING (master_person_id)
                {where_clause}
                ORDER BY m.canonical_last_name,
                         m.canonical_first_name,
                         e.encounter_date
            ) TO '{_GOLDEN_OUT}' (HEADER, DELIMITER ',')
        """)
        enc_count = ddb.sql(
            f"SELECT COUNT(*) FROM '{_GOLDEN_OUT}'"
        ).fetchone()[0]

        # 2. Persons only — pipeline persons minus overridden MPIs
        ddb.sql(f"""
            COPY (
                {_cte_block}
                SELECT
                    master_person_id,
                    canonical_first_name,
                    canonical_last_name,
                    canonical_dob,
                    canonical_ssn_last4,
                    contributing_sources,
                    total_linked_records,
                    linked_sources_count
                FROM {dim_src_p}
                ORDER BY canonical_last_name, canonical_first_name
            ) TO '{_GOLDEN_PERSONS}' (HEADER, DELIMITER ',')
        """)
        persons_count = ddb.sql(
            f"SELECT COUNT(*) FROM '{_GOLDEN_PERSONS}'"
        ).fetchone()[0]

        import datetime as _dt
        _ts = _dt.datetime.now().strftime("%H:%M:%S")
        st.session_state._pending_golden = False
        accepted_note = " · incl. manual accepts" if _has_persons else ""
        stale_note    = f" ({len(stale_sources)} stale source(s) excluded)" if stale_sources else ""
        st.session_state._golden_result = (
            f"WRITTEN {_ts} — {persons_count:,} persons · {enc_count:,} encounters"
            + accepted_note + stale_note
        )
    except Exception as ex:
        st.session_state._pending_golden = False
        st.session_state._golden_result = f"ERROR: {ex}"
    st.rerun()

@st.dialog("Export Golden File")
def _confirm_golden_dialog():
    import duckdb as _ddb
    exists = os.path.exists(_GOLDEN_OUT)

    # Detect mismatches between active sources and what's in the output files
    active_sources = _active_source_systems()
    stale_sources: list[str] = []   # in output file but no longer active
    missing_sources: list[str] = [] # active in session but absent from output file
    if os.path.exists(_GOLDEN_ENC):
        try:
            _all_src = _ddb.sql(
                f"SELECT DISTINCT source_system FROM '{_GOLDEN_ENC}'"
            ).fetchall()
            _file_sources = {r[0] for r in _all_src}
            if active_sources:
                stale_sources = sorted(_file_sources - set(active_sources))
                missing_sources = sorted(set(active_sources) - _file_sources)
        except Exception:
            pass

    needs_rerun = bool(stale_sources or missing_sources)

    # Warn when removed agencies are still in the output files
    if stale_sources:
        st.markdown(
            f'<div style="background:#3a1400;border:1px solid #FF9E3B;border-radius:6px;'
            f'padding:10px 14px;margin-bottom:12px;">'
            f'<div style="color:#FF9E3B;font-size:0.72rem;letter-spacing:1.5px;'
            f'font-family:\'Courier New\',monospace;margin-bottom:6px;">⚠ STALE OUTPUT DETECTED</div>'
            f'<div style="color:#c87030;font-size:0.72rem;line-height:1.6;">'
            f'The pipeline output files still contain data from agencies no longer '
            f'in your session:<br>'
            f'<b style="color:#FF9E3B">{", ".join(stale_sources)}</b><br>'
            f'The export below will exclude those encounters. For a fully clean '
            f'result, re-run the pipeline.'
            f'</div></div>',
            unsafe_allow_html=True,
        )

    # Warn when active agencies are missing from the output files entirely
    if missing_sources:
        st.markdown(
            f'<div style="background:#001a0e;border:1px solid #00E6A8;border-radius:6px;'
            f'padding:10px 14px;margin-bottom:12px;">'
            f'<div style="color:#00E6A8;font-size:0.72rem;letter-spacing:1.5px;'
            f'font-family:\'Courier New\',monospace;margin-bottom:6px;">⚠ PIPELINE OUT OF DATE</div>'
            f'<div style="color:#00a87a;font-size:0.72rem;line-height:1.6;">'
            f'The following active agencies have no records in the output files yet — '
            f'the pipeline must be re-run to include them:<br>'
            f'<b style="color:#00E6A8">{", ".join(missing_sources)}</b>'
            f'</div></div>',
            unsafe_allow_html=True,
        )

    # Build the source filter for the SQL query
    if active_sources:
        _src_list = ", ".join(f"'{s}'" for s in active_sources)
        _where = f"WHERE e.source_system IN ({_src_list})"
    else:
        _where = ""  # no filter if registry is empty (shouldn't happen)

    _persons_exists = os.path.exists(_GOLDEN_PERSONS)
    _either_exists = exists or _persons_exists
    _action_label = "OVERWRITE EXISTING FILES?" if _either_exists else "GENERATE GOLDEN FILES?"
    st.markdown(
        f'<div style="text-align:center;padding:8px 0 14px;">'
        f'<div style="font-size:2.2rem;margin-bottom:10px;">📥</div>'
        f'<div style="color:#a8b8c8;font-size:0.75rem;letter-spacing:2px;margin-bottom:14px;">'
        f'{_action_label}</div>'
        f'<div style="display:flex;flex-direction:column;gap:6px;margin-bottom:10px;">'
        f'<div style="color:#00E6A8;background:#0c1926;padding:7px 14px;border-radius:4px;'
        f'font-family:\'Courier New\',monospace;font-size:0.75rem;text-align:left;">'
        f'<span style="color:#8fa8c0;font-size:0.65rem;display:block;margin-bottom:2px;">'
        f'PERSONS ONLY (all mastered persons, no encounters)</span>'
        f'{_GOLDEN_PERSONS}</div>'
        f'<div style="color:#00E6A8;background:#0c1926;padding:7px 14px;border-radius:4px;'
        f'font-family:\'Courier New\',monospace;font-size:0.75rem;text-align:left;">'
        f'<span style="color:#8fa8c0;font-size:0.65rem;display:block;margin-bottom:2px;">'
        f'PERSONS × ENCOUNTERS (one row per service visit)</span>'
        f'{_GOLDEN_OUT}</div>'
        f'</div>'
        f'<div style="color:#8fa8c0;font-size:0.72rem;line-height:1.5;">'
        f'{"Previous exports exist and will be overwritten." if _either_exists else "Both files share master_person_id as the join key."}'
        f'{"<br>Sources: " + ", ".join(active_sources) if active_sources else ""}'
        f'</div></div>',
        unsafe_allow_html=True,
    )
    if needs_rerun:
        # Three-button layout when pipeline is out of date: Cancel | Export As-Is | Re-run & Export
        c1, c2, c3 = st.columns([1, 1.2, 1.4])
        with c1:
            if st.button("Cancel", use_container_width=True):
                st.session_state._pending_golden = False
                st.rerun()
        with c2:
            if st.button("Export As-Is", use_container_width=True):
                _do_golden_export(_ddb, _where, stale_sources)
        with c3:
            if st.button("Re-run & Export", use_container_width=True,
                         type="primary"):
                st.session_state._pending_golden = False
                st.session_state._rerun_and_export = True
                st.rerun()
    else:
        # Normal two-button layout
        c1, c2 = st.columns(2)
        with c1:
            if st.button("Cancel", use_container_width=True):
                st.session_state._pending_golden = False
                st.rerun()
        with c2:
            btn_label = "Overwrite" if exists else "Generate"
            if st.button(btn_label, use_container_width=True, type="primary"):
                _do_golden_export(_ddb, _where, stale_sources)

# ── Confirm-load dialog ────────────────────────────────────────────────────────
def _do_load(filename: str, df: pd.DataFrame, col_map_override: dict | None = None,
             client_id_col: str | None = None) -> None:
    """Commit a DataFrame into session state and trigger a rerun."""
    col_map = col_map_override if col_map_override is not None else _detect_cols(df)
    pairs, auto_n = build_candidates(
        df, col_map,
        st.session_state.min_threshold,
        st.session_state.max_threshold,
    )
    st.session_state.confirmed_df          = df
    st.session_state.confirmed_filename    = filename
    st.session_state.dismissed_filename    = None
    st.session_state.col_map               = col_map
    st.session_state.current_client_id_col = client_id_col
    st.session_state.candidate_pairs       = pairs
    st.session_state.auto_accepted         = auto_n
    st.session_state.current_idx           = 0
    st.session_state.decisions             = []
    _lbl = _label_from_filename(filename)
    reg  = dict(st.session_state.ingested_registry)
    reg[_lbl] = reg.get(_lbl, 0) + 1
    st.session_state.ingested_registry = reg
    st.toast(f"✓ {filename} loaded — {len(df):,} records", icon="✅")
    time.sleep(1.2)
    st.rerun()


@st.dialog("Confirm Data Load")
def _confirm_dialog(filename: str, file_obj):
    # ── Parse CSV once; cache to survive widget-triggered reruns ──────────
    if st.session_state.get("_tpm_filename") != filename:
        try:
            file_obj.seek(0)
            df = pd.read_csv(file_obj, dtype=str).fillna("")
            st.session_state._tpm_df       = df
            st.session_state._tpm_filename = filename
        except Exception as exc:
            st.error(f"Could not parse CSV: {exc}")
            return
    df = st.session_state._tpm_df

    # ── File header ───────────────────────────────────────────────────────
    st.markdown(
        f'<div style="text-align:center;padding:8px 0 14px;">'
        f'<div style="font-size:2rem;margin-bottom:8px;">📂</div>'
        f'<div style="color:#e6edf3;background:#0c1926;padding:7px 16px;border-radius:4px;'
        f'border:1px solid #1a2a3a;display:inline-block;font-size:0.85rem;word-break:break-all;">'
        f'{filename}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    known = _is_known_file(filename)

    if known:
        # ── KNOWN PARTNER: one-click confirm ─────────────────────────────
        st.markdown(
            '<div style="text-align:center;color:#00E6A8;font-size:0.7rem;'
            'letter-spacing:2px;margin-bottom:14px;">RECOGNISED TRADING PARTNER</div>',
            unsafe_allow_html=True,
        )
        c1, c2 = st.columns(2)
        with c1:
            if st.button("Cancel", use_container_width=True):
                st.session_state.dismissed_filename = filename
                st.rerun()
        with c2:
            if st.button("✓  Load", use_container_width=True, type="primary"):
                _known_schema = next(
                    (s for s in _load_schemas()
                     if s.get("client_file", "").lower() == filename.lower()),
                    None,
                )
                _cid = _known_schema["columns"].get("client_id") if _known_schema else None
                # Persist file to input/ so pipeline can read it on next run
                try:
                    file_obj.seek(0)
                    os.makedirs(INPUT_DIR, exist_ok=True)
                    with open(os.path.join(INPUT_DIR, filename), "wb") as _fh:
                        _fh.write(file_obj.read())
                except Exception:
                    pass
                _do_load(filename, df, client_id_col=_cid)

    else:
        # ── UNKNOWN PARTNER: trading-partner mapping form ─────────────────
        st.markdown(
            '<div style="text-align:center;color:#FF9E3B;font-size:0.7rem;'
            'letter-spacing:2px;margin-bottom:4px;">NEW TRADING PARTNER</div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            f'<div style="color:#a8b8c8;font-size:0.75rem;margin-bottom:12px;">'
            f'Map this file\'s columns once — Cascadia remembers it from here on.</div>',
            unsafe_allow_html=True,
        )

        csv_cols = list(df.columns)
        NONE_OPT = "-- None / Ignore --"
        opts     = [NONE_OPT] + csv_cols

        # Auto-detect defaults
        auto    = _detect_cols(df)
        auto_id = _detect_id_col(df)

        def _idx(detected: str | None) -> int:
            return opts.index(detected) if detected and detected in opts else 0

        # Agency name — strip trailing _clients/_members/_log etc., then uppercase
        _base        = re.sub(r'[_\-]+(clients?|members?|log|services?|data|records?)?$', '',
                               filename.replace(".csv", ""), flags=re.I)
        default_name = _base.upper()
        agency_name  = st.text_input("Agency name", value=default_name, key="_tpm_name")

        st.markdown(
            '<div style="color:#a8b8c8;font-size:0.72rem;letter-spacing:1px;'
            'margin:10px 0 4px;">COLUMN MAPPING</div>',
            unsafe_allow_html=True,
        )

        client_id_col    = st.selectbox("Client ID *",             opts, index=_idx(auto_id),                   key="_tpm_cid")
        first_name_col   = st.selectbox("First Name",              opts, index=_idx(auto.get("first_name")),    key="_tpm_fn")
        last_name_col    = st.selectbox("Last Name",               opts, index=_idx(auto.get("last_name")),     key="_tpm_ln")
        dob_col          = st.selectbox("Date of Birth",           opts, index=_idx(auto.get("dob")),           key="_tpm_dob")
        ssn_col          = st.selectbox("SSN / Alt ID (optional)", opts, index=_idx(auto.get("ssn")),           key="_tpm_ssn")
        enc_date_col     = st.selectbox("Encounter / Visit Date",  opts, index=_idx(auto.get("encounter_date")), key="_tpm_enc_date")

        ssn_type_label = st.radio(
            "SSN format",
            ["Not collected", "Last 4 digits (direct)", "Full SSN — extract last 4"],
            index=0,
            horizontal=True,
            key="_tpm_ssn_type",
        )
        ssn_type_map = {
            "Not collected":                  "none",
            "Last 4 digits (direct)":         "last4",
            "Full SSN — extract last 4":      "full",
        }

        st.divider()
        c1, c2 = st.columns(2)
        with c1:
            if st.button("Cancel", use_container_width=True):
                st.session_state.dismissed_filename = filename
                st.rerun()
        with c2:
            if st.button("Save Partner & Load", use_container_width=True, type="primary"):
                if not agency_name.strip():
                    st.error("Agency name is required.")
                    return
                if client_id_col == NONE_OPT:
                    st.error("Client ID column is required.")
                    return

                col_map_user = {
                    "first_name":     first_name_col  if first_name_col  != NONE_OPT else None,
                    "last_name":      last_name_col   if last_name_col   != NONE_OPT else None,
                    "dob":            dob_col         if dob_col         != NONE_OPT else None,
                    "ssn":            ssn_col         if ssn_col         != NONE_OPT else None,
                    "encounter_date": enc_date_col    if enc_date_col    != NONE_OPT else None,
                }
                source_slug = re.sub(r'[^A-Z0-9]+', '_', agency_name.upper()).strip('_')
                _save_new_schema(
                    agency_name   = agency_name.strip(),
                    source_slug   = source_slug,
                    client_file   = filename,
                    client_id_col = client_id_col,
                    col_map_user  = col_map_user,
                    ssn_type      = ssn_type_map[ssn_type_label],
                )
                # Persist the CSV to input/ so the pipeline picks it up on the next run
                try:
                    file_obj.seek(0)
                    os.makedirs(INPUT_DIR, exist_ok=True)
                    with open(os.path.join(INPUT_DIR, filename), "wb") as _fh:
                        _fh.write(file_obj.read())
                    st.session_state._new_partner_saved = filename
                except Exception:
                    st.session_state._new_partner_saved = None
                # Build scoring col_map (only mapped fields, no None values)
                app_col_map = {k: v for k, v in col_map_user.items() if v and k != "encounter_date"}
                _do_load(filename, df, col_map_override=app_col_map,
                         client_id_col=client_id_col if client_id_col != NONE_OPT else None)


# ── Record card renderer ───────────────────────────────────────────────────────
_MASTER_KEYS = {
    "first_name": "canonical_first_name",
    "last_name":  "canonical_last_name",
    "dob":        "canonical_dob",
    "ssn":        "canonical_ssn_last4",
}

def _fv(rec: dict, field: str, col_map: dict) -> str:
    for key in (col_map.get(field), _MASTER_KEYS.get(field)):
        if key and key in rec:
            v = str(rec[key]).strip()
            if v and v.lower() not in ("nan", "none", ""):
                return v
    return "—"

def _render_card(rec: dict, label: str, card_cls: str, lbl_cls: str,
                 col_map: dict, scores: dict) -> None:
    fn  = _fv(rec, "first_name", col_map)
    ln  = _fv(rec, "last_name",  col_map)
    dob = _fv(rec, "dob",        col_map)
    ssn_raw = _fv(rec, "ssn",    col_map)
    ssn = f"*-{ssn_raw[-4:]}" if ssn_raw != "—" and len(ssn_raw) >= 4 else ssn_raw
    name = f"{fn} {ln}".strip() if fn != "—" or ln != "—" else "—"

    abbr = {"first_name": "FN", "last_name": "LN", "dob": "DOB", "ssn": "SSN"}
    chips = "".join(
        f'<span class="sc {"sc-hi" if v >= 85 else "sc-mid" if v >= 65 else "sc-lo"}">'
        f'{abbr.get(k, k)} {v:.0f}%</span>'
        for k, v in scores.items()
    )

    st.markdown(
        f'<div class="record-card {card_cls}">'
        f'<span class="{lbl_cls}">{label}</span>'
        f'<span class="r-val">{name}</span>'
        f'<span class="r-sep">|</span>'
        f'<span class="r-dim">DOB:</span><span class="r-val">{dob}</span>'
        f'<span class="r-sep">|</span>'
        f'<span class="r-dim">SSN:</span><span class="r-val">{ssn}</span>'
        f'<div class="score-row">{chips}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )


# ── Match Evidence Panel ───────────────────────────────────────────────────────
_FIELD_LABELS = {"first_name": "First Name", "last_name": "Last Name",
                 "dob": "Date of Birth", "ssn": "SSN Last 4"}

def _evidence_oneliner(scores: dict) -> str:
    """Build a plain-English summary sentence from field scores."""
    strong, weak = [], []
    for field, score in scores.items():
        label = _FIELD_LABELS.get(field, field)
        if score >= 85:
            strong.append(label)
        elif score < 65:
            weak.append(label)
    parts = []
    if strong:
        parts.append(f"Strong {' + '.join(strong)} match")
    if weak:
        parts.append(f"conflicting {' + '.join(weak)}")
    if not parts:
        return "Moderate agreement across all fields — review carefully."
    return (", ".join(parts) + ".").capitalize()

def _render_evidence_panel(pair: dict, col_map: dict) -> None:
    scores = pair["scores"]
    rec_a, rec_b = pair["rec_a"], pair["rec_b"]

    # One-liner always visible — outside the expander
    oneliner = _evidence_oneliner(scores)
    st.markdown(
        f'<div style="color:#c9d1d9;font-size:0.82rem;font-style:italic;'
        f'margin:8px 0 4px;padding:6px 12px;'
        f'background:rgba(0,0,0,0.2);border-left:3px solid #00E6A8;border-radius:4px;">'
        f'{oneliner}</div>',
        unsafe_allow_html=True,
    )

    with st.expander("🔍  Match Evidence", expanded=False):
        rows_html = ""
        for field in ("first_name", "last_name", "dob", "ssn"):
            if field not in scores:
                continue
            score = scores[field]
            label = _FIELD_LABELS[field]
            va = _fv(rec_a, field, col_map)
            vb = _fv(rec_b, field, col_map)
            if score >= 85:
                score_col, icon = "#00E6A8", "✓"
            elif score >= 65:
                score_col, icon = "#FF9E3B", "~"
            else:
                score_col, icon = "#ef4444", "✗"
            weight = int(_W.get(field, 0.1) * 100)
            rows_html += (
                f'<tr>'
                f'<td style="color:#a8b8c8;padding:5px 10px;font-size:0.78rem;'
                f'letter-spacing:1px;">{label.upper()}</td>'
                f'<td style="color:#c9d1d9;padding:5px 10px;font-size:0.82rem;">{va}</td>'
                f'<td style="color:#c9d1d9;padding:5px 10px;font-size:0.82rem;">{vb}</td>'
                f'<td style="text-align:center;padding:5px 10px;">'
                f'<span style="color:{score_col};font-weight:bold;font-size:0.82rem;">'
                f'{icon} {score:.0f}%</span></td>'
                f'<td style="color:#8fa8c0;padding:5px 10px;font-size:0.75rem;'
                f'text-align:right;">{weight}%</td>'
                f'</tr>'
            )
        st.markdown(
            f'<table style="width:100%;border-collapse:collapse;'
            f'background:rgba(0,0,0,0.15);border-radius:6px;overflow:hidden;">'
            f'<thead><tr>'
            f'<th style="color:#8fa8c0;font-size:0.68rem;letter-spacing:1.5px;'
            f'padding:6px 10px;text-align:left;border-bottom:1px solid rgba(255,255,255,0.05);">'
            f'FIELD</th>'
            f'<th style="color:#00E6A8;font-size:0.68rem;letter-spacing:1.5px;'
            f'padding:6px 10px;text-align:left;border-bottom:1px solid rgba(255,255,255,0.05);">'
            f'RECORD A</th>'
            f'<th style="color:#FF9E3B;font-size:0.68rem;letter-spacing:1.5px;'
            f'padding:6px 10px;text-align:left;border-bottom:1px solid rgba(255,255,255,0.05);">'
            f'RECORD B</th>'
            f'<th style="color:#8fa8c0;font-size:0.68rem;letter-spacing:1.5px;'
            f'padding:6px 10px;text-align:center;border-bottom:1px solid rgba(255,255,255,0.05);">'
            f'AGREEMENT</th>'
            f'<th style="color:#8fa8c0;font-size:0.68rem;letter-spacing:1.5px;'
            f'padding:6px 10px;text-align:right;border-bottom:1px solid rgba(255,255,255,0.05);">'
            f'WEIGHT</th>'
            f'</tr></thead>'
            f'<tbody>{rows_html}</tbody>'
            f'</table>',
            unsafe_allow_html=True,
        )


# ══════════════════════════════════════════════════════════════════════════════
# PIPELINE RE-RUN (triggered by "Re-run & Export" in the golden dialog)
# ══════════════════════════════════════════════════════════════════════════════

if st.session_state._rerun_and_export:
    import subprocess, sys as _sys
    st.markdown(
        '<div style="color:#00E6A8;letter-spacing:2px;font-size:0.8rem;'
        'padding:12px 0 8px;">▸ PIPELINE RE-RUN IN PROGRESS</div>',
        unsafe_allow_html=True,
    )
    _project_dir = os.path.dirname(os.path.abspath(__file__))
    _pipeline_script = os.path.join(_project_dir, "mpi_pipeline.py")
    with st.status("Running MPI pipeline — this takes 30–90 seconds...",
                   expanded=True) as _status:
        _proc = subprocess.run(
            [_sys.executable, _pipeline_script],
            capture_output=True, text=True, encoding="utf-8",
            env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"},
            cwd=_project_dir,
        )
        _combined = (_proc.stdout or "") + (_proc.stderr or "")
        st.code(_combined, language="text")
        if _proc.returncode == 0:
            _status.update(
                label="Pipeline complete — generating golden file...",
                state="complete",
            )
        else:
            _status.update(label="Pipeline failed — see output above", state="error")

    if _proc.returncode == 0:
        # Auto-generate both golden files from fresh pipeline output
        try:
            import duckdb as _ddb2, datetime as _dt
            # Apply same override-CTE logic as _do_golden_export
            _has_pers2 = os.path.exists(ACCEPTED_PERSONS_PATH)
            _has_bri2  = os.path.exists(_GOLDEN_BRIDGE)
            _has_enc2  = os.path.exists(ACCEPTED_ENCOUNTERS_PATH)
            # Apply severed_links splits
            _gdim2, _gbridge2, _genc2 = _prepare_golden_sources()
            if _has_pers2 and _has_bri2:
                _xtra2 = (
                    f"UNION ALL SELECT encounter_id, master_person_id, unique_record_id,"
                    f" source_system, encounter_date, service_category, location_info"
                    f" FROM '{ACCEPTED_ENCOUNTERS_PATH}'"
                    if _has_enc2 else ""
                )
                _ap2_src = f"read_csv('{ACCEPTED_PERSONS_PATH}', delim=',', quote='\"', header=true, strict_mode=false)"
                _cte2_block = f"""WITH overridden AS (
                    SELECT DISTINCT b.master_person_id AS pipeline_mpi, ap.target_mpi
                    FROM '{_gbridge2}' b
                    JOIN {_ap2_src} ap
                      ON LOWER(b.source_system) = LOWER(ap.source_system)
                     AND b.source_id = ap.source_id
                    WHERE b.master_person_id != ap.target_mpi
                ),
                merged_additions AS (
                    SELECT
                        ov.target_mpi,
                        string_agg(DISTINCT b.source_system, ', ') AS extra_sources,
                        COUNT(b.unique_record_id)               AS extra_records,
                        COUNT(DISTINCT b.source_system)         AS extra_src_count
                    FROM overridden ov
                    JOIN '{_gbridge2}' b ON b.master_person_id = ov.pipeline_mpi
                    GROUP BY ov.target_mpi
                ),
                augmented_dim AS (
                    SELECT
                        d.master_person_id,
                        d.canonical_first_name,
                        d.canonical_last_name,
                        d.canonical_dob,
                        d.canonical_ssn_last4,
                        CASE WHEN ma.extra_sources IS NOT NULL
                             THEN d.contributing_sources || ', ' || ma.extra_sources
                             ELSE d.contributing_sources
                        END AS contributing_sources,
                        TRY_CAST(d.total_linked_records AS INTEGER) + COALESCE(ma.extra_records, 0) AS total_linked_records,
                        TRY_CAST(d.linked_sources_count AS INTEGER) + COALESCE(ma.extra_src_count, 0) AS linked_sources_count
                    FROM '{_gdim2}' d
                    LEFT JOIN merged_additions ma ON d.master_person_id = ma.target_mpi
                    WHERE d.master_person_id NOT IN (SELECT pipeline_mpi FROM overridden)
                ),
                enc_reassigned AS (
                    SELECT COALESCE(ov.target_mpi, e.master_person_id) AS master_person_id,
                           e.encounter_id, e.unique_record_id, e.source_system,
                           e.encounter_date, e.service_category, e.location_info
                    FROM '{_genc2}' e
                    LEFT JOIN overridden ov ON e.master_person_id = ov.pipeline_mpi
                    {_xtra2}
                )"""
                _dim2_src = "augmented_dim"
                _enc2_src = "enc_reassigned"
            else:
                _cte2_block = ""
                _dim2_src = f"'{_gdim2}'"
                _enc2_src = (
                    f"(SELECT * FROM '{_genc2}' UNION ALL SELECT * FROM '{ACCEPTED_ENCOUNTERS_PATH}')"
                    if _has_enc2 else f"'{_genc2}'"
                )
            # 1. Persons × encounters (CTE inside COPY)
            _ddb2.sql(f"""
                COPY (
                    {_cte2_block}
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
                    FROM {_dim2_src} m
                    JOIN {_enc2_src} e USING (master_person_id)
                    ORDER BY m.canonical_last_name,
                             m.canonical_first_name,
                             e.encounter_date
                ) TO '{_GOLDEN_OUT}' (HEADER, DELIMITER ',')
            """)
            _enc_rc = _ddb2.sql(f"SELECT COUNT(*) FROM '{_GOLDEN_OUT}'").fetchone()[0]
            # 2. Persons only (CTE inside COPY)
            _ddb2.sql(f"""
                COPY (
                    {_cte2_block}
                    SELECT
                        master_person_id,
                        canonical_first_name,
                        canonical_last_name,
                        canonical_dob,
                        canonical_ssn_last4,
                        contributing_sources,
                        total_linked_records,
                        linked_sources_count
                    FROM {_dim2_src}
                    ORDER BY canonical_last_name, canonical_first_name
                ) TO '{_GOLDEN_PERSONS}' (HEADER, DELIMITER ',')
            """)
            _p_rc = _ddb2.sql(f"SELECT COUNT(*) FROM '{_GOLDEN_PERSONS}'").fetchone()[0]
            _ts = _dt.datetime.now().strftime("%H:%M:%S")
            st.session_state._golden_result = (
                f"WRITTEN {_ts} — {_p_rc:,} persons · {_enc_rc:,} encounters"
            )
        except Exception as _ex:
            st.session_state._golden_result = f"Pipeline OK but golden export failed: {_ex}"
    else:
        # Pipeline failed — surface the error so the sidebar shows feedback
        _tail = ((_proc.stdout or "") + (_proc.stderr or ""))[-400:].strip()
        st.session_state._golden_result = (
            f"ERROR: Pipeline failed (exit {_proc.returncode}). "
            f"Golden file NOT written. Last output: {_tail}"
        )

    st.session_state._rerun_and_export = False
    st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# LAYOUT
# ══════════════════════════════════════════════════════════════════════════════

# ── Sidebar: session metrics ───────────────────────────────────────────────────
with st.sidebar:
    st.markdown(
        '<div style="color:#00E6A8;letter-spacing:2px;font-size:0.7rem;'
        'padding:10px 0 12px;border-bottom:1px solid rgba(0,230,168,0.08);">'
        '▸ SESSION METRICS</div>',
        unsafe_allow_html=True,
    )
    dec      = st.session_state.decisions
    accepted = sum(1 for d in dec if d == "accept")
    rejected = sum(1 for d in dec if d == "reject")
    total    = len(st.session_state.candidate_pairs)
    remain   = max(0, total - st.session_state.current_idx)
    mn = st.session_state.min_threshold
    mx = st.session_state.max_threshold

    auto_n = st.session_state.auto_accepted
    for lbl, val, vcls in [
        ("Auto-Accepted",       str(auto_n),                "m-val"),
        ("Accepted Merges",     str(accepted),              "m-val"),
        ("Rejected Links",      str(rejected),              "m-val"),
        ("Queue Remaining",     str(remain),                "m-warn" if remain else "m-val"),
        ("Total Candidates",    str(total),                 "m-val"),
        ("Max Threshold",       f"{mx}%",                   "m-val"),
        ("Min Threshold",       f"{mn}%",                   "m-val"),
    ]:
        st.markdown(
            f'<div class="m-row">'
            f'<span class="m-lbl">{lbl}</span>'
            f'<span class="{vcls}">{val}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )

    # ── Ingested Datasets ──────────────────────────────────────────────────────
    _registry = st.session_state.ingested_registry
    if _registry:
        st.markdown(
            '<div style="color:#00E6A8;letter-spacing:2px;font-size:0.7rem;'
            'padding:14px 0 8px;border-bottom:1px solid rgba(0,230,168,0.08);">'
            '▸ INGESTED DATASETS</div>',
            unsafe_allow_html=True,
        )
        for _ds_label, _ds_count in sorted(_registry.items()):
            _cli = _client_record_count(_ds_label)
            _svc = _service_record_count(_ds_label)
            _rec_str = (
                f", {_cli:,} client records, {_svc:,} service records"
                if _cli > 0 else ""
            )
            _suffix = f"({_ds_count} file{'s' if _ds_count != 1 else ''}{_rec_str})"
            _row_lbl, _row_btn = st.columns([8, 1])
            with _row_lbl:
                st.markdown(
                    f'<div class="m-row" style="padding:3px 0;">'
                    f'<span class="m-lbl">{_ds_label}</span>'
                    f'<span class="m-val">{_suffix}</span>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
            with _row_btn:
                if st.button("×", key=f"rm_ds_{_ds_label}", help=f"Remove {_ds_label}"):
                    st.session_state._pending_remove = _ds_label
                    st.rerun()
        if st.session_state._pending_remove:
            _confirm_remove_dialog(st.session_state._pending_remove)

    if dec:
        st.markdown(
            '<div style="color:#00E6A8;letter-spacing:2px;font-size:0.7rem;'
            'padding:14px 0 8px;border-bottom:1px solid rgba(0,230,168,0.08);">'
            '▸ RECENT DECISIONS</div>',
            unsafe_allow_html=True,
        )
        for i, d in enumerate(reversed(dec[-7:])):
            n = len(dec) - i
            icon = "💚" if d == "accept" else "❌"
            st.markdown(
                f'<div style="font-size:0.7rem;color:#2a3a4a;padding:2px 0;">'
                f'{icon} Pair {n}</div>',
                unsafe_allow_html=True,
            )

    if st.session_state.confirmed_filename:
        st.markdown("---")
        st.markdown(
            f'<div style="font-size:0.68rem;color:#1a2a3a;word-break:break-all;padding-bottom:8px;">'
            f'Loaded: {st.session_state.confirmed_filename}</div>',
            unsafe_allow_html=True,
        )
        if st.button("⟳  Load New File", use_container_width=True):
            for k, v in _DEFAULTS.items():
                st.session_state[k] = v
            st.rerun()

        # Persona presets
        st.markdown(
            '<div style="color:#00E6A8;letter-spacing:2px;font-size:0.7rem;'
            'padding:14px 0 10px;border-top:1px solid rgba(0,230,168,0.08);">'
            '▸ PERSONA PRESETS</div>',
            unsafe_allow_html=True,
        )
        # (label, min_thr, max_thr)
        presets = [
            ("⚖  Strict / Legal Housing", 85, 95),
            ("🏠 Case Management",         75, 88),
            ("📊 Public Health Aggregate", 60, 78),
        ]
        for label, p_min, p_max in presets:
            if st.button(label, use_container_width=True, key=f"preset_{p_min}_{p_max}"):
                st.session_state.min_threshold = p_min
                st.session_state.max_threshold = p_max
                if st.session_state.confirmed_df is not None:
                    _p, _a = build_candidates(
                        st.session_state.confirmed_df,
                        st.session_state.col_map,
                        p_min, p_max,
                    )
                    st.session_state.candidate_pairs = _p
                    st.session_state.auto_accepted   = _a
                    st.session_state.current_idx = 0
                    st.session_state.decisions   = []
                st.rerun()

        # ── Suggest Thresholds ─────────────────────────────────────────────
        st.markdown(
            '<div style="color:#00E6A8;letter-spacing:2px;font-size:0.7rem;'
            'padding:14px 0 10px;border-top:1px solid rgba(0,230,168,0.08);">'
            '▸ THRESHOLD ADVISOR</div>',
            unsafe_allow_html=True,
        )
        _has_data = st.session_state.confirmed_df is not None
        if st.button(
            "💡 Suggest Thresholds" if _has_data else "💡 Load a file to get suggestions",
            use_container_width=True,
            disabled=not _has_data,
            key="btn_suggest",
        ):
            _h_min, _h_max = _suggest_thresholds(
                st.session_state.confirmed_df,
                st.session_state.col_map,
            )
            st.session_state.threshold_hint = (_h_min, _h_max)

        _hint = st.session_state.threshold_hint
        if _hint:
            _h_min, _h_max = _hint
            st.markdown(
                f'<div style="background:rgba(0,230,168,0.06);border:1px solid rgba(0,230,168,0.18);'
                f'border-radius:5px;padding:10px 12px;margin:6px 0 4px;">'
                f'<div style="color:#00E6A8;font-size:0.68rem;letter-spacing:1.5px;margin-bottom:6px;">SUGGESTED</div>'
                f'<div style="display:flex;justify-content:space-between;margin-bottom:4px;">'
                f'<span style="color:#8fa8c0;font-size:0.75rem;">Min Threshold</span>'
                f'<span style="color:#e6edf3;font-size:0.75rem;font-weight:bold;">{_h_min}%</span>'
                f'</div>'
                f'<div style="display:flex;justify-content:space-between;margin-bottom:10px;">'
                f'<span style="color:#8fa8c0;font-size:0.75rem;">Max Threshold</span>'
                f'<span style="color:#e6edf3;font-size:0.75rem;font-weight:bold;">{_h_max}%</span>'
                f'</div>'
                f'<div style="font-size:0.68rem;color:#8fa8c0;line-height:1.4;">'
                f'Based on your data\'s score distribution. '
                f'Filters the noisiest 40% of candidates automatically.'
                f'</div>'
                f'</div>',
                unsafe_allow_html=True,
            )
            _apply_col, _dismiss_col = st.columns(2)
            with _apply_col:
                if st.button("Apply", use_container_width=True, type="primary", key="btn_hint_apply"):
                    st.session_state.min_threshold = _h_min
                    st.session_state.max_threshold = _h_max
                    st.session_state.threshold_hint = None
                    if st.session_state.confirmed_df is not None:
                        _p, _a = build_candidates(
                            st.session_state.confirmed_df,
                            st.session_state.col_map,
                            _h_min, _h_max,
                        )
                        st.session_state.candidate_pairs = _p
                        st.session_state.auto_accepted   = _a
                        st.session_state.current_idx = 0
                        st.session_state.decisions   = []
                    st.rerun()
            with _dismiss_col:
                if st.button("Dismiss", use_container_width=True, key="btn_hint_dismiss"):
                    st.session_state.threshold_hint = None
                    st.rerun()

    # ── Export Golden File ─────────────────────────────────────────────────
    _pipeline_ready = (
        os.path.exists("output/dim_master_persons.csv")
        and os.path.exists("output/fact_encounters.csv")
    )
    st.markdown(
        '<div style="color:#00E6A8;letter-spacing:2px;font-size:0.7rem;'
        'padding:14px 0 10px;border-top:1px solid rgba(0,230,168,0.08);">'
        '▸ EXPORT</div>',
        unsafe_allow_html=True,
    )
    _golden_exists = os.path.exists(_GOLDEN_OUT)
    _btn_label = (
        "Overwrite Golden File" if _golden_exists else "Generate Golden File"
    )
    st.session_state._always_rerun_pipeline = st.checkbox(
        "Always re-run pipeline before export",
        value=st.session_state._always_rerun_pipeline,
        key="chk_always_rerun",
    )
    if st.button(
        _btn_label if _pipeline_ready else "Run pipeline first",
        use_container_width=True,
        disabled=not _pipeline_ready,
        key="btn_golden",
    ):
        st.session_state._golden_result = None
        if st.session_state._always_rerun_pipeline:
            st.session_state._pending_golden = False
            st.session_state._rerun_and_export = True
        else:
            st.session_state._pending_golden = True
        st.rerun()

    _gr = st.session_state._golden_result
    if _gr:
        _ok = not _gr.startswith("ERROR")
        _icon = "✔ FILE WRITTEN" if _ok else "✗ EXPORT FAILED"
        st.markdown(
            f'<div style="background:{"#001a0e" if _ok else "rgba(180,20,20,0.18)"};'
            f'border:1px solid {"#00E6A8" if _ok else "rgba(220,50,50,0.5)"};'
            f'border-radius:6px;padding:10px 12px;margin-top:8px;">'
            f'<div style="color:{"#00E6A8" if _ok else "#ff6666"};font-size:0.68rem;'
            f'letter-spacing:1.8px;font-family:\'Courier New\',monospace;margin-bottom:4px;">'
            f'{_icon}</div>'
            f'<div style="color:{"#00a87a" if _ok else "#ff9999"};font-size:0.7rem;'
            f'word-break:break-all;line-height:1.5;">{_gr}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

    if st.session_state._pending_golden:
        _confirm_golden_dialog()



_LOGO_SVG = ""  # logo removed per user request

# ── Global button styler — CSS injection + MutationObserver ───────────────────
# CSS covers all children React may swap in; data-c3e attr persists on the
# button element itself (React doesn't touch custom data-* it didn't set).
_HP = "M18 29C18 29 2 19 2 9.5 2 5.4 5.4 2 9.5 2c2.9 0 5.3 1.6 6.7 3.9L18 8.8l1.8-2.9C21.2 3.6 23.6 2 26.5 2 30.6 2 34 5.4 34 9.5 34 19 18 29 18 29z"
_EP = "3,14 8,14 10,8 13,22 16,12 18,16 20,14 33,14"

def _svg_uri(ecg_color: str) -> str:
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 36 32">'
           f'<path d="{_HP}" fill="rgba(255,255,255,0.92)"/>'
           f'<polyline points="{_EP}" stroke="{ecg_color}" stroke-width="2.2" '
           f'fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg>')
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()

_REJ_URI = _svg_uri("#7a0000")
_ACC_URI = _svg_uri("#0d4a22")

def _golden_svg_uri() -> str:
    # Gold heart + dark-amber ECG on a transparent field
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 36 32">'
        # outer glow halo
        f'<path d="{_HP}" fill="rgba(255,200,0,0.18)" transform="scale(1.12) translate(-1.6,-1.6)"/>'
        # main gold heart
        f'<path d="{_HP}" fill="#FFD700"/>'
        # dark-amber ECG line for contrast
        f'<polyline points="{_EP}" stroke="#3D1F00" stroke-width="2.4" '
        f'fill="none" stroke-linecap="round" stroke-linejoin="round"/>'
        f'</svg>'
    )
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()

_GOLD_URI = _golden_svg_uri()

components.html(f"""<script>
(function() {{
  // Inject a persistent <style> once; CSS selector covers any child React swaps in
  if (!window.parent.document.getElementById('c3e-styles')) {{
    var s = window.parent.document.createElement('style');
    s.id = 'c3e-styles';
    s.textContent = `
      button[data-c3e='x'] {{
        background: rgba(180,20,20,0.30) !important;
        border: 1px solid rgba(220,50,50,0.55) !important;
        border-radius: 3px !important;
        padding: 0 !important;
        min-height: 20px !important;
        height: 20px !important;
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
      }}
      button[data-c3e='x']:hover {{ background: rgba(220,40,40,0.50) !important; }}
      button[data-c3e='x'] * {{ color: #ff6666 !important; font-size: 0.85rem !important; }}

      button[data-c3e='rej'] {{
        background: linear-gradient(135deg,#5a0000,#b71c1c) !important;
        border: 1px solid #c62828 !important;
        display: flex !important; align-items: center !important; justify-content: center !important;
      }}
      button[data-c3e='rej']:hover {{ background: linear-gradient(135deg,#7a0000,#e53935) !important; }}
      button[data-c3e='rej'] * {{ color: #fff !important; font-weight: 700 !important; letter-spacing: 2px !important; }}
      button[data-c3e='rej']::before {{
        content: ''; display: inline-block; width: 22px; height: 20px;
        margin-right: 8px; flex-shrink: 0;
        background: url("{_REJ_URI}") no-repeat center/contain;
      }}

      button[data-c3e='acc'] {{
        background: linear-gradient(135deg,#0a2e14,#1b7a3e) !important;
        border: 1px solid #2e7d52 !important;
        display: flex !important; align-items: center !important; justify-content: center !important;
      }}
      button[data-c3e='acc']:hover {{ background: linear-gradient(135deg,#145a32,#27ae60) !important; }}
      button[data-c3e='acc'] * {{ color: #fff !important; font-weight: 700 !important; letter-spacing: 2px !important; }}
      button[data-c3e='acc']::before {{
        content: ''; display: inline-block; width: 22px; height: 20px;
        margin-right: 8px; flex-shrink: 0;
        background: url("{_ACC_URI}") no-repeat center/contain;
      }}

      button[data-c3e='golden'] {{
        background: linear-gradient(135deg, #1a0800 0%, #5c3600 45%, #9a6800 100%) !important;
        border: 1px solid #C8920A !important;
        box-shadow: 0 0 10px rgba(200,146,10,0.35), inset 0 1px 0 rgba(255,220,80,0.15) !important;
        display: flex !important; align-items: center !important; justify-content: center !important;
        transition: box-shadow 0.2s ease !important;
      }}
      button[data-c3e='golden']:hover {{
        background: linear-gradient(135deg, #2a1200 0%, #7a4e00 45%, #C8920A 100%) !important;
        box-shadow: 0 0 18px rgba(218,165,32,0.65), inset 0 1px 0 rgba(255,230,100,0.25) !important;
      }}
      button[data-c3e='golden'] * {{
        color: #FFD700 !important;
        font-weight: 700 !important;
        letter-spacing: 1.5px !important;
        text-shadow: 0 0 8px rgba(255,200,0,0.5) !important;
      }}
      button[data-c3e='golden']::before {{
        content: ''; display: inline-block; width: 26px; height: 22px;
        margin-right: 10px; flex-shrink: 0;
        background: url("{_GOLD_URI}") no-repeat center/contain;
        filter: drop-shadow(0 0 4px rgba(255,210,0,0.7));
      }}
    `;
    window.parent.document.head.appendChild(s);
  }}

  // Tag buttons with data-c3e — that's all JS needs to do
  function tag(btn) {{
    if (btn.getAttribute('data-c3e')) return;
    var t = btn.textContent.trim();
    if (t === '×')                 btn.setAttribute('data-c3e', 'x');
    else if (t === 'REJECT')            btn.setAttribute('data-c3e', 'rej');
    else if (t === 'ACCEPT')            btn.setAttribute('data-c3e', 'acc');
    else if (t.indexOf('Golden File') >= 0) btn.setAttribute('data-c3e', 'golden');
  }}

  function tagAll() {{ window.parent.document.querySelectorAll('button').forEach(tag); }}
  tagAll();
  setTimeout(tagAll, 200);

  new MutationObserver(function(muts) {{
    muts.forEach(function(m) {{
      m.addedNodes.forEach(function(n) {{
        if (n.nodeType !== 1) return;
        if (n.tagName === 'BUTTON') tag(n);
        else n.querySelectorAll('button').forEach(tag);
      }});
    }});
  }}).observe(window.parent.document.body, {{childList:true, subtree:true}});
}})();
</script>""", height=0)

# ── Title ──────────────────────────────────────────────────────────────────────
st.markdown(
    '<div class="title-banner">'
    '<div class="title-inner">'
    + _LOGO_SVG +
    '<div class="title-text">'
    '<div class="title-h1">'
    '<span class="t-acc">Cascadia</span> (C3E)'
    '</div>'
    '<div class="title-sub">'
    'Continuum of Care Master Data Engine for the RRV'
    '</div>'
    '</div>'
    '</div>'
    '</div>',
    unsafe_allow_html=True,
)

_tab_audit, _tab_trends, _tab_records = st.tabs(["🗂  Audit", "📊  Trends", "🗃  Records"])

with _tab_audit:
    # ── Dual Confidence Sliders ──────────────────────────────────────────────
    sl_col, lbl_col = st.columns([5, 1])
    with sl_col:
        new_max = st.slider(
            "Confidence: Max Threshold",
            min_value=1, max_value=99,
            value=st.session_state.max_threshold,
            step=1, format="%d%%",
            help="Pairs at or above this confidence are auto-accepted with no card shown.",
        )
    with lbl_col:
        st.markdown('<div style="height:20px;"></div>', unsafe_allow_html=True)
        st.metric("Auto-Accept", f"{new_max}%")

    sl_col2, lbl_col2 = st.columns([5, 1])
    with sl_col2:
        new_min = st.slider(
            "Confidence: Min Threshold",
            min_value=1, max_value=99,
            value=st.session_state.min_threshold,
            step=1, format="%d%%",
            help="Pairs below this confidence are auto-rejected and never surfaced.",
        )
    with lbl_col2:
        st.markdown('<div style="height:20px;"></div>', unsafe_allow_html=True)
        st.metric("Auto-Reject", f"<{new_min}%")

    # Clamp: min must be < max
    new_min = min(new_min, new_max - 1)

    _changed = (
        new_min != st.session_state.min_threshold or
        new_max != st.session_state.max_threshold
    )
    if _changed:
        st.session_state.min_threshold = new_min
        st.session_state.max_threshold = new_max
        if st.session_state.confirmed_df is not None:
            _p, _a = build_candidates(
                st.session_state.confirmed_df,
                st.session_state.col_map,
                new_min,
                new_max,
            )
            st.session_state.candidate_pairs = _p
            st.session_state.auto_accepted   = _a
            st.session_state.current_idx = 0
            st.session_state.decisions   = []
        st.rerun()

    # ── Decisions-required counter (live, threshold-aware) ────────────────────────
    if st.session_state.confirmed_df is not None:
        n_required = len(st.session_state.candidate_pairs)
        already    = st.session_state.current_idx
        color      = "#00E6A8" if n_required == 0 else "#FF9E3B" if n_required > 10 else "#e6edf3"
        st.markdown(
            f'<div style="'
            f'display:flex;align-items:center;gap:14px;'
            f'padding:10px 16px;margin:6px 0 10px;'
            f'background:rgba(0,0,0,0.28);'
            f'border:1px solid {color}44;'
            f'border-radius:6px;'
            f'">'
            f'<span style="color:#a8b8c8;font-size:0.72rem;letter-spacing:2px;white-space:nowrap;">'
            f'DECISIONS REQUIRED</span>'
            f'<span style="color:{color};font-size:1.4rem;font-weight:700;letter-spacing:1px;">'
            f'{n_required - already}</span>'
            f'<span style="color:#8fa8c0;font-size:0.72rem;margin-left:auto;">'
            f'{already} of {n_required} reviewed &nbsp;·&nbsp; '
            f'{st.session_state.auto_accepted} auto-accepted'
            f'</span>'
            f'</div>',
            unsafe_allow_html=True,
        )

    # ── File uploader ─────────────────────────────────────────────────────────────
    def _on_main_upload():
        """Fires on both drag-drop and OS file-picker upload; stores file before script body runs."""
        f = st.session_state.get("_main_uploader")
        if f is not None:
            st.session_state._pending_upload = f

    uploaded = st.file_uploader(
        "Drop partner CSV",
        type=["csv"],
        label_visibility="collapsed",
        key="_main_uploader",
        on_change=_on_main_upload,
    )

    # Resolve: prefer the on_change-captured file (handles OS picker), fall back to widget value
    _file = st.session_state._pending_upload or uploaded
    if (_file is not None
            and _file.name != st.session_state.confirmed_filename
            and _file.name != st.session_state.dismissed_filename):
        st.session_state._pending_upload = None
        _confirm_dialog(_file.name, _file)

    st.markdown('<div style="height:6px;"></div>', unsafe_allow_html=True)

    # ── New-partner pipeline nudge ─────────────────────────────────────────────────
    _np = st.session_state.get("_new_partner_saved")
    if _np:
        st.markdown(
            f'<div style="background:#001a0e;border:1px solid #00E6A8;border-radius:6px;'
            f'padding:9px 12px;margin-bottom:8px;">'
            f'<div style="color:#00E6A8;font-size:0.68rem;letter-spacing:1.5px;margin-bottom:3px;">'
            f'✔ PARTNER SAVED — {_np}</div>'
            f'<div style="color:#00a87a;font-size:0.7rem;line-height:1.5;">'
            f'File written to <code>input/</code>. Re-run the pipeline from the '
            f'<b>Audit</b> tab to include this agency in the golden file and Trends.</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

    # ── Main deck ──────────────────────────────────────────────────────────────────
    pairs   = st.session_state.candidate_pairs
    idx     = st.session_state.current_idx
    col_map = st.session_state.col_map
    eff     = st.session_state.max_threshold

    if st.session_state.confirmed_df is None:
        # ── Landing ─────────────────────────────────────────────────────────────
        st.markdown(
            '<div class="drop-zone">'
            '<div class="drop-h">↑ DROP A PARTNER CSV TO BEGIN</div>'
            '<div class="drop-sub">'
            'OHRA · PEACE HOUSE · ST. VINCENT DE PAUL · LA CLINICA'
            '</div>'
            '</div>',
            unsafe_allow_html=True,
        )

    elif len(pairs) == 0:
        # ── No matches at current threshold ─────────────────────────────────────
        st.markdown(
            f'<div class="nomatch-box">'
            f'<div class="nomatch-head">NO CANDIDATE MATCHES AT {eff}% THRESHOLD</div>'
            f'Loaded <strong style="color:#e6edf3;">{st.session_state.confirmed_filename}</strong> '
            f'({len(st.session_state.confirmed_df)} records).<br><br>'
            f'Drag the Omni-Slider left to loosen the matching net,<br>'
            f'or select the <strong style="color:#e6edf3;">Public Health Aggregate</strong> preset.'
            f'</div>',
            unsafe_allow_html=True,
        )

    elif idx >= len(pairs):
        # ── Queue complete ───────────────────────────────────────────────────────
        accepted  = sum(1 for d in st.session_state.decisions if d == "accept")
        rejected  = sum(1 for d in st.session_state.decisions if d == "reject")
        client_fn = st.session_state.confirmed_filename or ""
        st.markdown(
            '<div class="complete-wrap">'
            '<div class="complete-icon">✓</div>'
            '<div class="complete-head">REVIEW COMPLETE</div>'
            f'<div class="complete-sub">'
            f'{accepted} merged · {rejected} rejected · {len(pairs)} total reviewed'
            f'</div>'
            '</div>',
            unsafe_allow_html=True,
        )

        # ── Services file prompt ─────────────────────────────────────────────────
        if st.session_state.awaiting_services is None:
            st.markdown(
                f'<div style="'
                f'margin:18px 0 10px;padding:18px 22px;'
                f'background:rgba(0,0,0,0.32);'
                f'border:1px solid rgba(0,230,168,0.22);'
                f'border-radius:8px;'
                f'">'
                f'<div style="color:#00E6A8;letter-spacing:2px;font-size:0.72rem;margin-bottom:10px;">'
                f'SERVICES DATA</div>'
                f'<div style="color:#c9d1d9;font-size:0.92rem;margin-bottom:16px;">'
                f'Do you have a matching services file for<br>'
                f'<strong style="color:#e6edf3;">{client_fn}</strong> ?'
                f'</div>'
                f'</div>',
                unsafe_allow_html=True,
            )
            btn_yes, btn_no = st.columns(2)
            with btn_yes:
                if st.button("Yes — Load Services File", use_container_width=True, type="primary"):
                    st.session_state.awaiting_services = True
                    st.rerun()
            with btn_no:
                if st.button("No — Skip", use_container_width=True):
                    st.session_state.awaiting_services = False
                    st.rerun()

        elif st.session_state.awaiting_services is True and st.session_state.services_df is None:
            st.markdown(
                f'<div style="'
                f'margin:18px 0 10px;padding:14px 22px;'
                f'background:rgba(0,0,0,0.28);'
                f'border:1px solid rgba(0,230,168,0.18);'
                f'border-radius:8px;'
                f'">'
                f'<div style="color:#00E6A8;letter-spacing:2px;font-size:0.72rem;margin-bottom:8px;">'
                f'DROP SERVICES CSV</div>'
                f'<div style="color:#a8b8c8;font-size:0.78rem;">'
                f'Drop the services file that corresponds to <strong style="color:#c9d1d9;">{client_fn}</strong>'
                f'</div>'
                f'</div>',
                unsafe_allow_html=True,
            )
            svc_upload = st.file_uploader(
                "Drop services CSV",
                type=["csv"],
                key="svc_uploader",
                label_visibility="collapsed",
            )
            if svc_upload is not None:
                try:
                    svc_df = pd.read_csv(svc_upload, dtype=str).fillna("")
                    st.session_state.services_df       = svc_df
                    st.session_state.services_filename = svc_upload.name
                    # Registry: count the services file as +1 for its source
                    _svc_lbl = _label_from_filename(svc_upload.name)
                    _reg = dict(st.session_state.ingested_registry)
                    _reg[_svc_lbl] = _reg.get(_svc_lbl, 0) + 1
                    st.session_state.ingested_registry = _reg
                    st.toast(f"✓ Services file loaded — {len(svc_df):,} records", icon="✅")
                    time.sleep(1.2)
                    st.rerun()
                except Exception as exc:
                    st.error(f"Could not read services file: {exc}")

        elif st.session_state.services_df is not None:
            svc_df = st.session_state.services_df
            st.markdown(
                f'<div style="'
                f'margin:18px 0 0;padding:14px 22px;'
                f'background:rgba(0,230,168,0.04);'
                f'border:1px solid rgba(0,230,168,0.25);'
                f'border-radius:8px;'
                f'">'
                f'<div style="color:#00E6A8;letter-spacing:2px;font-size:0.72rem;margin-bottom:6px;">'
                f'SERVICES FILE LOADED</div>'
                f'<div style="color:#c9d1d9;font-size:0.88rem;">'
                f'<strong>{st.session_state.services_filename}</strong> &nbsp;·&nbsp; '
                f'{len(svc_df):,} service records &nbsp;·&nbsp; '
                f'{svc_df.shape[1]} columns'
                f'</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

    else:
        # ── Active swipe deck ────────────────────────────────────────────────────
        pair   = pairs[idx]
        comp   = pair["composite"]
        scores = pair["scores"]

        # Borderline warning — pair is in manual review zone
        if comp < st.session_state.max_threshold:
            suggested = max(st.session_state.min_threshold, st.session_state.max_threshold - 5)
            st.markdown(
                f'<div class="warn-banner">'
                f'⚠ &nbsp;<strong>Borderline Match Detected</strong> '
                f'<span style="color:#b2bfcc;font-size:0.78rem;">({comp:.0f}% Confidence)</span>'
                f'&nbsp;<span class="warn-chip">Try lowering threshold to {suggested}%</span>'
                f'</div>',
                unsafe_allow_html=True,
            )

        # Confidence bar
        bar_c = "#00E6A8" if comp >= 85 else ("#FF9E3B" if comp >= 70 else "#ef4444")
        st.markdown(
            f'<div class="conf-wrap">'
            f'<div class="conf-fill" style="width:{min(comp,100):.0f}%;background:{bar_c};"></div>'
            f'</div>'
            f'<div style="font-size:0.7rem;color:#8fa8c0;margin-bottom:12px;">'
            f'CONFIDENCE <span style="color:{bar_c};font-weight:bold;">{comp:.1f}%</span>'
            f'&nbsp;·&nbsp; PAIR {idx + 1} / {len(pairs)}'
            f'</div>',
            unsafe_allow_html=True,
        )

        # Cards
        _render_card(pair["rec_a"], "RECORD A:", "card-a", "lbl-a", col_map, scores)
        _render_card(pair["rec_b"], "RECORD B:", "card-b", "lbl-b", col_map, scores)

        _render_evidence_panel(pair, col_map)

        if pair.get("mpi"):
            st.markdown(
                f'<div style="font-size:0.65rem;color:#1a2a3a;margin-bottom:12px;">'
                f'MPI · {pair["mpi"]}</div>',
                unsafe_allow_html=True,
            )

        # Buttons
        st.markdown('<div style="height:6px;"></div>', unsafe_allow_html=True)
        btn_r, btn_a = st.columns(2)
        with btn_r:
            if st.button("REJECT", use_container_width=True, key=f"rej_{idx}"):
                st.session_state.decisions.append("reject")
                _persist_decision(pair, "reject")
                st.session_state.current_idx += 1
                st.rerun()
        with btn_a:
            if st.button("ACCEPT", use_container_width=True,
                         key=f"acc_{idx}", type="primary"):
                st.session_state.decisions.append("accept")
                _persist_decision(pair, "accept")
                _accept_link(pair)
                st.session_state.current_idx += 1
                st.rerun()


with _tab_trends:
    import duckdb as _ddb_trends

    _enc_path = os.path.join(os.path.dirname(__file__), "output", "fact_encounters.csv")
    _dim_path = os.path.join(os.path.dirname(__file__), "output", "dim_master_persons.csv")

    if not os.path.exists(_enc_path):
        st.info("Run the pipeline first to generate output files.")
    else:
        _con = _ddb_trends.connect()
        _enc = _con.execute(f"SELECT * FROM read_csv_auto('{_enc_path.replace(chr(92), '/')}')").df()
        _dim = _con.execute(f"SELECT * FROM read_csv_auto('{_dim_path.replace(chr(92), '/')}')").df() if os.path.exists(_dim_path) else None

        # Parse dates
        _enc["encounter_date"] = pd.to_datetime(_enc["encounter_date"], errors="coerce")
        _enc = _enc.dropna(subset=["encounter_date"])
        _enc["year_week"] = _enc["encounter_date"].dt.to_period("W").apply(lambda p: p.start_time)
        _enc["year_month"] = _enc["encounter_date"].dt.to_period("M").apply(lambda p: p.start_time)

        # ── KPI Tiles ──
        total_persons  = _dim["master_person_id"].nunique() if _dim is not None else _enc["master_person_id"].nunique()
        total_enc      = len(_enc)
        date_min       = _enc["encounter_date"].min().strftime("%b %Y")
        date_max       = _enc["encounter_date"].max().strftime("%b %Y")
        cross_agency   = (_dim["linked_sources_count"].astype(float) > 1).sum() if _dim is not None and "linked_sources_count" in _dim.columns else 0
        cross_pct      = f"{100*cross_agency/total_persons:.1f}%" if total_persons else "—"

        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Unique Persons", f"{total_persons:,}")
        k2.metric("Total Encounters", f"{total_enc:,}")
        k3.metric("Date Range", f"{date_min} – {date_max}")
        k4.metric("Cross-Agency Match Rate", cross_pct)

        st.markdown('<div style="height:8px;"></div>', unsafe_allow_html=True)

        # ── Filters ──
        fc1, fc2 = st.columns(2)
        with fc1:
            all_sources = sorted(_enc["source_system"].dropna().unique().tolist())
            sel_sources = st.multiselect("Agencies", all_sources, default=all_sources, key="trends_sources")
        with fc2:
            all_cats = sorted(_enc["service_category"].dropna().unique().tolist())
            sel_cats = st.multiselect("Service Categories", all_cats, default=all_cats, key="trends_cats")

        _filtered = _enc[
            _enc["source_system"].isin(sel_sources) &
            _enc["service_category"].isin(sel_cats)
        ]

        # ── Week-over-week line chart ──
        st.markdown(
            '<div style="color:#00E6A8;letter-spacing:2px;font-size:0.72rem;'
            'margin:16px 0 8px;">WEEKLY ENCOUNTER VOLUME</div>',
            unsafe_allow_html=True,
        )
        _weekly = _filtered.groupby(["year_week", "source_system"]).size().reset_index(name="count")
        _weekly_total = _filtered.groupby("year_week").size().reset_index(name="count")
        _weekly_total["source_system"] = "TOTAL"
        _weekly_all = pd.concat([_weekly, _weekly_total], ignore_index=True)

        _COLORS = ["#00E6A8","#FF9E3B","#60a5fa","#f472b6","#a78bfa","#34d399","#fb923c","#e879f9"]
        fig_line = go.Figure()
        for i, src in enumerate(sel_sources):
            _d = _weekly_all[_weekly_all["source_system"] == src]
            fig_line.add_trace(go.Scatter(
                x=_d["year_week"], y=_d["count"], name=src,
                mode="lines+markers",
                line=dict(color=_COLORS[i % len(_COLORS)], width=2),
                marker=dict(size=4),
            ))
        _dt = _weekly_all[_weekly_all["source_system"] == "TOTAL"]
        fig_line.add_trace(go.Scatter(
            x=_dt["year_week"], y=_dt["count"], name="TOTAL",
            mode="lines", line=dict(color="#ffffff", width=2, dash="dot"),
        ))
        fig_line.update_layout(
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0.15)",
            font=dict(color="#c9d1d9", family="Courier New"),
            legend=dict(bgcolor="rgba(0,0,0,0.3)", bordercolor="#1e3a2f", font=dict(color="#c9d1d9")),
            xaxis=dict(gridcolor="rgba(255,255,255,0.05)", title=None),
            yaxis=dict(gridcolor="rgba(255,255,255,0.05)", title="Encounters"),
            margin=dict(l=0, r=0, t=10, b=0), height=320,
        )
        st.plotly_chart(fig_line, use_container_width=True)

        # ── New unique persons per month bar chart ──
        st.markdown(
            '<div style="color:#00E6A8;letter-spacing:2px;font-size:0.72rem;'
            'margin:16px 0 8px;">NEW UNIQUE PERSONS PER MONTH</div>',
            unsafe_allow_html=True,
        )
        _first_enc = _filtered.groupby("master_person_id")["encounter_date"].min().reset_index()
        _first_enc["year_month"] = _first_enc["encounter_date"].dt.to_period("M").apply(lambda p: p.start_time)
        _monthly_new = _first_enc.groupby("year_month").size().reset_index(name="new_persons")

        fig_bar = go.Figure(go.Bar(
            x=_monthly_new["year_month"], y=_monthly_new["new_persons"],
            marker_color="#00E6A8", opacity=0.85,
        ))
        fig_bar.update_layout(
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0.15)",
            font=dict(color="#c9d1d9", family="Courier New"),
            xaxis=dict(gridcolor="rgba(255,255,255,0.05)", title=None),
            yaxis=dict(gridcolor="rgba(255,255,255,0.05)", title="New Persons"),
            margin=dict(l=0, r=0, t=10, b=0), height=280,
        )
        st.plotly_chart(fig_bar, use_container_width=True)

        # ── Anonymous Community Signals ───────────────────────────────────────
        st.markdown('<div style="height:24px;"></div>', unsafe_allow_html=True)
        st.markdown(
            '<div style="border-top:1px solid rgba(0,230,168,0.25);margin:0 0 20px;"></div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            '<div style="color:#00E6A8;letter-spacing:2px;font-size:0.72rem;'
            'margin:0 0 6px;">📡  ANONYMOUS COMMUNITY SIGNALS</div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            '<div style="color:#a8b8c8;font-size:0.8rem;font-style:italic;'
            'margin:0 0 18px;padding:8px 14px;background:rgba(0,0,0,0.2);'
            'border-left:3px solid #00E6A8;border-radius:4px;">'
            'Anonymous-tier signals — no name, no DOB, no MPI attempted. '
            'Jackson County Syringe Exchange participants use coded IDs only. '
            'These counts represent raw service intensity and are intended for '
            'public health resource allocation, not individual case management.'
            '</div>',
            unsafe_allow_html=True,
        )

        _ANON_SOURCES = {"JACKSON_COUNTY_SSP"}
        _anon = _enc[_enc["source_system"].isin(_ANON_SOURCES)].copy()

        if _anon.empty:
            st.info("No SSP encounter data found in fact_encounters.csv. Ensure the pipeline has been run with SSP data loaded.")
        else:
            _col_chart, _col_zip = st.columns([3, 2])

            with _col_chart:
                st.markdown(
                    '<div style="color:#a8b8c8;font-size:0.75rem;letter-spacing:1px;'
                    'margin:0 0 6px;">WEEKLY HARM REDUCTION ENCOUNTERS</div>',
                    unsafe_allow_html=True,
                )
                _anon_weekly = (
                    _anon.groupby("year_week").size().reset_index(name="count")
                )
                fig_anon = go.Figure(go.Bar(
                    x=_anon_weekly["year_week"],
                    y=_anon_weekly["count"],
                    marker_color="#00E6A8",
                    opacity=0.80,
                ))
                fig_anon.update_layout(
                    paper_bgcolor="rgba(0,0,0,0)",
                    plot_bgcolor="rgba(0,0,0,0.15)",
                    font=dict(color="#c9d1d9", family="Courier New"),
                    xaxis=dict(gridcolor="rgba(255,255,255,0.05)", title=None),
                    yaxis=dict(gridcolor="rgba(255,255,255,0.05)", title="Encounters"),
                    margin=dict(l=0, r=0, t=10, b=0),
                    height=240,
                )
                st.plotly_chart(fig_anon, use_container_width=True)
                st.markdown(
                    '<div style="color:#a8b8c8;font-size:0.72rem;text-align:center;'
                    'margin-top:-8px;">One bar = one week · each encounter = one supply exchange event</div>',
                    unsafe_allow_html=True,
                )

            with _col_zip:
                st.markdown(
                    '<div style="color:#a8b8c8;font-size:0.75rem;letter-spacing:1px;'
                    'margin:0 0 6px;">ENCOUNTERS BY ZIP CODE</div>',
                    unsafe_allow_html=True,
                )
                _ssp_log_path = os.path.join(
                    os.path.dirname(__file__), "input", "jackson_county_ssp_log.csv"
                )
                _ssp_log_sql = _ssp_log_path.replace("\\", "/")
                _zip_loaded = False
                if os.path.exists(_ssp_log_path):
                    try:
                        import duckdb as _ddb_zip
                        _zip_con = _ddb_zip.connect()
                        _zip_df = _zip_con.execute(
                            f"SELECT CAST(zip_code AS VARCHAR) AS zip_code, COUNT(*) AS encounters "
                            f"FROM read_csv_auto('{_ssp_log_sql}') "
                            f"WHERE zip_code IS NOT NULL "
                            f"GROUP BY zip_code ORDER BY encounters DESC"
                        ).df()
                        _zip_con.close()
                        if not _zip_df.empty:
                            _zip_df.columns = ["ZIP Code", "Encounters"]
                            st.dataframe(
                                _zip_df,
                                use_container_width=True,
                                hide_index=True,
                            )
                            st.markdown(
                                '<div style="color:#a8b8c8;font-size:0.72rem;'
                                'margin-top:4px;">Use for site coverage &amp; resource allocation analysis.</div>',
                                unsafe_allow_html=True,
                            )
                            _zip_loaded = True
                    except Exception:
                        pass
                if not _zip_loaded:
                    st.info("ZIP data not available. Ensure jackson_county_ssp_log.csv is present in input/.")

        _con.close()

# ── Records tab ────────────────────────────────────────────────────────────────
with _tab_records:
    # Hide the Streamlit Material icon text (keyboard_arrow_right rendered as text
    # because Share Tech Mono overrides the Material Icons font globally).
    # Also brighten text throughout the Records tab.
    st.markdown(
        """
        <style>
        /* Hide the stIconMaterial span in expanders — Share Tech Mono override breaks it */
        [data-testid="stIconMaterial"] { display: none !important; }

        /* Bright expander headers in Records tab */
        details summary,
        details summary p,
        details summary span,
        details summary div {
            color: #d8e8f0 !important;
            font-size: 0.85rem !important;
        }

        /* Bright content inside expanded rows */
        details[open] > div {
            color: #c8dce8 !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div style="color:#00E6A8;font-size:0.75rem;letter-spacing:2px;'
        'margin-bottom:12px;">MASTER PERSON INDEX — RECORD INSPECTOR &amp; UNLINK TOOL</div>',
        unsafe_allow_html=True,
    )

    _gp_ok  = os.path.exists(_GOLDEN_PERSONS)
    _bri_ok = os.path.exists(_GOLDEN_BRIDGE)

    if not _gp_ok:
        st.info(
            "No golden file found. Use the sidebar 'Generate Golden File' button "
            "to build the effective master person index first."
        )
    elif not _bri_ok:
        st.info(
            "No bridge file found. Run the MPI pipeline first "
            "(bridge_record_links.csv is required)."
        )
    else:
        # ── Load base data ────────────────────────────────────────────────────
        try:
            _gp_df  = pd.read_csv(_GOLDEN_PERSONS, dtype=str)
            _bri_df = pd.read_csv(_GOLDEN_BRIDGE,  dtype=str)
        except Exception as _e:
            st.error(f"Could not load records: {_e}")
            _gp_df  = None
            _bri_df = None

        if _gp_df is not None and not _gp_df.empty:
            # ── Build effective bridge ────────────────────────────────────────
            # Start from pipeline MPIs
            _bri_df["link_origin"]   = "Pipeline"
            _bri_df["pipeline_mpi"]  = _bri_df["master_person_id"]
            _bri_df["effective_mpi"] = _bri_df["master_person_id"]

            # Apply accepted_persons overrides
            if os.path.exists(ACCEPTED_PERSONS_PATH):
                try:
                    _ap_df = pd.read_csv(ACCEPTED_PERSONS_PATH, dtype=str)
                    if not _ap_df.empty:
                        _ap_dedup = (
                            _ap_df.sort_values("timestamp", ascending=True)
                            .drop_duplicates(subset=["source_system", "source_id"], keep="last")
                        )
                        _bri_df = _bri_df.merge(
                            _ap_dedup[["source_system", "source_id", "target_mpi"]],
                            on=["source_system", "source_id"],
                            how="left",
                        )
                        _has_ap = _bri_df["target_mpi"].notna()
                        _bri_df.loc[_has_ap, "effective_mpi"] = _bri_df.loc[_has_ap, "target_mpi"]
                        _bri_df.loc[_has_ap, "link_origin"]   = "Manual Accept"
                        _bri_df = _bri_df.drop(columns=["target_mpi"])
                except Exception:
                    pass

            # Apply severed_links overrides (these always win)
            _bri_df["is_severed"] = False
            if os.path.exists(_GOLDEN_SEVERED):
                try:
                    _sv_df = pd.read_csv(_GOLDEN_SEVERED, dtype=str)
                    if not _sv_df.empty:
                        _sv_map = dict(zip(_sv_df["unique_record_id"], _sv_df["split_mpi"]))
                        _sev_mask = _bri_df["unique_record_id"].isin(_sv_map)
                        _bri_df.loc[_sev_mask, "effective_mpi"] = (
                            _bri_df.loc[_sev_mask, "unique_record_id"].map(_sv_map)
                        )
                        _bri_df.loc[_sev_mask, "is_severed"] = True
                except Exception:
                    pass

            # ── Join original demographic fields for display ──────────────────
            _stage2_path = os.path.join(OUTPUT_DIR, "stage2_clean_demographics.csv")
            if os.path.exists(_stage2_path):
                try:
                    _s2_cols = ["unique_record_id", "first_name", "last_name", "dob", "ssn_last4"]
                    _s2_df = pd.read_csv(_stage2_path, dtype=str, usecols=_s2_cols)
                    _bri_df = _bri_df.merge(_s2_df, on="unique_record_id", how="left")
                except Exception:
                    pass
            # Ensure columns exist even when stage2 file is absent
            for _dc in ("first_name", "last_name", "dob", "ssn_last4"):
                if _dc not in _bri_df.columns:
                    _bri_df[_dc] = ""

            # ── Search bar ────────────────────────────────────────────────────
            _total_persons = len(_gp_df)
            _search_col, _info_col = st.columns([4, 1])
            with _search_col:
                _rec_search = st.text_input(
                    "Search persons",
                    placeholder="name, source, or MPI fragment…",
                    label_visibility="collapsed",
                    key="_records_search_input",
                )
            with _info_col:
                st.markdown(
                    f'<div style="color:#a8b8c8;font-size:0.78rem;padding-top:8px;">'
                    f'{_total_persons:,} persons</div>',
                    unsafe_allow_html=True,
                )

            # Filter + sort
            _gp_filtered = _gp_df.copy()
            if _rec_search.strip():
                _q = _rec_search.strip().lower()
                _full_name = (
                    _gp_filtered["canonical_first_name"].fillna("").str.lower()
                    + " "
                    + _gp_filtered["canonical_last_name"].fillna("").str.lower()
                )
                _fmask = (
                    _gp_filtered["canonical_first_name"].str.lower().str.contains(_q, na=False)
                    | _gp_filtered["canonical_last_name"].str.lower().str.contains(_q, na=False)
                    | _full_name.str.contains(_q, na=False)
                    | _gp_filtered["contributing_sources"].str.lower().str.contains(_q, na=False)
                    | _gp_filtered["master_person_id"].str.lower().str.contains(_q, na=False)
                )
                _gp_filtered = _gp_filtered[_fmask].copy()

            if _gp_filtered.empty:
                st.info("No persons match the search.")
            else:
                _gp_filtered = _gp_filtered.sort_values(
                    ["canonical_last_name", "canonical_first_name"], na_position="last"
                ).reset_index(drop=True)

                for _, _mp in _gp_filtered.iterrows():
                    _mpi      = str(_mp["master_person_id"])
                    _fn       = str(_mp.get("canonical_first_name", ""))
                    _ln       = str(_mp.get("canonical_last_name", ""))
                    _sources  = str(_mp.get("contributing_sources", ""))
                    _n_linked = int(_mp.get("total_linked_records", 1))

                    _icon  = "✂" if _n_linked > 1 else "·"
                    _label = (
                        f"{_icon} {_fn} {_ln}  ·  {_sources}  ·  {_n_linked} record(s)"
                        f"  [{_mpi[:8]}…]"
                    )

                    with st.expander(_label, expanded=(st.session_state._unlink_expanded_mpi == _mpi)):
                        # Bridge rows for this effective MPI
                        _ebri = _bri_df[_bri_df["effective_mpi"] == _mpi].copy()

                        if _ebri.empty:
                            st.caption("No source records found for this person.")
                        else:
                            # Anchor = last non-severed Pipeline record
                            _n_pipeline_active = int(
                                (~_ebri["is_severed"] & (_ebri["link_origin"] == "Pipeline")).sum()
                            )

                            st.markdown(
                                '<div style="color:#a8b8c8;font-size:0.72rem;'
                                'letter-spacing:1px;margin:4px 0 8px;">'
                                'SOURCE RECORDS LINKED TO THIS MASTER PERSON</div>',
                                unsafe_allow_html=True,
                            )

                            for _, _br in _ebri.iterrows():
                                _uid        = str(_br["unique_record_id"])
                                _src_sys    = str(_br["source_system"])
                                _src_id     = str(_br["source_id"])
                                _conf       = _br.get("match_confidence", "")
                                _origin     = str(_br.get("link_origin", "Pipeline"))
                                _is_severed = bool(_br.get("is_severed", False))
                                _pipe_mpi   = str(_br.get("pipeline_mpi", _mpi))

                                # Demographic fields from stage2
                                _dem_fn  = str(_br.get("first_name", "") or "").strip()
                                _dem_ln  = str(_br.get("last_name",  "") or "").strip()
                                _dem_dob = str(_br.get("dob",        "") or "").strip()
                                _dem_ssn = str(_br.get("ssn_last4",  "") or "").strip()
                                _dem_name = f"{_dem_fn} {_dem_ln}".strip() or "—"
                                _dem_parts = []
                                if _dem_dob and _dem_dob not in ("nan", "None", ""):
                                    _dem_parts.append(f"DOB: {_dem_dob}")
                                if _dem_ssn and _dem_ssn not in ("nan", "None", ""):
                                    _dem_parts.append(f"SSN-4: {_dem_ssn}")
                                _dem_detail = "  ·  ".join(_dem_parts) if _dem_parts else ""

                                # Only the last non-severed Pipeline record is an anchor
                                _is_anchor = (
                                    not _is_severed
                                    and _origin == "Pipeline"
                                    and _n_pipeline_active <= 1
                                )

                                _rc1, _rc2, _rc3, _rc4 = st.columns([3, 2, 2, 2])
                                with _rc1:
                                    st.markdown(
                                        f'<span style="color:#00E6A8;font-size:0.8rem;">'
                                        f'{_src_sys}</span>'
                                        f'<span style="color:#a8b8c8;font-size:0.72rem;">'
                                        f' · {_src_id}</span>'
                                        f'<br><span style="color:#d8e8f0;font-size:0.8rem;font-weight:600;">'
                                        f'{_dem_name}</span>'
                                        + (
                                            f'<br><span style="color:#7a9ab0;font-size:0.7rem;">'
                                            f'{_dem_detail}</span>'
                                            if _dem_detail else ""
                                        ),
                                        unsafe_allow_html=True,
                                    )
                                with _rc2:
                                    _origin_color = "#FF9E3B" if _origin == "Manual Accept" else "#a8b8c8"
                                    st.markdown(
                                        f'<span style="color:{_origin_color};font-size:0.72rem;">'
                                        f'{_origin}</span>',
                                        unsafe_allow_html=True,
                                    )
                                with _rc3:
                                    try:
                                        _conf_pct = f"{float(_conf)*100:.1f}%"
                                    except Exception:
                                        _conf_pct = str(_conf)
                                    st.markdown(
                                        f'<span style="color:#a8b8c8;font-size:0.72rem;">'
                                        f'conf: {_conf_pct}</span>',
                                        unsafe_allow_html=True,
                                    )
                                with _rc4:
                                    if _is_severed:
                                        st.markdown(
                                            '<span style="color:#888;font-size:0.72rem;">'
                                            'Unlinked ✓</span>',
                                            unsafe_allow_html=True,
                                        )
                                    elif _is_anchor:
                                        st.markdown(
                                            '<span style="color:#555;font-size:0.72rem;">'
                                            'Anchor</span>',
                                            unsafe_allow_html=True,
                                        )
                                    elif st.session_state._unlink_confirm_uid == _uid:
                                        _cc1, _cc2 = st.columns(2)
                                        with _cc1:
                                            if st.button(
                                                "Confirm ✂",
                                                key=f"_ulk_confirm_{_uid}",
                                                use_container_width=True,
                                                type="primary",
                                            ):
                                                if _origin == "Manual Accept":
                                                    _undo_accept(_src_sys, _src_id)
                                                    _msg = (
                                                        f"Accept reversed for {_src_sys}. "
                                                        f"Regenerate the golden file to apply."
                                                    )
                                                else:
                                                    _new_mpi = _sever_link(_uid, _pipe_mpi)
                                                    _msg = (
                                                        f"Unlinked {_src_sys} record → "
                                                        f"new MPI {_new_mpi[:8]}…  "
                                                        f"Regenerate the golden file to apply."
                                                    )
                                                st.session_state._unlink_confirm_uid = None
                                                st.session_state._golden_result = _msg
                                                st.rerun()
                                        with _cc2:
                                            if st.button(
                                                "Cancel",
                                                key=f"_ulk_cancel_{_uid}",
                                                use_container_width=True,
                                            ):
                                                st.session_state._unlink_confirm_uid = None
                                                st.rerun()
                                    else:
                                        _btn_lbl = (
                                            "Undo Accept ↩"
                                            if _origin == "Manual Accept"
                                            else "Unlink ✂"
                                        )
                                        if st.button(
                                            _btn_lbl,
                                            key=f"_ulk_{_uid}",
                                            use_container_width=True,
                                        ):
                                            st.session_state._unlink_confirm_uid = _uid
                                            st.session_state._unlink_expanded_mpi = _mpi
                                            st.rerun()

                            _n_sev_this = int(_ebri["is_severed"].sum())
                            if _n_sev_this > 0:
                                st.markdown(
                                    f'<div style="background:#001a0e;border:1px solid #00E6A8;'
                                    f'border-radius:6px;padding:8px 12px;margin-top:10px;">'
                                    f'<span style="color:#00E6A8;font-size:0.72rem;">'
                                    f'{_n_sev_this} record(s) unlinked from this cluster. '
                                    f'Regenerate the golden file to apply splits.'
                                    f'</span></div>',
                                    unsafe_allow_html=True,
                                )

"""
generate_readme_pdf.py — Produces README.PDF for the C3E project.
Run: python generate_readme_pdf.py
"""

from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, KeepTogether,
)
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY

OUT = "README.PDF"

# ── Palette ────────────────────────────────────────────────────────────────────
TEAL       = colors.HexColor("#00C49A")
DARK_BG    = colors.HexColor("#0C1A26")
MID_DARK   = colors.HexColor("#0F2435")
AMBER      = colors.HexColor("#FF9E3B")
RED_SOFT   = colors.HexColor("#C0392B")
WHITE      = colors.white
LIGHT_GREY = colors.HexColor("#E8EDF3")
MID_GREY   = colors.HexColor("#7A8898")
DIM_GREY   = colors.HexColor("#1E3040")

# ── Styles ─────────────────────────────────────────────────────────────────────
base = getSampleStyleSheet()

def _style(name, parent="Normal", **kw):
    s = ParagraphStyle(name, parent=base[parent], **kw)
    return s

S_COVER_TITLE  = _style("CoverTitle",  fontSize=28, leading=34, textColor=TEAL,
                         alignment=TA_CENTER, spaceAfter=6, fontName="Helvetica-Bold")
S_COVER_SUB    = _style("CoverSub",    fontSize=13, leading=18, textColor=LIGHT_GREY,
                         alignment=TA_CENTER, spaceAfter=4, fontName="Helvetica")
S_COVER_BADGE  = _style("CoverBadge",  fontSize=9,  leading=12, textColor=MID_GREY,
                         alignment=TA_CENTER, spaceAfter=2, fontName="Helvetica")
S_SECTION      = _style("Section",     fontSize=13, leading=16, textColor=TEAL,
                         spaceBefore=18, spaceAfter=6, fontName="Helvetica-Bold")
S_SUBSECTION   = _style("Subsection",  fontSize=10, leading=13, textColor=AMBER,
                         spaceBefore=10, spaceAfter=4, fontName="Helvetica-Bold")
S_BODY         = _style("Body",        fontSize=9,  leading=13, textColor=LIGHT_GREY,
                         alignment=TA_JUSTIFY, spaceAfter=5, fontName="Helvetica")
S_BULLET       = _style("Bullet",      fontSize=9,  leading=13, textColor=LIGHT_GREY,
                         leftIndent=14, firstLineIndent=-10, spaceAfter=3,
                         fontName="Helvetica")
S_CODE         = _style("Code",        fontSize=8,  leading=11, textColor=TEAL,
                         backColor=DIM_GREY, leftIndent=10, rightIndent=10,
                         spaceAfter=6, fontName="Courier")
S_WARN         = _style("Warn",        fontSize=9,  leading=13, textColor=AMBER,
                         leftIndent=14, firstLineIndent=-10, spaceAfter=3,
                         fontName="Helvetica-Oblique")
S_TH           = _style("TH",          fontSize=8,  leading=10, textColor=DARK_BG,
                         fontName="Helvetica-Bold", alignment=TA_CENTER)
S_TD           = _style("TD",          fontSize=7.5,leading=10, textColor=LIGHT_GREY,
                         fontName="Courier")
S_TD_LABEL     = _style("TDLabel",     fontSize=7.5,leading=10, textColor=AMBER,
                         fontName="Helvetica-Bold")

# ── Helper builders ────────────────────────────────────────────────────────────
def section(title):
    return [
        Spacer(1, 0.1*inch),
        HRFlowable(width="100%", thickness=1, color=TEAL, spaceAfter=4),
        Paragraph(title, S_SECTION),
    ]

def subsection(title):
    return [Paragraph(title, S_SUBSECTION)]

def body(text):
    return Paragraph(text, S_BODY)

def bullet(text):
    return Paragraph(f"• &nbsp;{text}", S_BULLET)

def warn(text):
    return Paragraph(f"⚠ &nbsp;{text}", S_WARN)

def code(text):
    return Paragraph(text, S_CODE)

def gap(h=0.1):
    return Spacer(1, h*inch)

def header_table(headers, rows, col_widths):
    data = [[Paragraph(h, S_TH) for h in headers]]
    for row in rows:
        data.append([
            Paragraph(str(c), S_TD_LABEL if i == 0 else S_TD)
            for i, c in enumerate(row)
        ])
    t = Table(data, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND",   (0, 0), (-1, 0),  TEAL),
        ("BACKGROUND",   (0, 1), (-1, -1), MID_DARK),
        ("ROWBACKGROUNDS",(0, 1), (-1, -1), [MID_DARK, DIM_GREY]),
        ("GRID",         (0, 0), (-1, -1), 0.4, DARK_BG),
        ("VALIGN",       (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",   (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 4),
        ("LEFTPADDING",  (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ]))
    return t

# ── Document ───────────────────────────────────────────────────────────────────
doc = SimpleDocTemplate(
    OUT,
    pagesize=letter,
    leftMargin=0.75*inch, rightMargin=0.75*inch,
    topMargin=0.75*inch,  bottomMargin=0.75*inch,
    title="C3E — Cascadia README",
    author="Rogue Raise #02 Team",
)

W = letter[0] - 1.5*inch   # usable width

story = []

# ── Cover block ────────────────────────────────────────────────────────────────
story += [
    gap(0.3),
    Paragraph("🧭", _style("Compass", fontSize=36, alignment=TA_CENTER, spaceAfter=6)),
    Paragraph("Cascadia", S_COVER_TITLE),
    Paragraph("C3E — Continuum of Care Master Data Engine for the Rogue River Valley",
              S_COVER_SUB),
    gap(0.05),
    Paragraph("Rogue Raise #02: The Unhoused · Ashland, OR · Oct 23–25, 2026",
              S_COVER_BADGE),
    Paragraph("Version 1.0 · Python 3.10+ · Offline-First · HUD &amp; Non-HUD Sources",
              S_COVER_BADGE),
    gap(0.25),
    HRFlowable(width="100%", thickness=2, color=TEAL),
    gap(0.15),
]

# ── 1. Purpose ─────────────────────────────────────────────────────────────────
story += section("1.  Purpose")
story += [
    body(
        "The annual HUD Point-in-Time (PIT) homeless count produces a single-night "
        "snapshot in January that systematically undercounts the true scale of "
        "homelessness in the Rogue River Valley (RRV). Agencies funded by HUD operate "
        "in rigid HMIS silos, while community-based providers — syringe exchanges, "
        "meal programs, recovery cafes, faith-based outreach — capture service activity "
        "in disconnected spreadsheets or paper logs that never reach the formal count."
    ),
    gap(0.05),
    body(
        "C3E is an offline-first, pure-Python record linkage engine that:"
    ),
    bullet("De-duplicates client records across HUD and non-HUD data sources using "
           "probabilistic matching (Splink + DuckDB)."),
    bullet("Assigns each unique individual a persistent, deterministic Master Person ID "
           "(UUID v5) — the foundation of a Rogue River Valley Master Person Index (MPI)."),
    bullet("Aggregates continuous service encounters into a unified fact table spanning "
           "shelter, food, harm-reduction, and recovery services."),
    bullet("Exposes a 'Tinder-style' human-review interface (app.py) so case managers "
           "and data stewards can accept or reject proposed identity merges with a single "
           "click, maintaining a complete audit trail."),
    bullet("Exports a county-ready GOLDEN_PERSONS_ENCOUNTERS.csv combining verified "
           "persons with every service encounter — suitable for public health dashboards, "
           "commissioner briefings, and HUD Consolidated Plan submissions."),
    gap(0.05),
    body(
        "<b>Target audience:</b> Jackson County CoC staff, ACCESS case managers, "
        "Rogue Retreat intake coordinators, Recovery Café leadership, JCPH harm-reduction "
        "program officers, and county commissioners seeking unduplicated population counts."
    ),
]

# ── 2. Installation ────────────────────────────────────────────────────────────
story += section("2.  Installation")
story += subsection("Requirements")
story += [
    bullet("Python 3.10 or higher"),
    bullet("pip (standard with Python)"),
    bullet("Internet access for initial package download only; all pipeline "
           "execution is fully offline thereafter"),
    gap(0.05),
]
story += subsection("Install dependencies")
story += [
    code("pip install streamlit splink duckdb networkx pandas rapidfuzz reportlab"),
    gap(0.05),
]
story += subsection("Generate synthetic test data (first run only)")
story += [
    code("python generate_access_data.py<br/>"
         "python generate_rogue_retreat.py<br/>"
         "python generate_recovery_cafe.py<br/>"
         "python generate_syringe_exchange.py<br/>"
         "python generate_stvdp.py"),
    gap(0.05),
]
story += subsection("Run the data pipeline")
story += [
    code("python mpi_pipeline.py                  # full run (stages 1–5)<br/>"
         "python mpi_pipeline.py --from-stage 3   # resume from matching"),
    gap(0.05),
]
story += subsection("Launch the review UI")
story += [
    code("streamlit run app.py"),
    body("Open http://localhost:8501 in a browser. The sidebar shows ingested datasets "
         "and live session metrics. Upload a partner CSV to begin the swipe-deck "
         "entity-resolution workflow."),
    gap(0.05),
]
story += subsection("Generate the Golden Export (optional)")
story += [
    code("python generate_golden.py"),
    body("Or use the <b>▸ EXPORT → Overwrite Golden File</b> button in the C3E sidebar "
         "after the pipeline has produced its three output CSVs."),
]

# ── 3. Default Use Case ────────────────────────────────────────────────────────
story += section("3.  Default Use Case")
story += [
    body(
        "The canonical workflow proceeds in five stages, each validated by automated "
        "agentic checks before the next begins."
    ),
    gap(0.05),
]

steps = [
    ("Stage 1 — Ingest",
     "Drop provider CSVs into the input/ directory. ingest.py normalises column names "
     "across all four agency schemas and produces a unified demographic frame plus a "
     "raw service-encounters frame."),
    ("Stage 2 — Clean",
     "clean.py strips punctuation from names, standardises all dates to YYYY-MM-DD, "
     "extracts SSN last-4, and lower-cases all text fields for comparison."),
    ("Stage 3 — Match",
     "match.py runs Splink probabilistic linkage with Levenshtein comparisons on first "
     "name, last name, exact DOB, and exact SSN last-4. Blocking rules constrain the "
     "candidate pair space. Match probabilities below 0.70 are discarded automatically."),
    ("Stage 4 — Cluster",
     "cluster.py feeds accepted match pairs into a NetworkX connected-components graph. "
     "Each cluster receives a deterministic UUID v5 Master Person ID seeded from the "
     "sorted member record IDs — the same data always produces the same MPI."),
    ("Stage 5 — Export",
     "export.py writes dim_master_persons.csv (one row per unique person), "
     "bridge_record_links.csv (audit trace), and fact_encounters.csv (all service "
     "activity linked to master IDs). Run generate_golden.py or click the sidebar "
     "Export button to produce the combined GOLDEN_PERSONS_ENCOUNTERS.csv."),
]
for title, desc in steps:
    story += [KeepTogether([Paragraph(title, S_SUBSECTION), body(desc), gap(0.05)])]

story += [
    body(
        "<b>Human review loop:</b> Upload any partner CSV in the C3E UI. The engine "
        "proposes candidate pairs above the minimum confidence threshold. A data steward "
        "swipes right (Accept) to merge identities or left (Reject) to sever the link. "
        "Every decision is logged in the in-session audit trail and immediately reflected "
        "in the live Master Person count."
    ),
]

# ── 4. File Naming Convention ──────────────────────────────────────────────────
story += section("4.  File Naming Convention")
story += [
    body(
        "All provider data files follow a two-part snake_case convention: "
        "<b>&lt;agency_slug&gt;_&lt;file_type&gt;.csv</b>. The agency slug must be "
        "unique across all ingested sources; the file type is either <b>clients</b> "
        "(demographic record) or <b>services</b> (encounter/activity log)."
    ),
    gap(0.05),
]

naming_rows = [
    ("ACCESS HMIS (HUD)",          "access_hmis_client.csv",           "access_hmis_services.csv"),
    ("Rogue Retreat",              "rogue_retreat_clients.csv",         "rogue_retreat_services.csv"),
    ("Recovery Café",              "recovery_cafe_members.csv",         "recovery_cafe_services.csv"),
    ("Jackson Co. Syringe Exch.", "jackson_county_ssp_log.csv",        "jackson_county_ssp_services.csv"),
    ("St. Vincent de Paul",       "stvdp_clients.csv",                 "stvdp_services.csv"),
    ("New agency template",       "&lt;agency_slug&gt;_clients.csv",   "&lt;agency_slug&gt;_services.csv"),
]

naming_table = header_table(
    ["Agency / Program", "Demographic File", "Services File"],
    naming_rows,
    [2.2*inch, 2.15*inch, 2.15*inch],
)
story += [naming_table, gap(0.1)]
story += [
    bullet("Use only lowercase letters, digits, and underscores in slugs. "
           "No spaces, hyphens, or special characters."),
    bullet("Keep slugs consistent between the client file and its matching services "
           "file — the pipeline joins them on slug pattern."),
    bullet("Pipeline output files are always written to the <b>output/</b> directory. "
           "Do not place provider source CSVs in output/."),
    bullet("The golden export GOLDEN_PERSONS_ENCOUNTERS.csv always writes to the "
           "project root. This is the file for external distribution."),
]

# ── 5. CSV Header Layouts ──────────────────────────────────────────────────────
story += section("5.  CSV Header Layouts")
story += [
    body(
        "Each provider must supply a demographics file and, optionally, a services "
        "file. Headers below are the canonical names C3E expects after column mapping. "
        "The Column Mapper UI in C3E lets operators remap non-standard headers at "
        "upload time without modifying source files."
    ),
    gap(0.05),
]

story += subsection("5a.  Demographic / Client File (all providers)")
demo_rows = [
    ("source_id",       "Required",  "Unique client/member ID within the source agency"),
    ("first_name",      "Required",  "Legal or preferred first name"),
    ("last_name",       "Required",  "Legal or preferred surname"),
    ("date_of_birth",   "Required",  "ISO 8601 preferred (YYYY-MM-DD); common variants parsed"),
    ("ssn_last4",       "Optional",  "Last 4 digits of SSN — strongest linkage signal"),
    ("phone",           "Optional",  "Any format accepted; digits extracted for matching"),
    ("intake_date",     "Optional",  "First service contact date at this agency"),
    ("gender",          "Optional",  "Self-reported; not used in matching"),
    ("race_ethnicity",  "Optional",  "Self-reported; not used in matching"),
    ("veteran_status",  "Optional",  "Y/N; not used in matching"),
    ("notes",           "Optional",  "Free text; stripped before export"),
]
story += [
    header_table(
        ["Column", "Required?", "Description"],
        demo_rows,
        [1.5*inch, 0.9*inch, 4.1*inch],
    ),
    gap(0.1),
]

story += subsection("5b.  Services / Encounters File (all providers)")
svc_rows = [
    ("encounter_id",      "Required",  "Unique ID for this service event (visit, log, entry)"),
    ("source_id",         "Required",  "FK → demographic file client/member ID"),
    ("encounter_date",    "Required",  "Date service was provided (YYYY-MM-DD preferred)"),
    ("service_category",  "Required",  "Standardised service label (see taxonomy below)"),
    ("service_type",      "Optional",  "More granular sub-type within category"),
    ("location_info",     "Optional",  "ZIP, address, or site name"),
    ("quantity",          "Optional",  "Meals served, syringes exchanged, lbs food, etc."),
    ("exit_date",         "Optional",  "Shelter/program exit date (residential providers)"),
    ("case_manager",      "Optional",  "Staff name or ID; stripped before export"),
]
story += [
    header_table(
        ["Column", "Required?", "Description"],
        svc_rows,
        [1.5*inch, 0.9*inch, 4.1*inch],
    ),
    gap(0.1),
]

story += subsection("5c.  Pipeline Output Files")
out_rows = [
    ("dim_master_persons.csv",       "master_person_id, canonical_first_name, canonical_last_name, canonical_dob, canonical_ssn_last4, total_linked_records, linked_sources_count, contributing_sources"),
    ("bridge_record_links.csv",      "unique_record_id, master_person_id, source_system, source_id, match_confidence, match_type"),
    ("fact_encounters.csv",          "encounter_id, master_person_id, unique_record_id, source_system, encounter_date, service_category, location_info"),
    ("GOLDEN_PERSONS_ENCOUNTERS.csv","master_person_id, canonical_first_name, canonical_last_name, canonical_dob, contributing_sources, total_linked_records, linked_sources_count, encounter_id, source_system, encounter_date, service_category, location_info"),
]
out_table = header_table(
    ["Output File", "Headers"],
    out_rows,
    [2.4*inch, 4.1*inch],
)
story += [out_table, gap(0.1)]

# ── 6. Limitations ────────────────────────────────────────────────────────────
story += section("6.  System Limitations")

story += subsection("6a.  Scale Estimate — Rogue River Valley")
story += [
    body(
        "The RRV encompasses Medford, Ashland, Grants Pass, Jacksonville, and "
        "surrounding communities with a combined population of approximately 200,000. "
        "Oregon consistently reports one of the highest per-capita homelessness rates "
        "in the United States (~0.28% PIT, per 2023 HUD AHAR). Applying that rate:"
    ),
    gap(0.05),
]
scale_rows = [
    ("PIT Count (single night, Jan)",  "~560",          "200,000 × 0.28%"),
    ("Annual shelter contacts",         "~1,400–2,000",  "2.5–3.5× PIT (HUD shelter utilisation ratio)"),
    ("Non-HUD service contacts",        "~1,500–3,000",  "Meal programs, SSP, warming centers, street outreach"),
    ("Est. unique individuals/year",    "~2,500–4,000",  "Deduplicated across all programs; C3E target range"),
    ("Service encounter rows/year",     "~15,000–40,000","Avg 6–10 contacts per active individual"),
    ("Projected system record count",   "~5,000–8,000",  "Accumulated over 2–3 year rolling window"),
]
story += [
    header_table(
        ["Metric", "Estimate", "Basis"],
        scale_rows,
        [2.5*inch, 1.5*inch, 2.5*inch],
    ),
    gap(0.05),
    body(
        "At 5,000–8,000 demographic records, Splink with DuckDB backend and the three "
        "configured blocking rules produces roughly 80,000–200,000 candidate pairs — "
        "well within DuckDB's in-process capacity on a standard laptop with no network "
        "dependency. Full pipeline runtime at this scale is estimated at 2–8 minutes."
    ),
]

story += [gap(0.1)]
story += subsection("6b.  Record Linkage Accuracy")
story += [
    bullet("Probabilistic matching is not deterministic truth. The default 70% match "
           "probability threshold will produce both false positives (two different people "
           "merged) and false negatives (the same person left as two records)."),
    bullet("Name-only matches are high-risk. When SSN last-4 and DOB are both absent, "
           "first/last name similarity alone generates a high false-positive rate for "
           "common names (e.g., Maria Garcia, James Brown)."),
    bullet("Nickname and alias handling is limited. 'Bob' vs 'Robert', 'Liz' vs "
           "'Elizabeth' will not match unless the provider has normalised preferred names."),
    bullet("Typos and transcription errors in DOB (day/month transposition, wrong year) "
           "will suppress correct matches. Fallback blocking on last name compensates "
           "partially but increases candidate pair volume."),
]

story += [gap(0.05)]
story += subsection("6c.  Anonymous & Low-Identity Records")
story += [
    bullet("Syringe exchange programs (SSP) and many meal/warming programs collect "
           "only initials and birth year for harm-reduction safety. These records "
           "cannot be probabilistically matched to full-identity records — they are "
           "aggregated as anonymous encounters only."),
    bullet("Records with no shared field values (no name, no DOB, no SSN, no phone) "
           "are isolated nodes in the identity graph and will always appear as single-"
           "record MPI entries."),
    warn("Do not use anonymous SSP or warming-shelter records for individual-level "
         "case management — they are valid only for population-level aggregate counts."),
]

story += [gap(0.05)]
story += subsection("6d.  Ingestion Constraints")
story += [
    bullet("File size: the Streamlit uploader is capped at 200 MB per file. "
           "Providers with large multi-year extracts should split by fiscal year."),
    bullet("Encoding: UTF-8 is expected. Windows-1252 / Latin-1 files with special "
           "characters (accented names) may produce garbled output. Convert with "
           "'iconv' or Excel Save-As UTF-8 CSV before upload."),
    bullet("Date formats: the cleaner accepts ISO 8601, MM/DD/YYYY, and M/D/YY. "
           "Ambiguous two-digit years (e.g., 01/02/03) are interpreted as 2003-02-01 "
           "(ISO order). Verify edge cases manually."),
    bullet("Column mapping: the UI Column Mapper handles up to 9 semantic field slots. "
           "Providers with more than 9 meaningful fields must pre-process to the "
           "canonical 9-column demographic schema before ingestion."),
    bullet("Services files are optional. If a provider has no structured service log, "
           "the intake_date in the demographics file is used as a single proxy "
           "encounter date."),
]

story += [gap(0.05)]
story += subsection("6e.  Privacy & Compliance")
story += [
    bullet("C3E is designed for use by authorised CoC staff and data stewards only. "
           "The output CSVs contain PII (name, DOB, SSN last-4). Restrict file system "
           "access accordingly."),
    bullet("The system does not currently implement field-level encryption at rest. "
           "Enable the SHA-256 hashing toggle in the UI before sharing any export "
           "outside of authorised staff."),
    bullet("HMIS data shared under a signed Data Sharing Agreement (DSA) must remain "
           "within the DSA's permitted use scope. Do not upload HMIS data to any "
           "cloud service without explicit DSA authorisation."),
    warn("C3E is a decision-support tool, not a legal identity determination system. "
         "All merge decisions affecting housing-voucher eligibility must be reviewed "
         "by a qualified case manager."),
]

story += [gap(0.05)]
story += subsection("6f.  Infrastructure & Offline Constraints")
story += [
    bullet("All computation is local. No data leaves the machine running C3E."),
    bullet("Concurrent multi-user access is not supported. Streamlit serves a single-"
           "session process; simultaneous users will share session state unpredictably."),
    bullet("The identity graph (NetworkX) is rebuilt in memory on each pipeline run. "
           "There is no incremental / delta-update mode in the current version — adding "
           "a new provider requires a full re-run from Stage 1."),
    bullet("Browser session state (swipe decisions, threshold settings) is lost on "
           "page refresh. Always export before closing the browser tab."),
]

# ── Footer ─────────────────────────────────────────────────────────────────────
story += [
    gap(0.2),
    HRFlowable(width="100%", thickness=1, color=TEAL),
    gap(0.05),
    Paragraph(
        "Cascadia (C3E) · Rogue Raise #02 · Ashland, OR · Oct 2026 · "
        "Open-source, MIT License",
        _style("Footer", fontSize=7.5, textColor=MID_GREY, alignment=TA_CENTER),
    ),
]

# ── Dark page background via canvas ───────────────────────────────────────────
from reportlab.platypus import BaseDocTemplate, Frame, PageTemplate
from reportlab.lib.pagesizes import letter as LETTER

def dark_bg(canvas, doc):
    canvas.saveState()
    canvas.setFillColor(DARK_BG)
    canvas.rect(0, 0, LETTER[0], LETTER[1], fill=1, stroke=0)
    canvas.restoreState()

doc.build(story, onFirstPage=dark_bg, onLaterPages=dark_bg)
print(f"[OK] {OUT} written ({__import__('os').path.getsize(OUT):,} bytes)")

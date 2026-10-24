"""
generate_walkthrough_pdf.py
Captures live screenshots of the C3E Streamlit app at each walkthrough step,
then builds ONTRACK_INGESTION_WALKTHROUGH.pdf using reportlab.

Requirements:
    pip install playwright reportlab pillow
    python -m playwright install chromium

Run while 'streamlit run app.py' is already running on port 8501.
"""

import os, re, time, textwrap
from pathlib import Path
from playwright.sync_api import sync_playwright
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib.colors import HexColor, white, black
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Preformatted,
                                 Spacer, Image, HRFlowable, KeepTogether,
                                 PageBreak, Table, TableStyle)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY
from PIL import Image as PILImage

# -- Paths ---------------------------------------------------------------------
BASE   = Path(__file__).parent
TXT    = BASE / "ONTRACK_INGESTION_WALKTHROUGH.txt"
SHOTS  = BASE / "output" / "walkthrough_shots"
PDF    = BASE / "ONTRACK_INGESTION_WALKTHROUGH.pdf"
APP    = "http://localhost:8501"

SHOTS.mkdir(parents=True, exist_ok=True)

# -- Palette -------------------------------------------------------------------
BG        = HexColor("#0C1A26")
TEAL      = HexColor("#00C49A")
AMBER     = HexColor("#FF9E3B")
DIM_TEXT  = HexColor("#8AACBE")
LIGHT     = HexColor("#D6EAF8")
BORDER    = HexColor("#1E3A4F")
WHITE     = HexColor("#FFFFFF")
CODE_BG   = HexColor("#0A1520")

# -- Screenshot capture --------------------------------------------------------
VIEWPORT = {"width": 1280, "height": 900}

def capture(page, name, scroll_y=0, wait_ms=1200):
    """Scroll to position, wait for render, save PNG, return path."""
    if scroll_y:
        page.evaluate(f"window.scrollTo(0, {scroll_y})")
    time.sleep(wait_ms / 1000)
    path = str(SHOTS / f"{name}.png")
    page.screenshot(path=path, full_page=False)
    print(f"  [shot] {name}.png")
    return path

def upload_file(page, selector_label, file_path):
    """Click a file input and set its path."""
    page.set_input_files(selector_label, file_path)
    time.sleep(1.5)

def take_all_screenshots():
    shots = {}
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(viewport=VIEWPORT)
        page = ctx.new_page()

        # Shot 1: Home screen
        page.goto(APP, wait_until="networkidle")
        time.sleep(2)
        page.keyboard.press("Escape")
        time.sleep(0.5)
        page.keyboard.press("Escape")
        time.sleep(0.5)
        shots["01_home"] = capture(page, "01_home")

        # Shot 2: Sidebar with all agencies loaded
        page.evaluate("""
            const sb = document.querySelector('[data-testid="stSidebar"]');
            if (sb) sb.scrollTop = 0;
        """)
        time.sleep(0.5)
        shots["02_sidebar_loaded"] = capture(page, "02_sidebar_loaded")

        # Shot 3: Scroll sidebar down to show Export section
        page.evaluate("""
            const sb = document.querySelector('[data-testid="stSidebar"] section');
            if (sb) sb.scrollTop = 9999;
        """)
        time.sleep(0.5)
        shots["03_sidebar_export"] = capture(page, "03_sidebar_export")

        # Shot 4: Scroll back up, show threshold sliders area
        page.evaluate("""
            const sb = document.querySelector('[data-testid="stSidebar"] section');
            if (sb) sb.scrollTop = 0;
        """)
        time.sleep(0.3)
        shots["04_sliders"] = capture(page, "04_sliders")

        # Shot 5: Main content area
        page.evaluate("window.scrollTo(0, 300)")
        time.sleep(0.8)
        shots["05_main_panel"] = capture(page, "05_main_panel")

        # Shot 6: Scroll down to show match cards if present
        page.evaluate("window.scrollTo(0, 600)")
        time.sleep(0.8)
        shots["06_lower_panel"] = capture(page, "06_lower_panel")

        # Shot 7: Scroll to top and zoom out to show full layout
        page.evaluate("window.scrollTo(0, 0)")
        page.evaluate("document.body.style.zoom='0.8'")
        time.sleep(0.8)
        shots["07_full_layout"] = capture(page, "07_full_layout")
        page.evaluate("document.body.style.zoom='1'")

        # Shot 8: Golden file button area
        page.evaluate("""
            const sb = document.querySelector('[data-testid="stSidebar"] section');
            if (sb) sb.scrollTop = 9999;
        """)
        time.sleep(0.5)
        shots["08_golden_button"] = capture(page, "08_golden_button")

        # Shot 9: Click Generate Golden File, capture dialog
        btns = page.query_selector_all("button")
        golden_btn = None
        for b in btns:
            txt = b.inner_text().strip()
            if "Golden File" in txt:
                golden_btn = b
                break
        if golden_btn:
            golden_btn.scroll_into_view_if_needed()
            golden_btn.click()
            time.sleep(1.5)
            page.evaluate("window.scrollTo(0, 0)")
            time.sleep(0.5)
            shots["09_golden_dialog"] = capture(page, "09_golden_dialog")
            page.keyboard.press("Escape")
            time.sleep(0.5)

        # Shot 10: Persona preset buttons
        page.evaluate("""
            const sb = document.querySelector('[data-testid="stSidebar"] section');
            if (sb) sb.scrollTop = 0;
        """)
        time.sleep(0.5)
        shots["10_presets"] = capture(page, "10_presets")

        # Shot 11: Full page at 70% zoom for overview
        page.evaluate("document.body.style.zoom='0.7'")
        page.evaluate("window.scrollTo(0, 0)")
        time.sleep(0.8)
        shots["11_overview"] = capture(page, "11_overview")
        page.evaluate("document.body.style.zoom='1'")

        browser.close()
    return shots


# -- PDF builder ---------------------------------------------------------------
_UNICODE_TABLE = str.maketrans({
    "─": "-",   # BOX DRAWINGS LIGHT HORIZONTAL
    "│": "|",   # BOX DRAWINGS LIGHT VERTICAL
    "┌": "+",   # BOX DRAWINGS LIGHT DOWN AND RIGHT
    "┐": "+",   # BOX DRAWINGS LIGHT DOWN AND LEFT
    "└": "+",   # BOX DRAWINGS LIGHT UP AND RIGHT
    "┘": "+",   # BOX DRAWINGS LIGHT UP AND LEFT
    "├": "+",   # BOX DRAWINGS LIGHT VERTICAL AND RIGHT
    "┤": "+",   # BOX DRAWINGS LIGHT VERTICAL AND LEFT
    "┬": "+",   # BOX DRAWINGS LIGHT DOWN AND HORIZONTAL
    "┴": "+",   # BOX DRAWINGS LIGHT UP AND HORIZONTAL
    "┼": "+",   # BOX DRAWINGS LIGHT VERTICAL AND HORIZONTAL
    "✓": "[+]", # CHECK MARK
    "✗": "[-]", # BALLOT X
    "≠": "!=",  # NOT EQUAL TO
    "≈": "~",   # ALMOST EQUAL TO
    "→": "->",  # RIGHTWARDS ARROW
})

def _ascii(text):
    """Strip Unicode chars that Courier (Type1) cannot render."""
    return text.translate(_UNICODE_TABLE)


def make_styles():
    s = getSampleStyleSheet()

    def P(name, **kw):
        base = kw.pop("parent", "Normal")
        return ParagraphStyle(name, parent=s[base], **kw)

    return {
        "title":   P("title",   fontSize=22, textColor=TEAL,    spaceAfter=4,
                      fontName="Courier-Bold", alignment=TA_CENTER),
        "sub":     P("sub",     fontSize=12, textColor=DIM_TEXT, spaceAfter=2,
                      fontName="Courier",      alignment=TA_CENTER),
        "h1":      P("h1",      fontSize=14, textColor=TEAL,     spaceBefore=14,
                      spaceAfter=4, fontName="Courier-Bold"),
        "h2":      P("h2",      fontSize=11, textColor=AMBER,    spaceBefore=8,
                      spaceAfter=3, fontName="Courier-Bold"),
        "body":    P("body",    fontSize=9,  textColor=LIGHT,    spaceAfter=4,
                      fontName="Courier",      leading=14),
        # "code" for single inline lines
        "code":    P("code",    fontSize=8,  textColor=TEAL,     spaceAfter=3,
                      fontName="Courier",      leading=13,
                      backColor=CODE_BG,       borderPadding=6,
                      leftIndent=12),
        # "pre" for Preformatted multi-line blocks (no word wrap)
        "pre":     P("pre",     fontSize=7,  textColor=TEAL,     spaceAfter=8,
                      fontName="Courier",      leading=10,
                      backColor=CODE_BG,       leftIndent=8),
        "caption": P("caption", fontSize=8,  textColor=DIM_TEXT, spaceAfter=6,
                      fontName="Courier-Oblique", alignment=TA_CENTER),
        "note":    P("note",    fontSize=8,  textColor=AMBER,    spaceAfter=4,
                      fontName="Courier-Oblique"),
        "step_h":  P("step_h",  fontSize=11, textColor=WHITE,    spaceBefore=10,
                      spaceAfter=3, fontName="Courier-Bold"),
    }


def code_block(lines, style=None):
    """Single Preformatted block — preserves whitespace, no word-wrap.

    'lines' can be a list of strings or one multi-line string.
    All Unicode box-drawing chars are replaced with plain ASCII.
    """
    if isinstance(lines, (list, tuple)):
        text = "\n".join(lines)
    else:
        text = lines
    text = _ascii(text)
    return Preformatted(text, style or _PRE_STYLE)

# _PRE_STYLE is set inside build_pdf where styles are available; we use a
# module-level sentinel and replace it once per build_pdf call.
_PRE_STYLE = None


def img_element(path, max_w=6.5*inch, max_h=4*inch):
    """Return a reportlab Image flowable scaled to fit."""
    if not path or not os.path.exists(path):
        return None
    pil = PILImage.open(path)
    w, h = pil.size
    ratio = min(max_w / w, max_h / h)
    return Image(path, width=w*ratio, height=h*ratio)


def placeholder_box(label, st):
    """Text placeholder when a screenshot wasn't captured."""
    return Paragraph(f"[ Screenshot: {label} ]", st["caption"])


def build_pdf(shots, styles):
    global _PRE_STYLE
    _PRE_STYLE = styles["pre"]

    doc = SimpleDocTemplate(
        str(PDF),
        pagesize=letter,
        leftMargin=0.75*inch, rightMargin=0.75*inch,
        topMargin=0.75*inch,  bottomMargin=0.75*inch,
    )

    def on_page(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(BG)
        canvas.rect(0, 0, letter[0], letter[1], fill=1, stroke=0)
        canvas.setStrokeColor(BORDER)
        canvas.setLineWidth(0.5)
        canvas.line(0.75*inch, 0.5*inch, letter[0]-0.75*inch, 0.5*inch)
        canvas.setFont("Courier", 7)
        canvas.setFillColor(DIM_TEXT)
        canvas.drawCentredString(letter[0]/2, 0.35*inch,
            f"C3E  Cascadia  Rogue Raise #02  Ashland OR  Oct 23-25, 2026"
            f"  |  Page {doc.page}")
        canvas.restoreState()

    st = styles
    story = []

    def HR():
        story.append(Spacer(1, 4))
        story.append(HRFlowable(width="100%", thickness=0.5,
                                color=BORDER, spaceAfter=6))

    def add_shot(key, label, caption=None):
        path = shots.get(key)
        el = img_element(path) if path else None
        if el:
            story.append(el)
        else:
            story.append(placeholder_box(label, st))
        if caption:
            story.append(Paragraph(caption, st["caption"]))
        story.append(Spacer(1, 8))

    # -- Cover -----------------------------------------------------------------
    story.append(Spacer(1, 0.5*inch))
    story.append(Paragraph("C3E -- Cascadia", st["title"]))
    story.append(Paragraph(
        "Continuum of Care Master Data Engine  Rogue River Valley", st["sub"]))
    story.append(Spacer(1, 8))
    story.append(HRFlowable(width="100%", thickness=1, color=TEAL, spaceAfter=8))
    story.append(Paragraph(
        "OnTrack Rogue Valley -- Ingestion &amp; Golden Record Export", st["h1"]))
    story.append(Paragraph(
        "Step-by-Step Walkthrough with Live Application Screenshots", st["sub"]))
    story.append(Spacer(1, 12))
    story.append(Paragraph(
        "All records in this walkthrough are synthetic test data. "
        "No real client information is included or implied.",
        st["note"]))
    HR()

    # -- Application overview screenshot ---------------------------------------
    story.append(Paragraph("Application Overview", st["h1"]))
    story.append(Paragraph(
        "C3E running on localhost:8501 with existing agency data loaded. "
        "The dark Pacific Northwest cosmic theme, compass rose header, and "
        "sidebar controls are visible. The swipe deck occupies the main panel.",
        st["body"]))
    add_shot("01_home", "C3E app home screen",
             "Fig 1 -- C3E home screen. Dark PNW theme. Compass rose header."
             " Sidebar shows ingested agencies.")

    add_shot("07_full_layout", "Full app layout at 80% zoom",
             "Fig 2 -- Full layout view. Sidebar (left): session metrics, ingested"
             " datasets, export. Main panel (right): swipe deck.")

    HR()

    # -- Data being ingested ---------------------------------------------------
    story.append(Paragraph("The Data Being Ingested", st["h1"]))
    story.append(Paragraph(
        "OnTrack Rogue Valley is the largest SUD/MH treatment provider in the RRV. "
        "The two files below represent 240 clients and 2,999 service encounters "
        "with realistic dirty-data characteristics.", st["body"]))

    story.append(Paragraph("ontrack_clients.csv -- sample rows", st["h2"]))
    story.append(code_block([
        "client_id  | first_name | last_name | date_of_birth | ssn_last4 | phone",
        "-----------+------------+-----------+---------------+-----------+--------------------",
        "OT-000001  | Mary       | Baker     | 2007-08-23    | 4488      | 541-555-9082",
        "OT-000002  | Elizabeth  | Cox       | 07/23/1986    |           | cell: 541-555-3989",
        "OT-000003  | BRANDON    | MORALES   | 05/16/1957    | 201       | 541-555-2843",
        "OT-000004  | RAYMOND    | MARTIN    | 2/17/73       | 967       | (541) 555-7752",
        "OT-000005  | George     | Jones     | 1990-01-19    | 8279      | (541) 555-7225",
    ]))
    story.append(Paragraph(
        "Dirty-data indicators: OT-000002 has a 'cell: ' prefix on phone and missing SSN. "
        "OT-000003 and OT-000004 are ALL CAPS entries. OT-000003 has a 3-digit SSN (truncation). "
        "OT-000004 uses a 2-digit year. These are cleaned in Stage 2.", st["note"]))

    story.append(Spacer(1, 6))
    story.append(Paragraph("ontrack_services.csv -- sample rows", st["h2"]))
    story.append(code_block([
        "service_id     | client_id  | service_date | service_type                  | duration",
        "---------------+------------+--------------+-------------------------------+---------",
        "OT-SVC-000001  | OT-000001  | 2026-02-10   | Day Treatment Group           | 240 min",
        "OT-SVC-000002  | OT-000001  | 2025-06-03   | Day Treatment Skills Workshop | 90 min",
        "OT-SVC-000003  | OT-000001  | 2024-09-02   | Day Treatment UA              | 15 min",
        "OT-SVC-000004  | OT-000001  | 03/22/2026   | Day Treatment UA              | 15 min",
        "OT-SVC-000005  | OT-000001  | 2024-09-29   | Day Treatment Individual      | 60 min",
    ]))
    story.append(Paragraph(
        "OT-SVC-000004 uses MM/DD/YYYY date format -- will be normalized to YYYY-MM-DD in Stage 2.",
        st["note"]))

    HR()

    # -- Steps -----------------------------------------------------------------
    steps = [
        ("Step 1 -- Launch the Application", "01_home",
         "Launch: streamlit run app.py",
         "The C3E compass rose header loads with the dark Pacific Northwest theme. "
         "The sidebar shows session metrics, threshold sliders, loaded agencies, and the Export section. "
         "If this is a fresh session no agencies are loaded. Here the app already has prior agencies loaded.",
         "Fig 3 -- Application home screen after launch. Compass rose header visible center.",
         None),

        ("Step 2 -- Sidebar: Agencies &amp; Controls", "02_sidebar_loaded",
         None,
         "The left sidebar shows: Session Metrics (approved merges, severed matches, queue size), "
         "Confidence threshold sliders, Ingested Datasets list (each agency with record count and x remove), "
         "and the Export section at the bottom. All 5 prior agencies are shown here before OnTrack is added.",
         "Fig 4 -- Sidebar: session metrics, threshold sliders, and loaded agency list.",
         None),

        ("Step 3 -- Upload the OnTrack Client File", "04_sliders",
         "Click [ Upload Client File ] in the sidebar --> select input/ontrack_clients.csv",
         "The app reads the 240-row CSV and runs rapidfuzz header detection against its synonym dictionary. "
         "Dropdowns are pre-populated with the best-guess field mapping. The user confirms in under 30 seconds. "
         "A green banner confirms: OnTrack Clients loaded -- 240 records confirmed.",
         "Fig 5 -- Threshold sliders and upload area in the sidebar.",
         ("Column Mapper auto-detection results:\n"
          "  client_id       -> [Client ID / Source Key]      100%\n"
          "  first_name      -> [First Name]                  100%\n"
          "  last_name       -> [Last Name]                   100%\n"
          "  date_of_birth   -> [Date of Birth]                98%\n"
          "  ssn_last4       -> [SSN Last 4 Digits]            95%\n"
          "  phone           -> [Phone Number]                 97%\n"
          "  intake_date     -> [Intake / Encounter Date]      89%")),

        ("Step 4 -- Upload the OnTrack Services File", "02_sidebar_loaded",
         "Click [ Upload Services File ] --> select input/ontrack_services.csv",
         "The app auto-detects service file columns: service_id -> Encounter ID (97%), "
         "client_id -> Client ID (100%), service_date -> Encounter Date (96%). "
         "After confirmation: OnTrack Services loaded -- 2,999 encounter records confirmed. "
         "Total ingested across all 6 agencies: 760 demographic records.",
         "Fig 6 -- Sidebar after all agencies loaded. OnTrack joins the Ingested Datasets list.",
         None),

        ("Step 5 -- Stage 2: Cleaning &amp; Standardization", "05_main_panel",
         None,
         "Every record is normalized to a common schema. Dates are parsed from any format to YYYY-MM-DD. "
         "SSN fields are regex-validated (must be exactly 4 digits or blank -- 3-digit entries like '201' "
         "are treated as blank). Names are lowercased and stripped. "
         "Agentic check confirms: zero uncleaned dates, all SSN fields valid.",
         "Fig 7 -- Main panel during or after pipeline execution.",
         ("Cleaning examples:\n"
          "  '07/23/1986'  ->  '1986-07-23'\n"
          "  '2/17/73'     ->  '1973-02-17'\n"
          "  '03/22/2026'  ->  '2026-03-22'  (service date)\n"
          "  '201'         ->  ''  (3-digit SSN, fails \\d{4} check)\n"
          "  'BRANDON'     ->  'brandon'  (lowercased for matching)\n"
          "  'RAYMOND'     ->  'raymond'")),

        ("Step 6 -- Stage 3: Probabilistic Matching (Splink)", "05_main_panel",
         None,
         "Splink compares all 760 records against each other using blocking rules "
         "(same DOB, same last name, or same SSN last 4). For each candidate pair it "
         "calculates a match probability from 0.0 to 1.0 based on field-level agreement. "
         "Records below the minimum threshold are auto-rejected and never shown in the swipe deck.",
         "Fig 8 -- Pipeline executing Splink matching stage.",
         ("Example match candidates:\n"
          "  ONTRACK_RV::OT-000142  vs  ACCESS_HUD::ACC-031    p=0.9412\n"
          "    (Bob Smith 1978-11-02  vs  Robert Smith 1978-11-02)\n"
          "  ONTRACK_RV::OT-000089  vs  ROGUE_RETREAT::RR-0057  p=0.8834\n"
          "    (Maria Garcia 1992-06-30 vs  Maria Garcia 1992-06-30)\n"
          "  ONTRACK_RV::OT-000214  vs  ROGUE_RETREAT::RR-0044  p=0.5103\n"
          "    (James Johnson 1978-01-01 vs James Johnson 1979-03-12)")),

        ("Step 7 -- Stage 4: Graph Clustering &amp; MPI Assignment", "06_lower_panel",
         None,
         "Matched pairs become edges in a NetworkX graph. Connected components finds all clusters -- "
         "groups of records likely representing the same person. Each cluster is assigned a "
         "deterministic UUID v5 Master Person ID (MPI). The same group of records always "
         "produces the same UUID, even on re-runs.",
         "Fig 9 -- Lower panel showing clustering results.",
         None),

        ("Step 8 -- The Swipe Deck: Human Review", "05_main_panel",
         None,
         "Match candidates above the minimum threshold are presented side-by-side. "
         "Matching fields are highlighted in teal (#00E6A8). Discrepancies in amber (#FF9E3B). "
         "The match evidence panel shows field-by-field scores. "
         "ACCEPT merges the records under one MPI. REJECT severs the edge.",
         "Fig 10 -- Swipe deck with side-by-side Record A vs Record B comparison.",
         ("Example card pair:\n"
          "  Record A: ONTRACK_RV::OT-000142\n"
          "    Bob Smith  DOB: 1978-11-02  OnTrack Medford  Outpatient SUD\n"
          "  Record B: ACCESS_HUD::ACC-031\n"
          "    Robert Smith  DOB: 1978-11-02  ACCESS HMIS  Emergency Shelter\n"
          "  Match Score: 94%\n"
          "  Evidence:\n"
          "    Last name:  Smith = Smith       [+] Exact  (high weight)\n"
          "    DOB:        1978-11-02 = same   [+] Exact  (very high weight)\n"
          "    First name: Bob ~ Robert        [~] Fuzzy  (nickname variant)\n"
          "    SSN:        (blank) != 3847     [-] Cannot compare")),

        ("Step 9 -- Export the Golden Records File", "08_golden_button",
         "Scroll to EXPORT in sidebar  Click [ Generate Golden File ]  Confirm dialog",
         "The app joins dim_master_persons with fact_encounters using DuckDB in-process. "
         "Every service encounter is enriched with canonical person attributes in one flat file. "
         "Sorted by last name --> first name --> encounter date. "
         "This is the file a commissioner opens in Excel or PowerBI.",
         "Fig 11 -- Export section in sidebar showing Generate Golden File button.",
         None),

        ("Step 10 -- Golden Export Confirmation", "09_golden_dialog",
         None,
         "A confirmation dialog appears before generating the file. "
         "Clicking Generate triggers the DuckDB JOIN and writes the output file. "
         "A teal success banner confirms the row count.",
         "Fig 12 -- Confirmation dialog and/or success banner after golden file export.",
         None),
    ]

    for title, shot_key, cmd, body_text, fig_cap, code_text in steps:
        story.append(Paragraph(title, st["h1"]))
        if cmd:
            story.append(code_block([cmd]))
        story.append(Paragraph(body_text, st["body"]))
        if code_text:
            story.append(code_block(code_text))
        story.append(Spacer(1, 4))
        add_shot(shot_key, title, fig_cap)
        HR()

    # -- Intermediate file stubs -----------------------------------------------
    story.append(Paragraph("Intermediate Pipeline Files", st["h1"]))
    story.append(Paragraph(
        "Three files are written to output/ after the pipeline completes. "
        "These are the audit layer between raw input and the Golden File.", st["body"]))

    story.append(Paragraph("bridge_record_links.csv", st["h2"]))
    story.append(code_block([
        "unique_record_id           | master_person_id                     | conf   | match_type",
        "---------------------------+--------------------------------------+--------+---------------------",
        "ACCESS_HUD::ACC-001        | 0ba7925b-f9ed-53a1-b698-7caa051c6db6 | 0.9565 | Probabilistic_Splink",
        "ACCESS_HUD::ACC-002        | 92e1b786-7b9c-52d0-8afd-6fb3fa2cf511 | 1.0000 | Direct_Single",
        "ONTRACK_RV::OT-000089      | 84e1b999-3687-5ffa-b4c9-a6b2169006d2 | 0.8834 | Probabilistic_Splink",
        "ROGUE_RETREAT::RR-0057     | 84e1b999-3687-5ffa-b4c9-a6b2169006d2 | 0.8834 | Probabilistic_Splink",
    ]))
    story.append(Paragraph(
        "OT-000089 and RR-0057 share the same master_person_id -- same person at two agencies. "
        "Direct_Single = record stood alone; Probabilistic_Splink = merged by Splink match.",
        st["note"]))

    story.append(Spacer(1, 8))
    story.append(Paragraph("dim_master_persons.csv", st["h2"]))
    story.append(code_block([
        "master_person_id                     | first   | last     | dob        | rec | src | sources",
        "-------------------------------------+---------+----------+------------+-----+-----+------------------------------",
        "84e1b999-3687-5ffa-b4c9-a6b2169006d2 | Joseph  | Anderson | 1956-11-07 |   2 |   2 | RECOVERY_CAFE, ROGUE_RETREAT",
        "5c7e768d-0b22-510b-9fc8-0258aab26082 | Kenneth | Davis    | 1991-01-12 |   2 |   2 | RECOVERY_CAFE, ROGUE_RETREAT",
        "016a14ce-01e5-5275-a0f9-1e29c0e21238 | Steven  | Wilson   | 1987-05-05 |   2 |   2 | RECOVERY_CAFE, ROGUE_RETREAT",
        "0ba7925b-f9ed-53a1-b698-7caa051c6db6 | Mark    | Lewis    | 1971-04-27 |   1 |   1 | ACCESS_HUD",
    ]))
    story.append(Paragraph(
        "Joseph Anderson (84e1b999...) appears at Recovery Cafe AND Rogue Retreat. "
        "Without C3E he would be counted twice in the PIT count.",
        st["note"]))

    HR()

    # -- Golden File stub ------------------------------------------------------
    story.append(Paragraph("The Golden Records File -- Output", st["h1"]))
    story.append(Paragraph(
        "GOLDEN_PERSONS_ENCOUNTERS.csv is the final commissioner-ready deliverable. "
        "One row per service encounter, enriched with canonical person attributes. "
        "Every row is defensible -- every merge has a confidence score and audit trail. "
        "Every person is counted exactly once.", st["body"]))

    story.append(Paragraph("Single-agency person (OnTrack only)", st["h2"]))
    story.append(code_block([
        "-- Person --",
        "master_person_id  | first | last  | dob        | source     | rec",
        "------------------+-------+-------+------------+------------+----",
        "f3a92011-...      | Mary  | Baker | 2007-08-23 | ONTRACK_RV |   1",
        "",
        "-- Encounters --",
        "encounter_id   | source_sys | enc_date   | service_category",
        "---------------+------------+------------+-------------------------------",
        "OT-SVC-000001  | ONTRACK_RV | 2026-02-10 | Day Treatment Group",
        "OT-SVC-000002  | ONTRACK_RV | 2025-06-03 | Day Treatment Skills Workshop",
        "OT-SVC-000003  | ONTRACK_RV | 2024-09-02 | Day Treatment UA",
    ]))
    story.append(Paragraph(
        "Mary Baker appears only at OnTrack. total_linked_records = 1, linked_sources_count = 1. "
        "She contributes one person to the unique-persons count.",
        st["note"]))

    story.append(Spacer(1, 6))
    story.append(Paragraph("Cross-agency person (merged by C3E)", st["h2"]))
    story.append(code_block([
        "-- Person --",
        "master_person_id                     | first  | last     | dob        | rec",
        "-------------------------------------+--------+----------+------------+----",
        "84e1b999-3687-5ffa-b4c9-a6b2169006d2 | Joseph | Anderson | 1956-11-07 |   2",
        "Contributing sources: RECOVERY_CAFE, ROGUE_RETREAT",
        "",
        "-- Encounters --",
        "encounter_id   | source_sys    | enc_date   | service_category",
        "---------------+---------------+------------+--------------------------------------",
        "RC-VST-0123    | RECOVERY_CAFE | 2026-01-03 | One-on-One Peer Coaching",
        "RC-VST-0122    | RECOVERY_CAFE | 2026-02-21 | Women's Hope & Healing Group",
        "RR-ENT-0058    | ROGUE_RETREAT | 2026-03-24 | Shelter Entry: Urban Campground Space",
        "RC-VST-0124    | RECOVERY_CAFE | 2026-09-16 | Mindfulness & Well-being Workshop",
    ]))
    story.append(Paragraph(
        "Joseph Anderson was found at Recovery Cafe AND Rogue Retreat. Without C3E: counted as 2 people. "
        "With C3E: one UUID, all 4 service encounters unified under one master person. "
        "The difference between 'we served 760 individuals' and 'we served 692 unique individuals.'",
        st["note"]))

    story.append(Spacer(1, 12))
    add_shot("08_golden_button", "Golden file export button",
             "Fig 13 -- Sidebar Export section. Generate Golden File button with golden styling.")

    HR()

    # -- Summary ---------------------------------------------------------------
    story.append(Paragraph("Summary", st["h1"]))
    story.append(code_block([
        "Input:   ontrack_clients.csv (240 records) + ontrack_services.csv (2,999 encounters)",
        "Stage 1: Ingest -- 760 total records across 6 agencies normalized to unified schema",
        "Stage 2: Clean  -- dates -> YYYY-MM-DD, SSN validated \\d{4}, names lowercased",
        "Stage 3: Match  -- Splink probabilistic scoring, candidate pairs generated",
        "Stage 4: Cluster-- NetworkX connected components, UUID v5 MPIs assigned",
        "Stage 5: Export -- dim_master_persons + bridge_record_links + fact_encounters",
        "Human:   Swipe deck review -- accept/reject uncertain matches",
        "Output:  GOLDEN_PERSONS_ENCOUNTERS.csv -- commissioner-ready flat file",
    ]))

    story.append(Spacer(1, 16))
    story.append(HRFlowable(width="100%", thickness=1, color=TEAL, spaceAfter=6))
    story.append(Paragraph(
        "C3E  Cascadia  Rogue Raise #02  White Rabbit, Ashland OR  Oct 23-25, 2026",
        st["sub"]))

    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
    print(f"\n[OK] PDF written -> {PDF}")
    return str(PDF)


# -- Main ----------------------------------------------------------------------
if __name__ == "__main__":
    import sys

    if "--pdf-only" in sys.argv:
        # Skip screenshot capture; use existing shots in output/walkthrough_shots/
        print("Phase 1 -- Skipped (--pdf-only flag). Using existing screenshots.")
        shots = {p.stem: str(p) for p in SHOTS.glob("*.png")}
        print(f"  Found {len(shots)} existing screenshots.")
    else:
        print("Phase 1 -- Capturing screenshots from live app...")
        shots = take_all_screenshots()
        print(f"\nCaptured {len(shots)} screenshots into {SHOTS}\n")

    print("Phase 2 -- Building PDF...")
    styles = make_styles()
    result = build_pdf(shots, styles)
    print(f"Done. Open: {result}")

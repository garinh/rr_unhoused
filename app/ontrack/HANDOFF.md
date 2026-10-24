# Cascadia (C3E) — Handoff Guide
**Continuum of Care Master Data Engine — Rogue River Valley**

---

## What This Is

Cascadia de-duplicates client records from multiple Rogue River Valley homeless service providers — ACCESS, Rogue Retreat, Recovery Café, Jackson County SSP, St. Vincent de Paul, and OnTrack — and assigns each person a single persistent ID so they are counted once across all agencies, not once per program they touch.

The app runs entirely on your own computer. No data leaves your building.

---

## What You Need Before You Start

- A Windows computer (Windows 10 or later)
- An internet connection for the one-time setup
- About 5 minutes the first time

That's it. No software installation required beforehand.

---

## First-Time Setup (do this once)

1. Double-click **`setup.bat`**
2. A black window will open and download everything the app needs automatically
3. When it says **"Setup complete!"**, close the window

This only needs to happen once. After that, the app runs fully offline.

---

## Starting the App Every Day

Double-click **`start.bat`**

Your browser will open automatically to the app. Do not close the black command window that appears — it is keeping the app running. When you are done using the app, close the browser tab and then close the black window.

---

## Where Your Files Go

| Folder | What goes there |
|---|---|
| `input/` | Agency CSV files for the matching pipeline |
| `input/archive/` | Older CSV files you want to keep but not process |
| `input/schemas/` | Column mapping files — one per agency (already configured) |
| `output/` | Pipeline results: master person list, service encounter log, golden file |

---

## Agency Schemas Already Configured

The following agencies are already set up and will load automatically:

- ACCESS (HUD HMIS)
- Rogue Retreat
- Recovery Café
- Jackson County Syringe Exchange Program
- St. Vincent de Paul (Ashland)
- OnTrack Rogue Valley

---

## Adding a New Agency

1. Open the app and go to the **Trading Partner Manager** section in the left sidebar
2. Upload the agency's CSV file
3. Use the dropdown menus to match their column headers to the standard fields (First Name, Last Name, Date of Birth, etc.)
4. Click **Confirm Mapping** — the app saves the mapping so you never have to do it again for that agency

Target time: under 30 seconds for a clean CSV.

---

## Running the Pipeline and Exporting Data

After loading new agency files, use the **Generate / Overwrite Golden File** button in the app sidebar. This rebuilds the master person list and produces the export file in one click.

The output files appear in `output/`:

| File | Contents |
|---|---|
| `dim_master_persons.csv` | One row per unique person, with their persistent ID |
| `bridge_record_links.csv` | Maps every raw agency record to its master person ID |
| `fact_encounters.csv` | All service encounters across all agencies |
| `GOLDEN_PERSONS_ENCOUNTERS.csv` | Flat joined report for commissioner presentations |

---

## If Something Breaks

**App won't start — says "Setup has not been run yet":**
Run `setup.bat` first, then try `start.bat` again.

**Setup fails partway through:**
Check your internet connection and double-click `setup.bat` again — it will pick up where it left off.

**App loads but shows no data:**
Use the Generate Golden File button in the sidebar to run the pipeline. The app reads from `output/` — if no pipeline has run yet, those files don't exist.

**Still stuck:**
Contact your designated technical contact. Share the full text from the black command window — it will identify exactly which step failed.

---

## System Scale

Cascadia is designed for the Rogue River Valley region:
- ~2,500 to 4,000 unique individuals per year
- ~15,000 to 40,000 service encounters per year

It runs on a standard laptop or desktop. No server, no cloud, no internet after setup.

---

## Mac or Linux

Open Terminal, navigate to the project folder, and run:
```
bash start.sh
```
Python 3.10 or later must be installed first (`python.org/downloads`).

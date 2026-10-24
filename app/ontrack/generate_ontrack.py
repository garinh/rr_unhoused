"""
generate_ontrack.py — Synthetic data generator for OnTrack Rogue Valley
Produces:
    input/ontrack_clients.csv
    input/ontrack_services.csv

Programs: outpatient SUD/MH, IOP, day treatment, residential (HOME / Dad's /
Mountain View), transitional housing, DUII/MIP education, bilingual Spanish.
Link key: client_id  (format: OT-XXXXXX)

Dirty-data realism:
  - Nickname / legal-name mismatch (~25% of records)
  - ALL-CAPS names, lowercase names, mixed-case typos
  - DOB in MM/DD/YYYY or M/D/YY mixed with ISO; some blank or year-only
  - SSN last-4 often missing (SUD clients often refuse); some 3-digit typos
  - Phone formatted inconsistently or absent
  - Some records share names with other agency files (realistic cross-agency dups)
  - Court-mandated records tend to be cleaner; street-outreach records messiest
"""

import csv
import os
import random
import re
from datetime import date, timedelta

random.seed(2026_10)   # different seed from other generators

INPUT_DIR = os.path.join(os.path.dirname(__file__), "input")
os.makedirs(INPUT_DIR, exist_ok=True)

# ── Name pools ─────────────────────────────────────────────────────────────────
FIRST_M = [
    "James", "Robert", "Michael", "William", "David", "Richard", "Joseph",
    "Thomas", "Charles", "Christopher", "Daniel", "Matthew", "Anthony",
    "Donald", "Mark", "Paul", "Steven", "Andrew", "Kenneth", "Joshua",
    "Kevin", "Brian", "George", "Timothy", "Ronald", "Edward", "Jason",
    "Jeffrey", "Ryan", "Jacob", "Gary", "Nicholas", "Eric", "Jonathan",
    "Stephen", "Larry", "Justin", "Scott", "Brandon", "Benjamin",
    "Samuel", "Raymond", "Gregory", "Patrick", "Jack", "Dennis", "Jerry",
    "Tyler", "Aaron", "Jose", "Frank", "Travis", "Jesse", "Adam",
]
FIRST_F = [
    "Mary", "Patricia", "Jennifer", "Linda", "Barbara", "Elizabeth",
    "Susan", "Jessica", "Sarah", "Karen", "Lisa", "Nancy", "Betty",
    "Margaret", "Sandra", "Ashley", "Dorothy", "Kimberly", "Emily",
    "Donna", "Michelle", "Carol", "Amanda", "Melissa", "Deborah",
    "Stephanie", "Rebecca", "Sharon", "Laura", "Cynthia", "Kathleen",
    "Amy", "Angela", "Shirley", "Anna", "Brenda", "Pamela", "Emma",
    "Nicole", "Helen", "Samantha", "Katherine", "Christine", "Debra",
    "Rachel", "Carolyn", "Janet", "Catherine", "Maria", "Heather",
    "Diane", "Julie", "Amber", "Tiffany", "Crystal", "Brandy",
]
LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller",
    "Davis", "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez",
    "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson", "Martin",
    "Lee", "Perez", "Thompson", "White", "Harris", "Sanchez", "Clark",
    "Ramirez", "Lewis", "Robinson", "Walker", "Young", "Allen", "King",
    "Wright", "Scott", "Torres", "Hill", "Flores", "Green", "Adams",
    "Nelson", "Baker", "Hall", "Rivera", "Mitchell", "Carter", "Roberts",
    "Phillips", "Evans", "Turner", "Diaz", "Parker", "Cruz", "Edwards",
    "Collins", "Reyes", "Stewart", "Morris", "Morales", "Cook", "Rogers",
    "Gutierrez", "Ortiz", "Morgan", "Cooper", "Bailey", "Reed", "Kelly",
    "Howard", "Ramos", "Kim", "Cox", "Ward", "Brooks", "Wood", "Webb",
    "Simpson", "Fields", "Ferguson", "Hunt", "Burke", "Hanson", "Knight",
]

# Nicknames / aliases that replace legal names in dirty records
NICKNAME_MAP = {
    "Robert": ["Bob", "Bobby", "Rob", "Robbie"],
    "William": ["Bill", "Billy", "Will", "Willy"],
    "Michael": ["Mike", "Mikey", "Mick"],
    "Richard": ["Rick", "Ricky", "Dick", "Rich"],
    "James":   ["Jim", "Jimmy", "Jamie"],
    "Thomas":  ["Tom", "Tommy"],
    "Joseph":  ["Joe", "Joey"],
    "Charles":  ["Chuck", "Charlie", "Chas"],
    "Christopher": ["Chris", "Kris"],
    "Timothy": ["Tim", "Timmy"],
    "Donald":  ["Don", "Donnie"],
    "Kenneth": ["Ken", "Kenny"],
    "Stephen": ["Steve"],
    "Steven":  ["Steve", "Stevie"],
    "Daniel":  ["Dan", "Danny"],
    "Anthony": ["Tony", "Ant"],
    "Patrick": ["Pat", "Paddy"],
    "Brandon": ["Bran"],
    "Benjamin": ["Ben", "Benji"],
    "Samuel":  ["Sam", "Sammy"],
    "Elizabeth": ["Liz", "Beth", "Lizzie", "Eliza", "Betty"],
    "Jennifer": ["Jen", "Jenny", "Jenn"],
    "Kathleen": ["Kathy", "Kate", "Katie"],
    "Patricia": ["Pat", "Patty", "Tricia"],
    "Margaret": ["Maggie", "Peg", "Peggy", "Margie"],
    "Kimberly": ["Kim", "Kimmy"],
    "Christine": ["Chris", "Chrissy", "Tina"],
    "Stephanie": ["Steph", "Stefanie"],
    "Deborah":  ["Deb", "Debbie"],
    "Rebecca":  ["Becca", "Becky"],
    "Samantha": ["Sam", "Sammy"],
    "Katherine": ["Kate", "Kathy", "Kat"],
    "Barbara":  ["Barb", "Barbie"],
    "Dorothy":  ["Dot", "Dottie"],
    "Sandra":   ["Sandy"],
    "Melissa":  ["Mel", "Missy"],
    "Amanda":   ["Mandy"],
    "Crystal":  ["Crys"],
    "Tiffany":  ["Tiff", "Tiffy"],
}

# Typo generators
def _typo(name):
    """Introduce a realistic transcription typo ~30% of the time."""
    if random.random() > 0.30:
        return name
    ops = []
    # doubled letter
    if len(name) > 3:
        i = random.randint(1, len(name) - 2)
        ops.append(name[:i] + name[i] + name[i:])
    # dropped letter
    if len(name) > 4:
        i = random.randint(1, len(name) - 2)
        ops.append(name[:i] + name[i+1:])
    # transposed adjacent letters
    if len(name) > 3:
        i = random.randint(0, len(name) - 2)
        lst = list(name)
        lst[i], lst[i+1] = lst[i+1], lst[i]
        ops.append("".join(lst))
    return random.choice(ops) if ops else name


def _case_mangle(name, style):
    if style == "upper":  return name.upper()
    if style == "lower":  return name.lower()
    if style == "proper": return name.title()
    return name   # mixed / leave as-is


# ── Date helpers ───────────────────────────────────────────────────────────────
SERVICE_START = date(2024, 1, 1)
SERVICE_END   = date(2026, 10, 1)


def _rand_dob(min_age=18, max_age=72):
    days_back = random.randint(min_age * 365, max_age * 365)
    return date(2026, 1, 1) - timedelta(days=days_back)


def _format_dob(d, style):
    """Return DOB in various dirty formats."""
    if style == "iso":       return d.strftime("%Y-%m-%d")
    if style == "us":        return d.strftime("%m/%d/%Y")
    if style == "us_short":  return d.strftime("%-m/%-d/%y") if os.name != "nt" else f"{d.month}/{d.day}/{d.strftime('%y')}"
    if style == "year_only": return f"{d.year}-01-01"
    if style == "blank":     return ""
    if style == "unknown":   return "UNKNOWN"
    return d.strftime("%Y-%m-%d")


def _rand_date(start=SERVICE_START, end=SERVICE_END):
    delta = (end - start).days
    return start + timedelta(days=random.randint(0, delta))


def _rand_phone(style):
    n = random.randint(1000, 9999)
    base = f"541555{n:04d}"
    if style == "formatted":  return f"(541) 555-{n:04d}"
    if style == "dashes":     return f"541-555-{n:04d}"
    if style == "raw":        return base
    if style == "cell_label": return f"cell: 541-555-{n:04d}"
    if style == "blank":      return ""
    return f"541-555-{n:04d}"


def _rand_ssn(completeness):
    """completeness: 'full4', 'partial3', 'blank', 'refused'"""
    if completeness == "blank":   return ""
    if completeness == "refused": return "REFUSED"
    if completeness == "partial3":
        return f"{random.randint(100, 999)}"   # 3-digit typo
    return f"{random.randint(1000, 9999)}"


# ── Program & staff pools ──────────────────────────────────────────────────────
PROGRAMS = [
    "Outpatient SUD",
    "Intensive Outpatient (IOP)",
    "Day Treatment",
    "Residential - Mountain View Recovery Center",
    "Residential - HOME Program",
    "Residential - Dad's Program",
    "Transitional Housing",
    "DUII Education",
    "MIP Education",
    "Mental Health Outpatient",
    "Bilingual SUD (Spanish)",
]

PROGRAM_WEIGHTS = [18, 14, 10, 8, 5, 4, 7, 12, 6, 10, 6]

CASE_MANAGERS = [
    "A. Reeves", "B. Tanaka", "C. Okonkwo", "D. Whitfield",
    "E. Sandoval", "F. Nguyen", "G. Harmon", "H. Delgado",
    "I. Patel", "J. Crowley", "K. Vasquez", "L. Strom",
    "M. Oduya",  # bilingual Spanish
]

LOCATIONS = [
    "OnTrack Medford - 625 Stevens St",
    "OnTrack Ashland - 100 N Mountain Ave",
    "OnTrack Grants Pass - 1700 NE 7th St",
    "OnTrack Cave Junction",
    "Mountain View Recovery Center - Medford",
    "HOME Program - Medford",
    "Dad's Program - Medford",
    "Transitional Housing Unit - Medford",
]

SERVICE_TYPES = {
    "Outpatient SUD": [
        ("Individual Counseling - SUD", "Substance Use Treatment", 60),
        ("Group Therapy - SUD", "Substance Use Treatment", 90),
        ("Medication-Assisted Treatment (MAT) Check-in", "Substance Use Treatment", 30),
        ("Urinalysis (UA) Drug Screen", "Substance Use Treatment", 15),
        ("Case Management", "Case Management", 45),
        ("Crisis Intervention", "Crisis Services", 60),
    ],
    "Intensive Outpatient (IOP)": [
        ("IOP Group Session", "Substance Use Treatment", 180),
        ("IOP Individual Check-in", "Substance Use Treatment", 30),
        ("IOP Urinalysis", "Substance Use Treatment", 15),
        ("IOP Family Session", "Substance Use Treatment", 60),
        ("IOP Case Management", "Case Management", 30),
    ],
    "Day Treatment": [
        ("Day Treatment Group", "Substance Use Treatment", 240),
        ("Day Treatment Individual", "Substance Use Treatment", 60),
        ("Day Treatment Skills Workshop", "Substance Use Treatment", 90),
        ("Day Treatment UA", "Substance Use Treatment", 15),
    ],
    "Residential - Mountain View Recovery Center": [
        ("Residential Intake Assessment", "Residential", 120),
        ("Residential Group Therapy", "Residential", 90),
        ("Residential Individual Counseling", "Residential", 60),
        ("Residential Life Skills", "Residential", 60),
        ("Residential UA", "Residential", 15),
        ("Residential Discharge Planning", "Residential", 60),
    ],
    "Residential - HOME Program": [
        ("HOME Intake - Mother/Child", "Residential", 120),
        ("HOME Group Session", "Residential", 90),
        ("HOME Parenting Skills", "Residential", 60),
        ("HOME Individual Counseling", "Residential", 60),
        ("HOME Child Development Check", "Residential", 30),
        ("HOME UA", "Residential", 15),
    ],
    "Residential - Dad's Program": [
        ("Dad's Program Intake", "Residential", 120),
        ("Dad's Parenting Group", "Residential", 90),
        ("Dad's Individual Counseling", "Residential", 60),
        ("Dad's Fatherhood Workshop", "Residential", 90),
        ("Dad's UA", "Residential", 15),
    ],
    "Transitional Housing": [
        ("Housing Intake", "Transitional Housing", 60),
        ("Housing Case Management", "Case Management", 45),
        ("Housing Stability Check-in", "Transitional Housing", 30),
        ("Housing UA (optional)", "Transitional Housing", 15),
        ("Housing Benefits Navigation", "Case Management", 60),
    ],
    "DUII Education": [
        ("DUII Level I Class", "Court-Mandated Education", 120),
        ("DUII Level II Class", "Court-Mandated Education", 180),
        ("DUII Fast-Track Session", "Court-Mandated Education", 240),
        ("DUII Individual Assessment", "Court-Mandated Education", 60),
        ("DUII Compliance Report", "Court-Mandated Education", 30),
        ("DUII Relapse Prevention", "Court-Mandated Education", 60),
    ],
    "MIP Education": [
        ("MIP Class Session", "Court-Mandated Education", 120),
        ("MIP Individual Counseling", "Court-Mandated Education", 60),
        ("MIP Compliance Report", "Court-Mandated Education", 30),
    ],
    "Mental Health Outpatient": [
        ("Mental Health Assessment", "Mental Health", 90),
        ("Individual Therapy - MH", "Mental Health", 60),
        ("Group Therapy - MH", "Mental Health", 90),
        ("Psychiatric Medication Management", "Mental Health", 30),
        ("Crisis Stabilization", "Crisis Services", 120),
        ("Case Management - MH", "Case Management", 45),
    ],
    "Bilingual SUD (Spanish)": [
        ("Consejería Individual (SUD)", "Substance Use Treatment", 60),
        ("Grupo de Terapia", "Substance Use Treatment", 90),
        ("Evaluación de Ingreso", "Substance Use Treatment", 90),
        ("Prueba de Drogas (UA)", "Substance Use Treatment", 15),
        ("Manejo de Caso", "Case Management", 45),
        ("DUII Educación (Español)", "Court-Mandated Education", 120),
    ],
}

NOTES_POOL = [
    "", "", "", "",   # most notes blank — realistic
    "No show - called to reschedule",
    "Late arrival 15 min",
    "Client reported housing instability",
    "Court report submitted",
    "Positive UA - addressed in session",
    "Client request: Spanish interpreter needed",
    "Family session requested for next visit",
    "Crisis line referral made",
    "MAT prescription updated",
    "Client transported by OnTrack van",
    "Zoom session (client no vehicle)",
    "Walk-in same-day appointment",
    "Rescheduled from last week",
    "DUII court date 30 days",
    "Refer to housing navigator",
    "Client reported job loss",
    "Spanish-speaking only — L. Strom or M. Oduya required",
]

# ── Generate clients ───────────────────────────────────────────────────────────
N_CLIENTS = 240

# Decide overall data-quality "tier" for each client
# Court-mandated → cleaner; street outreach → messier
QUALITY_TIERS = {
    "clean":  0.30,   # court, residential — good data
    "medium": 0.45,   # typical outpatient
    "dirty":  0.25,   # street referral, unstable, missing lots
}

def _quality():
    r = random.random()
    if r < 0.30: return "clean"
    if r < 0.75: return "medium"
    return "dirty"

clients = []
for i in range(1, N_CLIENTS + 1):
    q = _quality()
    is_female = random.random() < 0.42   # slightly more male in SUD programs
    gender    = "F" if is_female else "M"

    # ── Name ──────────────────────────────────────────────────────────────────
    legal_first = random.choice(FIRST_F if is_female else FIRST_M)
    last        = random.choice(LAST_NAMES)
    case_style  = random.choice(["proper", "proper", "proper", "upper", "lower"])

    # Dirty: use nickname, typo last name, or stuff middle initial in first
    if q == "dirty":
        # ~50% nickname instead of legal name
        if legal_first in NICKNAME_MAP and random.random() < 0.50:
            first = random.choice(NICKNAME_MAP[legal_first])
        else:
            first = legal_first
        # ~40% typo in last name
        if random.random() < 0.40:
            last = _typo(last)
        # ~20%: middle initial crammed into first_name field
        if random.random() < 0.20:
            first = first + " " + random.choice("ABCDEFGHJKLMNPRSTW") + "."
        case_style = random.choice(["upper", "lower", "proper", "proper"])
    elif q == "medium":
        if legal_first in NICKNAME_MAP and random.random() < 0.20:
            first = random.choice(NICKNAME_MAP[legal_first])
        else:
            first = legal_first
        if random.random() < 0.10:
            last = _typo(last)
    else:
        first = legal_first

    first = _case_mangle(first, case_style)
    last  = _case_mangle(last,  case_style)

    # ── DOB ───────────────────────────────────────────────────────────────────
    min_age, max_age = (15, 21) if "MIP" in random.choice(PROGRAMS) else (18, 70)
    dob_obj = _rand_dob(min_age, max_age)

    if q == "clean":
        dob_fmt = "iso"
    elif q == "medium":
        dob_fmt = random.choice(["iso", "iso", "us", "us_short"])
    else:  # dirty
        dob_fmt = random.choice(["us", "us_short", "year_only", "blank", "unknown",
                                  "us", "iso"])
    dob = _format_dob(dob_obj, dob_fmt)

    # ── SSN ───────────────────────────────────────────────────────────────────
    if q == "clean":
        ssn = _rand_ssn("full4")
    elif q == "medium":
        ssn = _rand_ssn(random.choice(["full4", "full4", "blank", "partial3"]))
    else:
        ssn = _rand_ssn(random.choice(["blank", "blank", "refused", "partial3", "full4"]))

    # ── Phone ─────────────────────────────────────────────────────────────────
    if q == "clean":
        phone_style = random.choice(["formatted", "dashes"])
    elif q == "medium":
        phone_style = random.choice(["formatted", "dashes", "raw", "blank"])
    else:
        phone_style = random.choice(["blank", "blank", "raw", "cell_label", "dashes"])
    phone = _rand_phone(phone_style)

    # ── Program & other fields ────────────────────────────────────────────────
    program  = random.choices(PROGRAMS, weights=PROGRAM_WEIGHTS, k=1)[0]
    is_court = program in ("DUII Education", "MIP Education") or (
        q != "dirty" and random.random() < 0.20)
    language = "Spanish" if (program == "Bilingual SUD (Spanish)"
                             or random.random() < 0.08) else "English"
    cm       = "M. Oduya" if language == "Spanish" else random.choice(CASE_MANAGERS[:-1])

    intake = _rand_date(SERVICE_START, date(2026, 6, 1))

    clients.append({
        "client_id":       f"OT-{i:06d}",
        "first_name":      first,
        "last_name":       last,
        "date_of_birth":   dob,
        "ssn_last4":       ssn,
        "phone":           phone,
        "gender":          gender if q != "dirty" or random.random() > 0.3 else "",
        "program_type":    program,
        "intake_date":     intake.strftime("%Y-%m-%d"),
        "primary_language": language,
        "court_mandated":  "Y" if is_court else "N",
        "case_manager":    cm if q != "dirty" or random.random() > 0.4 else "",
        "_dob_obj":        dob_obj,   # internal — stripped before CSV write
        "_program":        program,
    })

# ── Generate services ──────────────────────────────────────────────────────────
services   = []
svc_num    = 1

for c in clients:
    prog    = c["_program"]
    svc_pool = SERVICE_TYPES.get(prog, SERVICE_TYPES["Outpatient SUD"])
    intake  = date.fromisoformat(c["intake_date"])

    # 2x records → 8–14 visits per client (vs ~4 in other files)
    n_visits = random.randint(8, 14)
    # Court-mandated clients have more visits (compliance tracking)
    if c["court_mandated"] == "Y":
        n_visits = random.randint(12, 20)

    for _ in range(n_visits):
        stype, scat, dur = random.choice(svc_pool)

        # Service date after intake, within study window
        svc_end = min(SERVICE_END, intake + timedelta(days=730))
        svc_date = _rand_date(intake, svc_end)

        # Dirty records: date format inconsistency
        if c.get("court_mandated") == "N" and random.random() < 0.15:
            svc_date_str = svc_date.strftime("%m/%d/%Y")
        else:
            svc_date_str = svc_date.strftime("%Y-%m-%d")

        # Occasional duration typo (missing a zero — 9 instead of 90)
        if random.random() < 0.04:
            dur = dur // 10

        loc = random.choice(LOCATIONS)
        if "Bilingual" in prog or c.get("primary_language") == "Spanish":
            loc = "OnTrack Medford - 625 Stevens St"

        note = random.choice(NOTES_POOL)

        services.append({
            "service_id":       f"OT-SVC-{svc_num:06d}",
            "client_id":        c["client_id"],
            "service_date":     svc_date_str,
            "service_type":     stype,
            "service_category": scat,
            "duration_minutes": dur,
            "provider_name":    c["case_manager"] or random.choice(CASE_MANAGERS),
            "location":         loc,
            "notes":            note,
        })
        svc_num += 1

# ── Inject realistic cross-agency overlaps ─────────────────────────────────────
# A handful of OnTrack clients share names/DOBs with other agency records
# so the linkage engine has real cross-agency matches to find.
CROSS_AGENCY_SEEDS = [
    # (first, last, dob_iso) — these names appear in other generator name pools
    ("Sarah",  "Williams", "1985-03-15"),
    ("James",  "Johnson",  "1978-11-02"),
    ("Maria",  "Garcia",   "1992-06-30"),
    ("Robert", "Brown",    "1965-08-19"),
    ("Linda",  "Davis",    "1990-04-07"),
    ("Michael","Wilson",   "1983-09-25"),
    ("Karen",  "Jones",    "1975-12-01"),
    ("David",  "Martinez", "1988-05-14"),
]

# Overwrite a few client records with near-matches to cross-agency seeds
random.shuffle(CROSS_AGENCY_SEEDS)
n_overlaps = min(len(CROSS_AGENCY_SEEDS), 8)
overlap_indices = random.sample(range(N_CLIENTS), n_overlaps)

for idx, seed in zip(overlap_indices, CROSS_AGENCY_SEEDS):
    legal_f, legal_l, seed_dob = seed
    c = clients[idx]
    # Introduce slight variation to make matching probabilistic, not trivial
    use_nick = legal_f in NICKNAME_MAP and random.random() < 0.50
    c["first_name"] = random.choice(NICKNAME_MAP[legal_f]) if use_nick else _typo(legal_f)
    c["last_name"]  = legal_l if random.random() > 0.3 else _typo(legal_l)
    # DOB: 80% exact match, 20% off by a year (transcription error)
    d = date.fromisoformat(seed_dob)
    if random.random() < 0.20:
        d = d.replace(year=d.year + random.choice([-1, 1]))
    c["date_of_birth"] = d.strftime(
        "%Y-%m-%d" if random.random() > 0.3 else "%m/%d/%Y"
    )

# ── Write CSVs ─────────────────────────────────────────────────────────────────
CLIENT_FIELDS = [
    "client_id", "first_name", "last_name", "date_of_birth", "ssn_last4",
    "phone", "gender", "program_type", "intake_date", "primary_language",
    "court_mandated", "case_manager",
]
SVC_FIELDS = [
    "service_id", "client_id", "service_date", "service_type",
    "service_category", "duration_minutes", "provider_name", "location", "notes",
]

clients_path = os.path.join(INPUT_DIR, "ontrack_clients.csv")
with open(clients_path, "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=CLIENT_FIELDS, extrasaction="ignore")
    w.writeheader()
    w.writerows(clients)

services_path = os.path.join(INPUT_DIR, "ontrack_services.csv")
with open(services_path, "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=SVC_FIELDS, extrasaction="ignore")
    w.writeheader()
    w.writerows(services)

print(f"[OK] {clients_path}  — {len(clients):,} client records")
print(f"[OK] {services_path} — {len(services):,} service records")
print(f"     Avg visits/client: {len(services)/len(clients):.1f}")
print(f"     Cross-agency overlap seeds injected: {n_overlaps}")
print(f"\nOnTrack Rogue Valley synthetic data generation complete.")
print(f"  Programs represented: {len(PROGRAMS)}")
print(f"  Court-mandated clients: {sum(1 for c in clients if c['court_mandated']=='Y')}")
print(f"  Spanish-language clients: {sum(1 for c in clients if c['primary_language']=='Spanish')}")
print(f"  Missing SSN (blank/refused): {sum(1 for c in clients if not c['ssn_last4'] or c['ssn_last4']=='REFUSED')}")
print(f"  Missing phone: {sum(1 for c in clients if not c['phone'])}")

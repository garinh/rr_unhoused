"""
generate_stvdp.py — Synthetic data generator for St. Vincent de Paul (Ashland, OR)
Produces:
    input/stvdp_clients.csv
    input/stvdp_services.csv

Services: Community meals and food pantry visits.
Link key: client_id
"""

import csv
import os
import random
from datetime import date, timedelta

random.seed(2026)

INPUT_DIR = os.path.join(os.path.dirname(__file__), "input")
os.makedirs(INPUT_DIR, exist_ok=True)

# ── Name pools ─────────────────────────────────────────────────────────────────
FIRST_NAMES = [
    "James", "Mary", "Robert", "Patricia", "John", "Jennifer", "Michael",
    "Linda", "William", "Barbara", "David", "Susan", "Richard", "Jessica",
    "Joseph", "Sarah", "Thomas", "Karen", "Charles", "Lisa", "Daniel",
    "Nancy", "Matthew", "Betty", "Anthony", "Margaret", "Mark", "Sandra",
    "Donald", "Ashley", "Steven", "Dorothy", "Paul", "Kimberly", "Andrew",
    "Emily", "Kenneth", "Donna", "George", "Michelle", "Joshua", "Carol",
    "Kevin", "Amanda", "Brian", "Melissa", "Edward", "Deborah", "Ronald",
    "Stephanie", "Timothy", "Rebecca", "Jason", "Sharon", "Jeffrey", "Laura",
    "Ryan", "Cynthia", "Jacob", "Kathleen", "Gary", "Amy", "Nicholas",
    "Angela", "Eric", "Shirley", "Jonathan", "Anna", "Stephen", "Brenda",
    "Larry", "Pamela", "Justin", "Emma", "Scott", "Nicole", "Brandon",
    "Helen", "Benjamin", "Samantha", "Samuel", "Katherine", "Raymond",
    "Christine", "Gregory", "Debra", "Frank", "Rachel", "Alexander",
    "Carolyn", "Patrick", "Janet", "Jack", "Catherine", "Dennis", "Maria",
    "Jerry", "Heather", "Tyler", "Diane", "Aaron", "Julie", "Jose",
]

LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller",
    "Davis", "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez",
    "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson", "Martin",
    "Lee", "Perez", "Thompson", "White", "Harris", "Sanchez", "Clark",
    "Ramirez", "Lewis", "Robinson", "Walker", "Young", "Allen", "King",
    "Wright", "Scott", "Torres", "Nguyen", "Hill", "Flores", "Green",
    "Adams", "Nelson", "Baker", "Hall", "Rivera", "Campbell", "Mitchell",
    "Carter", "Roberts", "Phillips", "Evans", "Turner", "Diaz", "Parker",
    "Cruz", "Edwards", "Collins", "Reyes", "Stewart", "Morris", "Morales",
    "Murphy", "Cook", "Rogers", "Gutierrez", "Ortiz", "Morgan", "Cooper",
    "Peterson", "Bailey", "Reed", "Kelly", "Howard", "Ramos", "Kim",
    "Cox", "Ward", "Richardson", "Watson", "Brooks", "Chavez", "Wood",
]

MEAL_SERVICES = [
    "Community Dinner",
    "Hot Lunch Program",
    "Holiday Meal Service",
    "Weekend Breakfast",
    "Senior Meal Delivery",
]

PANTRY_SERVICES = [
    "Food Pantry Distribution",
    "Emergency Food Box",
    "SNAP Supplemental Bag",
    "Produce Market Day",
    "Shelf-Stable Pantry Visit",
    "Baby & Family Pantry",
]

ALL_SERVICES = MEAL_SERVICES + PANTRY_SERVICES

HOUSEHOLD_SIZES = [1, 1, 1, 2, 2, 3, 3, 4, 5, 6]

SERVICE_START = date(2025, 10, 1)
SERVICE_END   = date(2026, 10, 1)


def _rand_dob() -> str:
    # Adults 18–78
    days_back = random.randint(18 * 365, 78 * 365)
    return (date(2026, 1, 1) - timedelta(days=days_back)).strftime("%Y-%m-%d")


def _rand_phone() -> str:
    return f"541-555-{random.randint(1000, 9999)}"


def _rand_date(start: date = SERVICE_START, end: date = SERVICE_END) -> str:
    delta = (end - start).days
    return (start + timedelta(days=random.randint(0, delta))).strftime("%Y-%m-%d")


def _rand_ssn_last4() -> str:
    return f"{random.randint(1000, 9999)}"


# ── Generate clients ───────────────────────────────────────────────────────────
N_CLIENTS = 120

clients = []
for i in range(1, N_CLIENTS + 1):
    client_id = f"STVDP-{i:04d}"
    first     = random.choice(FIRST_NAMES)
    last      = random.choice(LAST_NAMES)
    dob       = _rand_dob()
    phone     = _rand_phone()
    household = random.choice(HOUSEHOLD_SIZES)
    # ~60% have SSN on file (food pantry requirement for some programs)
    ssn_last4 = _rand_ssn_last4() if random.random() < 0.60 else ""
    intake    = _rand_date(SERVICE_START, date(2026, 3, 1))

    clients.append({
        "client_id":      client_id,
        "first_name":     first,
        "last_name":      last,
        "date_of_birth":  dob,
        "phone":          phone,
        "household_size": household,
        "ssn_last4":      ssn_last4,
        "intake_date":    intake,
    })

# ── Write clients CSV ──────────────────────────────────────────────────────────
clients_path = os.path.join(INPUT_DIR, "stvdp_clients.csv")
with open(clients_path, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=list(clients[0].keys()))
    writer.writeheader()
    writer.writerows(clients)

print(f"[OK] Wrote {len(clients)} clients → {clients_path}")

# ── Generate services ──────────────────────────────────────────────────────────
services   = []
visit_num  = 1

for client in clients:
    cid  = client["client_id"]
    # Each client gets 2–8 service visits
    n_visits = random.randint(2, 8)
    for _ in range(n_visits):
        svc_type = random.choice(ALL_SERVICES)
        is_pantry = svc_type in PANTRY_SERVICES
        services.append({
            "visit_id":        f"STVDP-VST-{visit_num:05d}",
            "client_id":       cid,
            "service_date":    _rand_date(),
            "service_type":    svc_type,
            "service_category": "Food Pantry" if is_pantry else "Community Meal",
            "household_served": client["household_size"],
            "lbs_food_provided": (
                random.randint(15, 60) if is_pantry else ""
            ),
            "meals_provided": (
                "" if is_pantry else client["household_size"]
            ),
            "location":        "St. Vincent de Paul — 1632 Ashland St, Ashland OR 97520",
            "volunteer_name":  random.choice([
                "Sr. Margaret", "Bob K.", "Diane R.", "Tom V.", "Ana L.",
                "Carlos M.", "Patricia W.", "Fr. Joseph", "Helen S.",
            ]),
        })
        visit_num += 1

# ── Write services CSV ─────────────────────────────────────────────────────────
services_path = os.path.join(INPUT_DIR, "stvdp_services.csv")
with open(services_path, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=list(services[0].keys()))
    writer.writeheader()
    writer.writerows(services)

print(f"[OK] Wrote {len(services)} service records → {services_path}")
print(f"\nSt. Vincent de Paul synthetic data generation complete.")
print(f"  Clients : {len(clients)}")
print(f"  Services: {len(services)}")
print(f"  Avg visits/client: {len(services)/len(clients):.1f}")

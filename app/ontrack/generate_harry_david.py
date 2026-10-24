"""
generate_harry_david.py — Harry & David Community Food & Essentials Program
Medford, OR · Synthetic data for Rogue Raise hackathon demo

Output:
  input/harry_david_clients.csv   (75 clients, 8 cross-agency overlap seeds)
  input/harry_david_services.csv  (~220 service rows)

Column names are intentionally non-standard to exercise the TPM column mapper:
  hd_id, first_name, last_name, birthday, last_ssn, phone_number,
  household_size, zip, enrollment_date
  (services: svc_id, hd_client_id, visit_date, program_type, items_provided, site_location)
"""

import csv
import os
import random
from datetime import date, timedelta

random.seed(2026_12)

INPUT_DIR = os.path.join(os.path.dirname(__file__), "input")
os.makedirs(INPUT_DIR, exist_ok=True)

# ── Name pools ────────────────────────────────────────────────────────────────
_M = ["James", "John", "Robert", "Michael", "William", "David", "Joseph", "Charles",
      "Thomas", "Daniel", "Mark", "Anthony", "Paul", "Andrew", "Joshua",
      "Kevin", "Brian", "George", "Timothy", "Gary", "Larry", "Frank", "Eric",
      "Scott", "Jason", "Jeffrey", "Ryan", "Jacob", "Raymond", "Steven", "Donald",
      "Ronald", "Harold", "Walter", "Patrick", "Dennis", "Jerry", "Henry", "Carl"]
_F = ["Mary", "Patricia", "Jennifer", "Linda", "Barbara", "Susan", "Jessica",
      "Sarah", "Karen", "Lisa", "Nancy", "Betty", "Margaret", "Sandra",
      "Ashley", "Dorothy", "Kimberly", "Emily", "Donna", "Michelle",
      "Carol", "Amanda", "Melissa", "Deborah", "Stephanie", "Rebecca", "Laura",
      "Sharon", "Cynthia", "Kathleen", "Amy", "Angela", "Shirley", "Anna",
      "Ruth", "Virginia", "Kathleen", "Pamela", "Martha", "Brenda"]
_L = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis",
      "Rodriguez", "Martinez", "Hernandez", "Lopez", "Wilson", "Anderson", "Taylor",
      "Thomas", "Moore", "Jackson", "White", "Harris", "Martin", "Thompson",
      "Rivera", "Carter", "Lee", "Walker", "Hall", "Young", "King", "Scott",
      "Green", "Baker", "Nelson", "Mitchell", "Perez", "Roberts", "Turner",
      "Campbell", "Parker", "Evans", "Edwards", "Collins", "Stewart", "Sanchez",
      "Morris", "Rogers", "Reed", "Cook", "Bailey", "Bell", "Murphy", "Cooper"]
_NICK = {
    "Robert": "Bob", "William": "Bill", "Michael": "Mike", "James": "Jim",
    "Thomas": "Tom", "Joseph": "Joe", "Richard": "Rick", "Christopher": "Chris",
    "Timothy": "Tim", "Kenneth": "Ken", "Charles": "Charlie", "Daniel": "Dan",
    "Patricia": "Pat", "Jennifer": "Jenny", "Margaret": "Maggie", "Barbara": "Barb",
    "Elizabeth": "Liz", "Katherine": "Kathy", "Dorothy": "Dot", "Rebecca": "Becky",
    "Sandra": "Sandy", "Jessica": "Jessie", "Deborah": "Deb", "Stephanie": "Steph",
}
_PROGRAMS = [
    "Emergency Food Box - Standard",
    "Emergency Food Box - Family",
    "Holiday Gift Basket Distribution",
    "Pear Harvest Share",
    "Moose Munch Community Pack",
    "Truffle & Confections Box",
    "Seasonal Fruit Box",
    "Harry & David Pantry Staples Kit",
    "Community Meal Voucher",
    "Weekend Food Box",
    "Senior Nutrition Pack",
    "Partner Referral: Meals on Wheels",
]
_SITES = [
    "HD Distribution Center - Medford",
    "St. Matthew's Church - Ashland",
    "Peace House Drop-In - Ashland",
    "Rogue Valley YMCA - Medford",
    "Jackson County Fairgrounds - Central Point",
    "Salvation Army - Medford",
]

# ── Helpers ───────────────────────────────────────────────────────────────────
def _rand_dob(y0=1945, y1=2004):
    start = date(y0, 1, 1)
    return start + timedelta(days=random.randint(0, (date(y1, 12, 31) - start).days))

def _dirty_dob(d):
    fmt = random.choices(
        ["iso", "mdy4", "mdy2", "year_only", "blank", "unknown"],
        weights=[35, 30, 15, 10, 7, 3],
    )[0]
    if fmt == "iso":       return d.strftime("%Y-%m-%d")
    if fmt == "mdy4":      return f"{d.month}/{d.day}/{d.year}"
    if fmt == "mdy2":      return f"{d.month}/{d.day}/{str(d.year)[2:]}"
    if fmt == "year_only": return str(d.year)
    if fmt == "blank":     return ""
    return "UNKNOWN"

def _dirty_name(n):
    r = random.random()
    if r < 0.13: return n.upper()
    if r < 0.23: return n.lower()
    return n

def _ssn_or_blank(n):
    return "" if random.random() < 0.28 else str(n).zfill(4)

def _phone_or_blank():
    return "" if random.random() < 0.20 else f"541-555-{random.randint(1000,9999)}"

def _maybe_middle(first):
    if random.random() < 0.08:
        return f"{first} {random.choice('ABCDJKLMNRST')}."
    return first

def _maybe_nick(first):
    if random.random() < 0.15 and first in _NICK:
        return _NICK[first]
    return first

# ── Cross-agency overlap seeds ────────────────────────────────────────────────
# Each entry deliberately varies from the source record (dirty data realism).
# Source records confirmed from existing CSVs.
#
#  Seed | Name in H&D         | Matches                                   | Dirty delta
#  -----|---------------------|-------------------------------------------|---------------------------
#  1    | Lynda Jonhson       | ACC-001 "iLnda Johnson" / RR-001 / RC-001 | transposed last name, mdy DOB
#  2    | TOM SCOTT           | ACC-009 / RR-010 DOB 1955-24-11           | ALL CAPS, year-only DOB
#  3    | Maggie Perez        | RR-003 / RC-003 DOB 1972-03-07            | nickname, mdy DOB
#  4    | Kenny Johnson       | RR-002 DOB 1990-04-23 / RC-002 1/1/1990  | nickname, 2-digit year
#  5    | Robert Hill         | RR-006 "Bob Hill" DOB 1995-03-18 ssn 5010 | legal name, DOB +1 day
#  6    | Jessika Gonzales    | RR-018 "Jessica Gonzalez" DOB 1967-09-15  | misspelled first+last, 2-yr
#  7    | sandy wright        | RR-004 1962-03-07 ssn5803 / RC-004 7/3/62 | lowercase, DOB m/d transposed
#  8    | Erik Thompson       | OT-000011 "Eric Thompson" DOB 1980-10-23  | misspelled first, short yr

OVERLAP_SEEDS = [
    {"hd_id":"HD-0000001","first_name":"Lynda",   "last_name":"Jonhson",   "birthday":"5/8/2002",   "last_ssn":"",     "phone_number":"",             "household_size":1,"zip":"97520","enrollment_date":"2026-01-15"},
    {"hd_id":"HD-0000002","first_name":"TOM",     "last_name":"SCOTT",     "birthday":"1955",        "last_ssn":"2876", "phone_number":"541-555-3301", "household_size":1,"zip":"97501","enrollment_date":"2026-02-03"},
    {"hd_id":"HD-0000003","first_name":"Maggie",  "last_name":"Perez",     "birthday":"3/7/1972",   "last_ssn":"",     "phone_number":"541-555-8812", "household_size":2,"zip":"97504","enrollment_date":"2026-03-18"},
    {"hd_id":"HD-0000004","first_name":"Kenny",   "last_name":"Johnson",   "birthday":"4/23/90",    "last_ssn":"",     "phone_number":"",             "household_size":1,"zip":"97501","enrollment_date":"2026-04-05"},
    {"hd_id":"HD-0000005","first_name":"Robert",  "last_name":"Hill",      "birthday":"1995-03-19", "last_ssn":"5010", "phone_number":"541-555-7041", "household_size":1,"zip":"97520","enrollment_date":"2026-02-22"},
    {"hd_id":"HD-0000006","first_name":"Jessika", "last_name":"Gonzales",  "birthday":"9/15/67",    "last_ssn":"",     "phone_number":"541-555-2290", "household_size":3,"zip":"97504","enrollment_date":"2026-01-30"},
    {"hd_id":"HD-0000007","first_name":"sandy",   "last_name":"wright",    "birthday":"1962-07-03", "last_ssn":"5803", "phone_number":"",             "household_size":1,"zip":"97501","enrollment_date":"2026-05-11"},
    {"hd_id":"HD-0000008","first_name":"Erik",    "last_name":"Thompson",  "birthday":"10/23/80",   "last_ssn":"8979", "phone_number":"541-555-6144", "household_size":2,"zip":"97501","enrollment_date":"2026-03-07"},
]

# ── Fresh Harry & David-only clients ─────────────────────────────────────────
def _build_clients():
    rows = list(OVERLAP_SEEDS)
    for i in range(9, 76):
        gender = random.choice(["M","M","F","F","F","NB"])
        first  = random.choice(_M if gender == "M" else _F)
        first  = _maybe_nick(first)
        first  = _maybe_middle(first)
        last   = random.choice(_L)
        dob    = _rand_dob()
        ssn4   = random.randint(1000, 9999)
        enroll = date(2025, 9, 1) + timedelta(days=random.randint(0, 395))
        rows.append({
            "hd_id":          f"HD-{i:07d}",
            "first_name":     _dirty_name(first),
            "last_name":      _dirty_name(last),
            "birthday":       _dirty_dob(dob),
            "last_ssn":       _ssn_or_blank(ssn4),
            "phone_number":   _phone_or_blank(),
            "household_size": random.choice([1,1,1,2,2,3,4]),
            "zip":            random.choice(["97501","97504","97520","97523","97527","97501","97501"]),
            "enrollment_date": enroll.isoformat(),
        })
    return rows

# ── Service records ───────────────────────────────────────────────────────────
def _build_services(clients):
    rows = []
    ctr = 1
    for c in clients:
        try:
            base = date.fromisoformat(c["enrollment_date"])
        except ValueError:
            base = date(2025, 11, 1)
        n_visits = random.randint(1, 7)
        for _ in range(n_visits):
            visit = base + timedelta(days=random.randint(0, 330))
            rows.append({
                "svc_id":        f"HD-SVC-{ctr:05d}",
                "hd_client_id":  c["hd_id"],
                "visit_date":    visit.isoformat(),
                "program_type":  random.choice(_PROGRAMS),
                "items_provided": random.choice([
                    "Moose Munch Popcorn, Royal Riviera Pears",
                    "Truffles, Moose Munch",
                    "Royal Riviera Pears",
                    "Moose Munch Popcorn",
                    "Truffles & Confections",
                    "Pears, Truffles, Moose Munch",
                    "Seasonal Fruit Assortment",
                    "Pantry Staples + Pears",
                    "Truffles",
                    "Holiday Gift Assortment",
                ]),
                "site_location": random.choice(_SITES),
            })
            ctr += 1
    return rows

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    clients  = _build_clients()
    services = _build_services(clients)

    c_path = os.path.join(INPUT_DIR, "harry_david_clients.csv")
    s_path = os.path.join(INPUT_DIR, "harry_david_services.csv")

    c_fields = ["hd_id","first_name","last_name","birthday","last_ssn",
                "phone_number","household_size","zip","enrollment_date"]
    with open(c_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=c_fields, extrasaction="ignore")
        w.writeheader(); w.writerows(clients)

    s_fields = ["svc_id","hd_client_id","visit_date","program_type","items_provided","site_location"]
    with open(s_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=s_fields)
        w.writeheader(); w.writerows(services)

    print(f"[OK] harry_david_clients.csv   — {len(clients)} clients  ({len(OVERLAP_SEEDS)} cross-agency seeds)")
    print(f"[OK] harry_david_services.csv  — {len(services)} service rows")
    print("\nCross-agency overlap seeds (dirty deltas vs. source records):")
    for s in OVERLAP_SEEDS:
        print(f"  {s['hd_id']}  {s['first_name']:<12s} {s['last_name']:<14s}  DOB: {s['birthday']}")

if __name__ == "__main__":
    main()

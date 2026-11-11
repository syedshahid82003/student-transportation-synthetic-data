"""
backend/app/generators/master_data.py
--------------------------------------
Deterministic master-data generator for the Student Transportation system.

Design rules
------------
* Single RNG: ``numpy.random.default_rng(SEED)`` — no global random state,
  no stdlib random, no Faker seeding.  All randomness flows through one
  generator object passed top-down so the call order alone determines output.
* Parents before children: zones → stops → buses → drivers → students →
  guardian_contacts.  Every FK is validated before the DataFrame is returned.
* Field names match database/validators/*.json exactly.
* All personal data (names, phones, emails) is fully synthetic.
  - Names come from fixed fictional word-lists embedded here.
  - Phones use the fictional 555-XXXX NXX code (555-0100 to 555-0199)
    with area codes 200–999 (non-geographic).
  - Emails use @example.com (RFC 2606 reserved).
* No real PII is generated.
"""

from __future__ import annotations

import datetime
import math
from typing import Any

import numpy as np
import pandas as pd

from backend.app.core.config import SCALES, SCHOOL_CALENDAR_START, SCHOOL_YEAR, SEED
from backend.app.core.ids import (
    bus_id,
    driver_id,
    guardian_id,
    route_id,
    stop_id,
    student_id,
    zone_id,
)

# ---------------------------------------------------------------------------
# Fictional name pools
# (All entries are invented; no connection to real people.)
# ---------------------------------------------------------------------------

_FIRST_NAMES: list[str] = [
    "Aelin", "Brix", "Calyx", "Doran", "Elowen", "Favin", "Gael", "Hira",
    "Idris", "Jova", "Kael", "Lysa", "Maren", "Niko", "Orin", "Pella",
    "Quill", "Reva", "Solen", "Tara", "Ulan", "Vira", "Wren", "Xael",
    "Yori", "Zael", "Arden", "Blyth", "Ciran", "Demi", "Elian", "Faye",
    "Gidra", "Helix", "Iora", "Juren", "Kessa", "Lorne", "Myra", "Nael",
    "Oban", "Pryn", "Quora", "Rael", "Silas", "Tova", "Uvine", "Vael",
    "Wyla", "Xora", "Yela", "Zane", "Alyx", "Bren", "Cove", "Dael",
    "Esrin", "Fren", "Gova", "Hael", "Iren", "Jael", "Kova", "Lael",
]

_LAST_NAMES: list[str] = [
    "Ashveil", "Brindal", "Carwick", "Dawnmore", "Edgeholm", "Frostwyn",
    "Galveth", "Harwick", "Ironfeld", "Jarvik", "Keldrun", "Lochwin",
    "Morrow", "Northgate", "Orvyn", "Pinecroft", "Quelmar", "Ridgemont",
    "Stonecross", "Thistlewood", "Underhill", "Vexmore", "Westholm",
    "Xanthvale", "Yarwick", "Zephyrton", "Aldmar", "Blackfen", "Corvin",
    "Dunvale", "Eldwick", "Farholm", "Greystone", "Halwick", "Ironwood",
    "Jaspervale", "Keldwick", "Lornfeld", "Moorgate", "Netherwick",
    "Oakveil", "Pemberton", "Quarrystone", "Rookwood", "Silverwick",
    "Thornfield", "Umbervale", "Virelwood", "Whitmore", "Yarfield",
]

_ZONE_DESCRIPTORS: list[str] = [
    "Ashwood", "Birchfield", "Cedarvale", "Duskhollow", "Elmwood",
    "Ferndale", "Glenwood", "Hillcrest", "Ironwood", "Jadefield",
    "Knotwood", "Larchmont", "Maplewood", "Northfield", "Oakdale",
    "Pinewood", "Quarryhill", "Ridgewood", "Silverdale", "Thornfield",
    "Underwood", "Valewood", "Westfield", "Xerophyte", "Yewdale",
    "Zetherwood", "Alderwood", "Briarfield", "Copperwood", "Dustwood",
]

_STREET_NAMES: list[str] = [
    "Maple Ave", "Oak St", "Pine Rd", "Elm Blvd", "Cedar Ln",
    "Birch Dr", "Spruce Way", "Larch Ct", "Walnut St", "Chestnut Ave",
    "Willow Rd", "Ash Ln", "Poplar Blvd", "Sycamore Dr", "Fir Way",
]

_BUS_MAKES: list[str] = ["BlueStar", "TransCo", "SafeRide", "ScholarBus"]
_BUS_MODELS: list[str] = ["C200", "D300", "E400", "F500"]
_CAPACITIES: list[int] = [24, 36, 48, 54]
_ZONE_TYPES: list[str] = [
    "elementary", "middle", "high", "mixed", "special_education"
]
_RELATIONSHIPS: list[str] = [
    "parent", "legal_guardian", "emergency_contact", "other"
]
_NOTIFICATION_PREFS: list[list[str]] = [
    ["sms"], ["email"], ["push"], ["sms", "email"], ["email", "push"],
]

# Geographic bounding box — fictional midwestern-style grid, no real city.
_LAT_MIN, _LAT_MAX = 41.60, 42.00
_LNG_MIN, _LNG_MAX = -88.40, -87.80

# Approval rule: 92 % of stops are approved at generation time.
# The remaining 8 % are set to pending_approval (unapproved) to represent
# newly proposed stops that have not yet completed the safety review process.
STOP_APPROVAL_RATE: float = 0.92

# Accessibility rule: at least 25% of buses carry wheelchair lifts, minimum 5.
BUS_ACCESSIBILITY_RATE: float = 0.25

# Student accessibility rule: approximately 6 % of students require an
# accessible vehicle.
STUDENT_ACCESSIBILITY_RATE: float = 0.06

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_NOW = datetime.datetime(2025, 9, 1, 0, 0, 0)  # deterministic "created_at"
_EFF = datetime.date(2025, 9, 1)               # effective_from baseline


def _pick(rng: np.random.Generator, pool: list, size: int) -> np.ndarray:
    """Sample *size* items from *pool* with replacement."""
    return rng.choice(pool, size=size, replace=True)


def _unique_strings(
    rng: np.random.Generator,
    prefix: str,
    n: int,
    length: int = 6,
) -> list[str]:
    """Generate *n* unique fixed-length alphanumeric strings with *prefix*."""
    seen: set[str] = set()
    out: list[str] = []
    chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no O/0/1/I ambiguity
    while len(out) < n:
        batch = rng.choice(list(chars), size=(n * 2, length))
        for row in batch:
            s = prefix + "".join(row)
            if s not in seen:
                seen.add(s)
                out.append(s)
                if len(out) == n:
                    break
    return out


def _dob_for_grade(rng: np.random.Generator, grade: int) -> datetime.date:
    """Return a plausible date-of-birth for a student in *grade*."""
    # Age at start of school year (Sep 1, 2025): grade + 5 (K=5, G12=17)
    age = grade + 5
    birth_year = 2025 - age
    # Vary birthday ± 6 months around Sep 1 of birth year
    base = datetime.date(birth_year, 9, 1)
    offset = int(rng.integers(-180, 181))
    return base + datetime.timedelta(days=offset)


# ---------------------------------------------------------------------------
# Individual collection generators
# ---------------------------------------------------------------------------


def _gen_zones(rng: np.random.Generator, n: int) -> pd.DataFrame:
    """Generate *n* address_zones rows."""
    # Zone type distribution: roughly equal across the 5 types
    type_weights = np.array([0.25, 0.20, 0.20, 0.25, 0.10])
    type_weights /= type_weights.sum()
    types = rng.choice(_ZONE_TYPES, size=n, p=type_weights)

    # Names must be unique; use the descriptor list (len == 30, matches n=30)
    names = _ZONE_DESCRIPTORS[:n]

    rows = []
    for i in range(n):
        rows.append(
            {
                "_id":        zone_id(i + 1),
                "name":       f"{names[i]} District",
                "zone_type":  types[i],
                "created_at": _NOW,
                "updated_at": _NOW,
            }
        )
    return pd.DataFrame(rows)


def _gen_stops(
    rng: np.random.Generator, n: int, zone_ids: list[str]
) -> pd.DataFrame:
    """Generate *n* stops, each assigned to one of *zone_ids*.

    Zone seeding rule
    -----------------
    Every zone is seeded with exactly ONE approved stop before the remaining
    stops are distributed randomly.  This guarantees every zone has at least
    one approved stop, which the route generator requires to place any route
    stops in that zone.

    The seeded stops count toward the total *n*.  If n < len(zone_ids), only
    the first n zones get a seeded stop (n is always >= n_zones in practice).

    Approval rule
    -------------
    Seeded stops are always approved (is_approved=True, status='active').
    Of the remaining stops, ~92 % are approved; ~8 % are unapproved
    (pending_approval) representing stops awaiting safety review.
    """
    n_zones = len(zone_ids)
    # We need at least n_zones stops to seed one per zone
    n_seed  = min(n_zones, n)
    n_extra = n - n_seed          # remaining stops distributed freely

    # --- Generate seeded stops (one approved per zone, first n_seed zones) ---
    seed_lats  = rng.uniform(_LAT_MIN, _LAT_MAX, size=n_seed)
    seed_lngs  = rng.uniform(_LNG_MIN, _LNG_MAX, size=n_seed)
    seed_nums  = rng.integers(100, 9999, size=n_seed)
    seed_names = _pick(rng, _STREET_NAMES, n_seed)
    seed_acc   = rng.random(size=n_seed) < 0.70

    rows = []
    for i in range(n_seed):
        rows.append(
            {
                "_id":            stop_id(i + 1),
                "name":           f"Stop {i + 1:04d}",
                "lat":            float(round(seed_lats[i], 6)),
                "lng":            float(round(seed_lngs[i], 6)),
                "street_address": f"{seed_nums[i]} {seed_names[i]}",
                "zone_id":        zone_ids[i],       # one-to-one with zone
                "is_approved":    True,              # seeded stops always approved
                "is_accessible":  bool(seed_acc[i]),
                "status":         "active",
                "created_at":     _NOW,
                "updated_at":     _NOW,
            }
        )

    # --- Generate remaining stops distributed across all zones ---
    if n_extra > 0:
        extra_zones   = rng.choice(zone_ids, size=n_extra, replace=True)
        extra_lats    = rng.uniform(_LAT_MIN, _LAT_MAX, size=n_extra)
        extra_lngs    = rng.uniform(_LNG_MIN, _LNG_MAX, size=n_extra)
        # Apply 92% approval rate to extra stops only
        extra_approved = rng.random(size=n_extra) < STOP_APPROVAL_RATE
        extra_acc      = rng.random(size=n_extra) < 0.70
        extra_nums     = rng.integers(100, 9999, size=n_extra)
        extra_names    = _pick(rng, _STREET_NAMES, n_extra)

        for j in range(n_extra):
            idx = n_seed + j + 1
            approved = bool(extra_approved[j])
            rows.append(
                {
                    "_id":            stop_id(idx),
                    "name":           f"Stop {idx:04d}",
                    "lat":            float(round(extra_lats[j], 6)),
                    "lng":            float(round(extra_lngs[j], 6)),
                    "street_address": f"{extra_nums[j]} {extra_names[j]}",
                    "zone_id":        extra_zones[j],
                    "is_approved":    approved,
                    "is_accessible":  bool(extra_acc[j]),
                    "status":         "active" if approved else "pending_approval",
                    "created_at":     _NOW,
                    "updated_at":     _NOW,
                }
            )

    return pd.DataFrame(rows)


def _gen_buses(rng: np.random.Generator, n: int, n_students: int) -> pd.DataFrame:
    """Generate *n* buses sized to cover ~108% of student demand.

    Capacity sizing rule
    --------------------
    Total seat capacity targets 108% of *n_students*.  Bus capacities are
    drawn from {24, 36, 48, 54} with weights adjusted so the fleet total
    meets that target while keeping variety.

    Accessibility rule
    ------------------
    At least 25% of buses are accessible (is_accessible=True), with a
    minimum of 5 at any scale.  Accessible buses always have capacity >= 36.

    Note: the route generator may need more accessible buses than the 25%
    minimum if many zones have accessibility students.  The minimum is set
    conservatively; the actual count is controlled by BUS_ACCESSIBILITY_RATE.
    """
    # Capacity weights: favour 36 and 48 to reach the target efficiently
    cap_pool    = [24, 36, 48, 54]
    cap_weights = np.array([0.10, 0.35, 0.40, 0.15])
    cap_weights = cap_weights / cap_weights.sum()
    capacities  = rng.choice(cap_pool, size=n, replace=True, p=cap_weights)

    # Accessibility: min(max(ceil(0.25*n), 5), n) accessible buses
    min_accessible = max(5, int(math.ceil(n * BUS_ACCESSIBILITY_RATE)))
    min_accessible = min(min_accessible, n)

    accessible_mask = np.zeros(n, dtype=bool)
    accessible_mask[:min_accessible] = True
    rng.shuffle(accessible_mask)

    makes  = _pick(rng, _BUS_MAKES,  n)
    models = _pick(rng, _BUS_MODELS, n)
    years  = rng.integers(2010, 2026, size=n)
    plates = _unique_strings(rng, "TS", n, length=4)

    rows = []
    for i in range(n):
        accessible = bool(accessible_mask[i])
        cap = int(capacities[i])
        if accessible and cap < 36:
            cap = 36
        rows.append(
            {
                "_id":           bus_id(i + 1),
                "license_plate": plates[i],
                "make":          makes[i],
                "model":         models[i],
                "year":          int(years[i]),
                "capacity":      cap,
                "is_accessible": accessible,
                "status":        "active",
                "effective_from": _EFF,
                "effective_to":   None,
                "created_at":    _NOW,
                "updated_at":    _NOW,
            }
        )
    return pd.DataFrame(rows)


def _gen_drivers(rng: np.random.Generator, bus_df: pd.DataFrame) -> pd.DataFrame:
    """Generate one driver per bus row in *bus_df*."""
    n = len(bus_df)
    first_names = _pick(rng, _FIRST_NAMES, n)
    last_names  = _pick(rng, _LAST_NAMES,  n)

    # License classes: B covers standard school buses; A covers articulated.
    license_classes = rng.choice(["A", "B", "C"], size=n, p=[0.15, 0.70, 0.15])

    # Unique 8-char alphanumeric CDL numbers
    license_numbers = _unique_strings(rng, "CDL", n, length=8)

    # Expiry: 1–5 years from effective date
    expiry_offsets = rng.integers(365, 5 * 365, size=n)

    # Phones: fictional 555-01xx numbers with non-geographic area codes
    area_codes  = rng.integers(200, 1000, size=n)
    line_nums   = rng.integers(100, 200, size=n)   # 555-0100 to 555-0199
    extra_digits = rng.integers(0, 10, size=n)
    phones = [
        f"{area_codes[i]:03d}5550{line_nums[i]:03d}"[:10]
        for i in range(n)
    ]

    rows = []
    for i in range(n):
        expiry = _EFF + datetime.timedelta(days=int(expiry_offsets[i]))
        rows.append(
            {
                "_id":            driver_id(i + 1),
                "first_name":     first_names[i],
                "last_name":      last_names[i],
                "license_number": license_numbers[i],
                "license_class":  license_classes[i],
                "license_expiry": expiry,
                "phone":          phones[i],
                "status":         "active",
                "bus_id":         bus_df.iloc[i]["_id"],  # 1-to-1 assignment
                "created_at":     _NOW,
                "updated_at":     _NOW,
            }
        )
    return pd.DataFrame(rows)


def _gen_students(
    rng: np.random.Generator, n: int, zone_ids: list[str]
) -> pd.DataFrame:
    """Generate *n* students with zone assignments weighted by population.

    Zone weighting
    --------------
    Zones are assigned a synthetic "population weight" drawn once from a
    Dirichlet distribution (alpha=1 for each zone) so that some zones
    naturally have more students — a realistic distribution without any
    real data.
    """
    n_zones = len(zone_ids)
    # Draw population weights from Dirichlet(alpha=1) → uniform on simplex
    zone_weights = rng.dirichlet(np.ones(n_zones))
    assigned_zones = rng.choice(zone_ids, size=n, p=zone_weights, replace=True)

    grades = rng.integers(0, 13, size=n)  # 0–12 inclusive
    first_names = _pick(rng, _FIRST_NAMES, n)
    last_names  = _pick(rng, _LAST_NAMES,  n)
    access_mask = rng.random(size=n) < STUDENT_ACCESSIBILITY_RATE

    rows = []
    for i in range(n):
        grade = int(grades[i])
        dob   = _dob_for_grade(rng, grade)
        rows.append(
            {
                "_id":                   student_id(i + 1),
                "first_name":            first_names[i],
                "last_name":             last_names[i],
                "date_of_birth":         datetime.datetime(
                                             dob.year, dob.month, dob.day
                                         ),
                "grade":                 grade,
                "zone_id":               assigned_zones[i],
                "guardian_ids":          [],   # filled in after guardians generated
                "accessibility_required": bool(access_mask[i]),
                "status":                "active",
                "effective_from":        _EFF,
                "effective_to":          None,
                "created_at":            _NOW,
                "updated_at":            _NOW,
            }
        )
    return pd.DataFrame(rows)


def _gen_guardians(
    rng: np.random.Generator, student_df: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Generate 1–2 guardian_contacts per student.

    Returns
    -------
    guardians_df :
        DataFrame of guardian_contacts rows.
    students_updated :
        Copy of *student_df* with ``guardian_ids`` column populated.
    """
    n_students = len(student_df)

    # Decide how many guardians per student (1 or 2)
    counts = rng.choice([1, 2], size=n_students, p=[0.35, 0.65])
    total_guardians = int(counts.sum())

    first_names   = _pick(rng, _FIRST_NAMES, total_guardians)
    last_names    = _pick(rng, _LAST_NAMES,  total_guardians)
    relationships = rng.choice(
        _RELATIONSHIPS, size=total_guardians,
        p=[0.55, 0.25, 0.10, 0.10],
    )
    notif_prefs = rng.choice(
        list(range(len(_NOTIFICATION_PREFS))), size=total_guardians
    )

    # Phones: 555-01xx style (fictional), 10 digits
    area_codes = rng.integers(200, 1000, size=total_guardians)
    line_nums  = rng.integers(100, 200,  size=total_guardians)
    # Build 10-digit strings: AAA5550LLL — always exactly 10 chars
    phones = [
        f"{area_codes[i]:03d}5550{line_nums[i]:03d}"[:10]
        for i in range(total_guardians)
    ]

    # Email slugs
    email_slugs = [
        f"{first_names[i].lower()}.{last_names[i].lower()}{i + 1}"
        for i in range(total_guardians)
    ]

    guardian_rows: list[dict] = []
    student_guardian_map: dict[str, list[str]] = {}  # student_id → [grd_id, …]

    grd_counter = 1
    for s_idx in range(n_students):
        stu_id = student_df.iloc[s_idx]["_id"]
        student_guardian_map[stu_id] = []
        for _ in range(counts[s_idx]):
            g_idx = grd_counter - 1
            grd_id = guardian_id(grd_counter)
            guardian_rows.append(
                {
                    "_id":           grd_id,
                    "first_name":    first_names[g_idx],
                    "last_name":     last_names[g_idx],
                    "relationship":  relationships[g_idx],
                    "phone_primary": phones[g_idx],
                    "email":         f"{email_slugs[g_idx]}@example.com",
                    "contact_status": "VALID",
                    "is_valid":      True,
                    "notification_preferences": list(
                        _NOTIFICATION_PREFS[notif_prefs[g_idx]]
                    ),
                    "created_at":    _NOW,
                    "updated_at":    _NOW,
                    # Back-reference — not in schema but useful for FK tests
                    "student_id":    stu_id,
                }
            )
            student_guardian_map[stu_id].append(grd_id)
            grd_counter += 1

    # Populate guardian_ids on students
    students_updated = student_df.copy()
    students_updated["guardian_ids"] = students_updated["_id"].map(
        student_guardian_map
    )

    return pd.DataFrame(guardian_rows), students_updated


# ---------------------------------------------------------------------------
# Top-level entry point
# ---------------------------------------------------------------------------


def generate_master_data(scale: str = "starter") -> dict[str, pd.DataFrame]:
    """Generate all master-data collections for the given *scale*.

    Parameters
    ----------
    scale:
        One of ``"starter"`` or ``"full"``.

    Returns
    -------
    dict[str, pd.DataFrame]
        Keys: ``"address_zones"``, ``"stops"``, ``"buses"``, ``"drivers"``,
        ``"students"``, ``"guardian_contacts"``.

    Generation order (parents before children)
    -------------------------------------------
    1. address_zones
    2. stops          (references address_zones)
    3. buses
    4. drivers        (references buses)
    5. students       (references address_zones)
    6. guardian_contacts (references students)
    """
    if scale not in SCALES:
        raise ValueError(f"scale must be 'starter' or 'full', got '{scale}'")

    cfg = SCALES[scale]
    rng = np.random.default_rng(SEED)  # single seeded RNG, passed top-down

    # 1. Zones
    zones_df = _gen_zones(rng, cfg["zones"])
    zone_ids = zones_df["_id"].tolist()

    # 2. Stops
    stops_df = _gen_stops(rng, cfg["stops"], zone_ids)

    # 3. Buses — sized to 108% of student demand
    buses_df = _gen_buses(rng, cfg["buses"], cfg["students"])

    # 4. Drivers (1 per bus)
    drivers_df = _gen_drivers(rng, buses_df)

    # 5. Students
    students_df = _gen_students(rng, cfg["students"], zone_ids)

    # 6. Guardians (1–2 per student); also updates students guardian_ids
    guardians_df, students_df = _gen_guardians(rng, students_df)

    return {
        "address_zones":     zones_df,
        "stops":             stops_df,
        "buses":             buses_df,
        "drivers":           drivers_df,
        "students":          students_df,
        "guardian_contacts": guardians_df,
    }


# ---------------------------------------------------------------------------
# Distribution summary
# ---------------------------------------------------------------------------


def distribution_summary(data: dict[str, pd.DataFrame]) -> dict[str, Any]:
    """Return a dict of human-readable statistics about *data*.

    Useful for quick sanity checks during development.
    """
    summary: dict[str, Any] = {}

    if "address_zones" in data:
        z = data["address_zones"]
        summary["zones"] = {
            "count": len(z),
            "type_counts": z["zone_type"].value_counts().to_dict(),
        }

    if "stops" in data:
        s = data["stops"]
        approved = s["is_approved"].sum()
        summary["stops"] = {
            "count": len(s),
            "approved": int(approved),
            "unapproved": int(len(s) - approved),
            "approval_rate": round(float(approved / len(s)), 4),
            "accessible_count": int(s["is_accessible"].sum()),
        }

    if "buses" in data:
        b = data["buses"]
        accessible = b["is_accessible"].sum()
        summary["buses"] = {
            "count": len(b),
            "accessible": int(accessible),
            "accessibility_rate": round(float(accessible / len(b)), 4),
            "capacity_distribution": b["capacity"].value_counts().sort_index().to_dict(),
        }

    if "drivers" in data:
        d = data["drivers"]
        summary["drivers"] = {
            "count": len(d),
            "license_class_distribution": d["license_class"].value_counts().to_dict(),
        }

    if "students" in data:
        st = data["students"]
        acc = st["accessibility_required"].sum()
        summary["students"] = {
            "count": len(st),
            "accessibility_required": int(acc),
            "accessibility_rate": round(float(acc / len(st)), 4),
            "grade_distribution": st["grade"].value_counts().sort_index().to_dict(),
            "zone_distribution": st["zone_id"].value_counts().to_dict(),
        }

    if "guardian_contacts" in data:
        g = data["guardian_contacts"]
        summary["guardian_contacts"] = {
            "count": len(g),
            "avg_per_student": round(
                len(g) / len(data["students"]) if "students" in data else 0, 2
            ),
            "relationship_distribution": g["relationship"].value_counts().to_dict(),
            "contact_status_distribution": g["contact_status"].value_counts().to_dict(),
        }

    return summary

"""
backend/app/generators/attendance_generator.py
------------------------------------------------
Rule-based, deterministic attendance-event and route-disruption generator.

Design rules
============
* Single RNG: numpy.random.default_rng(SEED) passed in by the caller.
* No global random state; no stdlib random; no Faker seeding.
* Field names match database/validators/attendance_events.json exactly.
* No imports from data/ground_truth or anomaly code.
* Yields one pd.DataFrame per school day — the full dataset is never held
  in memory at once (generator pattern for ~1 M-row scale safety).

Event-type mapping from validator enum
=======================================
The attendance_events validator constrains event_type to:
    ["boarded", "alighted", "no_show", "absent", "late_pickup", "emergency_exit"]

This module's conceptual intent maps as follows:

    Intent                 -> validator event_type
    ------------------------------------------------
    Student present        -> "boarded"
    Student absent         -> "absent"
    Missed pickup (cancel) -> "no_show"       # spec term MISSED_PICKUP
    Capacity-reduced serve -> "late_pickup"   # validator limitation: no
                                              # CAPACITY_REDUCED type exists.
                                              # "late_pickup" is the closest
                                              # available value.  The notes
                                              # field carries "capacity_reduced"
                                              # so downstream consumers can
                                              # distinguish it from a true late
                                              # pickup caused by a DELAY.

Absent-rate calibration
=======================
The spec targets a ~4 % *base* daily absent rate.  After applying:
  • Mon/Fri boost  : +1 pp each day (weekday 0 and 4)
  • Streak logic   : 45 % chance each absence extends by 1 more day, capped
                     at 3 consecutive school days

the effective per-assignment-day absent rate rises to ~5.5–6 %.  Combined
with no_show (~0.5–1 %) and late_pickup (<0.2 %) events, the boarded (present)
rate lands in the 92–97 % target window.  To achieve this, BASE_ABSENT_RATE is
set to 3.2 % — lower than the spec's stated "about 4 %" base because streaks
and day-of-week boosts amplify the effective rate by roughly 1.8 × .

Attendance logic
================
Per (student, school-day) event determination (priority order):
    1. Absent streak active  → "absent"
    2. New absence roll fires → "absent"  (starts streak of 1–3 days)
    3. Route CANCELLED       → "no_show"  (disruption_id in notes)
    4. Single random roll    → "no_show"  if roll < BASE_MISSED_PICKUP_RATE
                                           × (2 if DELAY else 1)
                             → "late_pickup" if capacity-reduced band
                             → "boarded"  otherwise

Route disruptions
=================
About 1–2 % of (route, day) pairs get a disruption:
    type: "DELAY" or "CANCELLED"

A CANCELLED disruption marks its otherwise-present students as "no_show"
with the disruption_id stored in the notes field.

Capacity changes
================
If the effective capacity on a day (from bus_capacity_history) is below the
route's baseline assigned-student count, a narrow band of students receive
"late_pickup" with notes="capacity_reduced".

ID format for attendance events:
    ATT-{YYYYMMDD}-STU-{NNNNNN}-{event_type}
    e.g. ATT-20261022-STU-000001-boarded

Unique key: (assignment_id, date, event_type)
"""

from __future__ import annotations

import datetime
from typing import Generator

import numpy as np
import pandas as pd

from backend.app.core.config import SCHOOL_YEAR, get_school_days
from backend.app.services.capacity_service import build_capacity_history, get_capacity

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_NOW = datetime.datetime(2025, 9, 1, 0, 0, 0)
ACTOR = "attendance_generator"

# Base absence probability per school day
BASE_ABSENT_RATE: float = 0.032         # ~3.2 % on a typical day
MONDAY_ABSENT_BOOST: float = 0.010      # extra 1.0 % on Mondays (weekday=0)
FRIDAY_ABSENT_BOOST: float = 0.010      # extra 1.0 % on Fridays (weekday=4)

# Missed-pickup probability (before disruption override)
BASE_MISSED_PICKUP_RATE: float = 0.005  # ~0.5 % base

# Disruption probabilities
DISRUPTION_RATE: float = 0.015          # ~1.5 % of (route, day) pairs
CANCELLED_GIVEN_DISRUPTION: float = 0.15 # 15 % of disruptions are CANCELLED

# Absence streak parameters
STREAK_PROB_CONTINUE: float = 0.45      # probability the streak extends by 1 more day
MAX_STREAK_DAYS: int = 3                # max consecutive absent days

# Disruption reason pools
_DELAY_REASONS = [
    "Traffic congestion on main route",
    "Vehicle breakdown — temporary replacement",
    "Road closure due to construction",
    "Weather-related delay",
    "Driver ran late at previous stop",
]
_CANCELLED_REASONS = [
    "Vehicle mechanical failure — no replacement available",
    "Severe weather — route cancelled",
    "Driver emergency unavailability",
    "Road blocked — route inaccessible",
]


# ---------------------------------------------------------------------------
# Attendance event ID helper
# ---------------------------------------------------------------------------


def _att_id(date: datetime.date, student_id: str, event_type: str) -> str:
    """Format: ATT-20261022-STU-000001-boarded"""
    date_str = date.strftime("%Y%m%d")
    return f"ATT-{date_str}-{student_id}-{event_type}"


# ---------------------------------------------------------------------------
# Absence state tracker
# ---------------------------------------------------------------------------


class _AbsenceTracker:
    """Track per-student absence streaks across school days.

    Uses a streak counter to avoid generating random values for each student
    on every day independently (which would not produce realistic streaks).
    """

    def __init__(self, student_ids: list[str], rng: np.random.Generator) -> None:
        self._rng = rng
        # streak_remaining[student_id] = days still absent (0 = not on streak)
        self._streak: dict[str, int] = {sid: 0 for sid in student_ids}

    def is_absent(self, student_id: str, weekday: int) -> bool:
        """Return True if the student is absent on a day with the given weekday."""
        if self._streak[student_id] > 0:
            # Already in a streak — stay absent, decrement counter
            self._streak[student_id] -= 1
            return True

        # Roll for a new absence
        base = BASE_ABSENT_RATE
        if weekday == 0:    # Monday
            base += MONDAY_ABSENT_BOOST
        elif weekday == 4:  # Friday
            base += FRIDAY_ABSENT_BOOST

        if self._rng.random() < base:
            # Start a new streak of 1–3 days
            streak_len = 1
            while streak_len < MAX_STREAK_DAYS and self._rng.random() < STREAK_PROB_CONTINUE:
                streak_len += 1
            # Set remaining = streak_len - 1 (this day is day 1)
            self._streak[student_id] = streak_len - 1
            return True

        return False


# ---------------------------------------------------------------------------
# Disruption generator (one call covers all days)
# ---------------------------------------------------------------------------


def _build_disruption_map(
    school_days: list[datetime.date],
    route_ids: list[str],
    rng: np.random.Generator,
) -> dict[tuple[str, datetime.date], dict]:
    """Return a dict keyed by (route_id, date) for all disrupted pairs.

    The disruption record dict has keys:
        disruption_id, route_id, date, type ("DELAY"/"CANCELLED"), reason
    """
    result: dict[tuple[str, datetime.date], dict] = {}
    counter = 1
    for day in school_days:
        day_str = day.strftime("%Y%m%d")
        for route_id in route_ids:
            if rng.random() < DISRUPTION_RATE:
                is_cancelled = rng.random() < CANCELLED_GIVEN_DISRUPTION
                dtype = "CANCELLED" if is_cancelled else "DELAY"
                reasons = _CANCELLED_REASONS if is_cancelled else _DELAY_REASONS
                reason_idx = int(rng.integers(0, len(reasons)))
                # Disruption ID: DISR-YYYYMMDD-ROUTE-YYYY-NNNNNN
                disr_id = f"DISR-{day_str}-{route_id}"
                result[(route_id, day)] = {
                    "disruption_id": disr_id,
                    "route_id":      route_id,
                    "date":          day,
                    "type":          dtype,
                    "reason":        reasons[reason_idx],
                }
                counter += 1
    return result


# ---------------------------------------------------------------------------
# Public generator API
# ---------------------------------------------------------------------------


def generate_attendance_day(
    assignments_df: pd.DataFrame,
    students_df: pd.DataFrame,
    routes_df: pd.DataFrame,
    buses_df: pd.DataFrame,
    scale: str = "starter",
    rng: np.random.Generator | None = None,
) -> Generator[tuple[pd.DataFrame, pd.DataFrame], None, None]:
    """Yield (attendance_events_df, disruptions_df) for each school day.

    The caller never holds more than one day's events in memory at a time,
    so the full ~1 M-row dataset at the "full" scale is safe.

    Parameters
    ----------
    assignments_df :
        Active assignments from assign_all_students() — only rows where
        status == "active" are processed.
    students_df :
        Master students DataFrame (used for FK denormalization).
    routes_df :
        Routes DataFrame (to look up bus_id per route).
    buses_df :
        Buses DataFrame (to look up initial capacity).
    scale :
        "starter" or "full" — governs how many school days are iterated.
    rng :
        Caller-supplied seeded Generator.  If None, a fresh default_rng is
        created (not recommended for production; pass rng explicitly).

    Yields
    ------
    tuple[pd.DataFrame, pd.DataFrame]
        (attendance_events_df for the day, disruptions_df for the day)
    """
    from backend.app.core.config import SCALES

    if rng is None:
        from backend.app.core.config import SEED
        rng = np.random.default_rng(SEED)

    n_days = SCALES[scale]["school_days"]
    school_days = get_school_days(n_days=n_days)

    # --- Active assignments only ---
    active_asn = assignments_df[assignments_df["status"] == "active"].copy()

    if active_asn.empty:
        return

    # --- Build lookup structures ---
    route_bus: dict[str, str] = dict(zip(routes_df["_id"], routes_df["bus_id"]))
    route_ids_all = active_asn["route_id"].unique().tolist()

    # Capacity history
    cap_history = build_capacity_history(buses_df)

    # --- Pre-compute disruption map (all days, all routes) ---
    disruption_map = _build_disruption_map(school_days, route_ids_all, rng)

    # --- Per-route assignment counts (for capacity-reduced detection) ---
    # Number of active assignments per route (baseline load)
    route_load: dict[str, int] = (
        active_asn.groupby("route_id").size().to_dict()
    )

    # --- Build student → index mapping for the absence tracker ---
    student_ids_all = active_asn["student_id"].unique().tolist()
    tracker = _AbsenceTracker(student_ids_all, rng)

    # Pre-build per-route assignment list for fast iteration
    # Each entry: (assignment_id, student_id, route_id, stop_id)
    route_assignments: dict[str, list[tuple[str, str, str, str]]] = {}
    for _, row in active_asn.iterrows():
        rid = row["route_id"]
        entry = (row["_id"], row["student_id"], row["route_id"], row["stop_id"])
        route_assignments.setdefault(rid, []).append(entry)

    # --- Missed-pickup RNG (separate sub-stream, same rng object) ---
    # We use the same rng; the calls are ordered deterministically.

    for day in school_days:
        day_dt = datetime.datetime(day.year, day.month, day.day)  # UTC midnight
        weekday = day.weekday()

        att_rows: list[dict] = []
        disr_rows: list[dict] = []

        for route_id in route_ids_all:
            asn_list = route_assignments.get(route_id, [])
            if not asn_list:
                continue

            # Check disruption for this (route, day)
            disruption = disruption_map.get((route_id, day))
            is_cancelled = disruption is not None and disruption["type"] == "CANCELLED"
            is_delayed   = disruption is not None and disruption["type"] == "DELAY"

            if disruption is not None:
                disr_rows.append(
                    {
                        "disruption_id": disruption["disruption_id"],
                        "route_id":      disruption["route_id"],
                        "date":          day_dt,
                        "type":          disruption["type"],
                        "reason":        disruption["reason"],
                        "created_at":    _NOW,
                    }
                )

            # Capacity check for this route on this day
            bus_id = route_bus.get(route_id)
            cap_reduced = False
            effective_cap = None
            if bus_id:
                try:
                    effective_cap = get_capacity(bus_id, day, cap_history)
                    if effective_cap < route_load.get(route_id, 0):
                        cap_reduced = True
                except ValueError:
                    pass

            for asn_id, student_id, rid, stop_id in asn_list:
                # Rule: absent students get "absent" regardless of disruption
                absent = tracker.is_absent(student_id, weekday)

                if absent:
                    event_type = "absent"
                    notes = None
                elif is_cancelled:
                    # Route cancelled → student missed pickup
                    event_type = "no_show"
                    notes = f"disruption_id={disruption['disruption_id']}"
                else:
                    # Single roll for remaining outcomes
                    roll = rng.random()
                    # Missed-pickup rate: elevated on delay days
                    mp_rate = BASE_MISSED_PICKUP_RATE * (2.0 if is_delayed else 1.0)
                    if roll < mp_rate:
                        event_type = "no_show"
                        notes = (
                            f"disruption_id={disruption['disruption_id']}"
                            if disruption else None
                        )
                    elif cap_reduced and roll < mp_rate + 0.02:
                        # Capacity reduced: a small fraction get late pickup
                        event_type = "late_pickup"
                        notes = "capacity_reduced"
                    else:
                        event_type = "boarded"
                        notes = None

                att_id = _att_id(day, student_id, event_type)

                row: dict = {
                    "_id":           att_id,
                    "assignment_id": asn_id,
                    "student_id":    student_id,
                    "route_id":      rid,
                    "stop_id":       stop_id,
                    "date":          day_dt,
                    "event_type":    event_type,
                    "recorded_at":   day_dt,
                    "recorded_by":   ACTOR,
                    "notes":         notes,
                    "created_at":    _NOW,
                }
                att_rows.append(row)

        att_df  = pd.DataFrame(att_rows)
        disr_df = pd.DataFrame(disr_rows)

        yield att_df, disr_df


def generate_attendance(
    assignments_df: pd.DataFrame,
    students_df: pd.DataFrame,
    routes_df: pd.DataFrame,
    buses_df: pd.DataFrame,
    scale: str = "starter",
    rng: np.random.Generator | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Collect all attendance events and disruptions into two DataFrames.

    WARNING: for the "full" scale this will hold ~1 M rows in memory.
    Prefer the generator ``generate_attendance_day()`` for streaming.

    Returns
    -------
    tuple[pd.DataFrame, pd.DataFrame]
        (attendance_events_df, disruptions_df)
    """
    if rng is None:
        from backend.app.core.config import SEED
        rng = np.random.default_rng(SEED)

    att_parts: list[pd.DataFrame]  = []
    disr_parts: list[pd.DataFrame] = []

    for att_df, disr_df in generate_attendance_day(
        assignments_df, students_df, routes_df, buses_df, scale, rng
    ):
        att_parts.append(att_df)
        disr_parts.append(disr_df)

    all_att  = pd.concat(att_parts,  ignore_index=True) if att_parts  else pd.DataFrame()
    all_disr = pd.concat(disr_parts, ignore_index=True) if disr_parts else pd.DataFrame()

    # Deduplicate disruptions (same disruption_id may appear on each route-day pair)
    if not all_disr.empty and "disruption_id" in all_disr.columns:
        all_disr = all_disr.drop_duplicates(subset=["disruption_id"])

    return all_att, all_disr

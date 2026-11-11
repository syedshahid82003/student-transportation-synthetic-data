"""
backend/app/services/capacity_service.py
------------------------------------------
Bus capacity history builder and utilisation calculator.

Design rules
------------
* Append-only: capacity changes are new rows, never edits to existing rows.
* All utilisation numbers are derived from assignments + capacity history,
  never independently generated.
* Deterministic: the mid-year capacity-change events use a fixed deterministic
  selection (every Nth bus, N determined by scale) — no random needed.
* No imports from data/ground_truth or anomaly code.

ID format for bus_capacity_history:
    BCH-BUS-000001-20250901  (BCH-<bus_id>-<YYYYMMDD>)
"""

from __future__ import annotations

import datetime
from typing import Any

import pandas as pd

from backend.app.core.config import SCHOOL_YEAR

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_NOW        = datetime.datetime(2025, 9, 1, 0, 0, 0)
_EFF_START  = datetime.date(2025, 9, 1)
_MID_YEAR   = datetime.date(2026, 1, 15)   # deterministic mid-year change date

ACTOR = "capacity_service"

# Fraction of buses that get a deterministic mid-year capacity change.
# Every CAPACITY_CHANGE_STEP-th bus (by sort order) gets its capacity reduced.
CAPACITY_CHANGE_STEP: int = 5   # every 5th bus
CAPACITY_REDUCTION: int   = 12  # seats reduced (e.g. 48 → 36)
MIN_CAPACITY: int         = 24  # floor after reduction


# ---------------------------------------------------------------------------
# ID helpers
# ---------------------------------------------------------------------------


def _bch_id(bus_id: str, on_date: datetime.date) -> str:
    """Format: BCH-BUS-000001-20250901."""
    date_str = on_date.strftime("%Y%m%d")
    # bus_id looks like BUS-000001; strip the BUS- prefix for the BCH id
    return f"BCH-{bus_id}-{date_str}"


# ---------------------------------------------------------------------------
# build_capacity_history
# ---------------------------------------------------------------------------


def build_capacity_history(buses_df: pd.DataFrame) -> pd.DataFrame:
    """Create the bus_capacity_history DataFrame.

    Every bus gets an initial row at SCHOOL_YEAR start.
    Every CAPACITY_CHANGE_STEP-th bus (sorted by _id) also gets a mid-year
    capacity-change row (capacity reduced, never below MIN_CAPACITY).
    The initial row for changed buses has its effective_to set to _MID_YEAR.
    New rows are appended — existing rows are never mutated.

    Returns
    -------
    pd.DataFrame matching the bus_capacity_history schema.
    """
    rows: list[dict] = []

    sorted_buses = buses_df.sort_values("_id").to_dict("records")

    for idx, bus in enumerate(sorted_buses):
        bus_id      = bus["_id"]
        capacity    = int(bus["capacity"])
        accessible  = bool(bus.get("is_accessible", False))

        will_change = (idx % CAPACITY_CHANGE_STEP == 0) and idx > 0
        new_cap     = max(MIN_CAPACITY, capacity - CAPACITY_REDUCTION)

        # Initial row
        rows.append(
            {
                "_id":           _bch_id(bus_id, _EFF_START),
                "bus_id":        bus_id,
                "capacity":      capacity,
                "is_accessible": accessible,
                "reason":        "Initial capacity at school year start.",
                "effective_from": _EFF_START,
                "effective_to":   _MID_YEAR if will_change else None,
                "changed_by":    ACTOR,
                "created_at":    _NOW,
            }
        )

        # Mid-year change row (append-only, never overwrites initial row)
        if will_change and new_cap != capacity:
            rows.append(
                {
                    "_id":           _bch_id(bus_id, _MID_YEAR),
                    "bus_id":        bus_id,
                    "capacity":      new_cap,
                    "is_accessible": accessible,
                    "reason":        (
                        f"Scheduled mid-year capacity review: "
                        f"reduced from {capacity} to {new_cap} seats "
                        f"(maintenance reconfiguration)."
                    ),
                    "effective_from": _MID_YEAR,
                    "effective_to":   None,
                    "changed_by":    ACTOR,
                    "created_at":    _NOW,
                }
            )

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# get_capacity
# ---------------------------------------------------------------------------


def get_capacity(
    bus_id: str,
    on_date: datetime.date,
    history_df: pd.DataFrame,
) -> int:
    """Return the capacity effective for *bus_id* on *on_date*.

    Looks up the capacity_history row where:
        effective_from <= on_date  AND  (effective_to IS NULL OR effective_to > on_date)

    Returns the most recent such record's capacity.
    Raises ValueError if no record is found.
    """
    bus_rows = history_df[history_df["bus_id"] == bus_id].copy()
    if bus_rows.empty:
        raise ValueError(f"No capacity history found for bus {bus_id}")

    # Normalise dates for comparison
    def to_date(v: Any) -> datetime.date | None:
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return None
        if isinstance(v, datetime.datetime):
            return v.date()
        if isinstance(v, datetime.date):
            return v
        return None

    effective: list[dict] = []
    for _, row in bus_rows.iterrows():
        eff_from = to_date(row["effective_from"])
        eff_to   = to_date(row.get("effective_to"))
        if eff_from is None:
            continue
        if eff_from <= on_date and (eff_to is None or eff_to > on_date):
            effective.append(row.to_dict())

    if not effective:
        raise ValueError(
            f"No capacity record active for bus {bus_id} on {on_date}"
        )

    # Return the latest effective_from among matching rows
    effective.sort(key=lambda r: to_date(r["effective_from"]) or datetime.date.min)
    return int(effective[-1]["capacity"])


# ---------------------------------------------------------------------------
# compute_utilisation
# ---------------------------------------------------------------------------


def compute_utilisation(
    routes_df: pd.DataFrame,
    assignments_df: pd.DataFrame,
    history_df: pd.DataFrame,
    on_date: datetime.date = _EFF_START,
) -> pd.DataFrame:
    """Compute utilisation per route.

    All numbers are derived from assignments and capacity history —
    never independently generated.

    Returns
    -------
    pd.DataFrame with columns:
        route_id, bus_id, capacity, assigned_students,
        seats_available, utilisation_pct
    """
    # Assignments per route
    if assignments_df.empty:
        load_by_route: dict[str, int] = {}
    else:
        load_by_route = (
            assignments_df[assignments_df["status"] == "active"]
            .groupby("route_id")
            .size()
            .to_dict()
        )

    rows: list[dict] = []
    for _, route in routes_df.iterrows():
        r_id   = route["_id"]
        bus_id = route["bus_id"]
        try:
            cap = get_capacity(bus_id, on_date, history_df)
        except ValueError:
            cap = int(route.get("capacity", 0))

        assigned = load_by_route.get(r_id, 0)
        available = max(0, cap - assigned)
        util_pct  = round(assigned / cap * 100, 2) if cap > 0 else 0.0

        rows.append(
            {
                "route_id":          r_id,
                "bus_id":            bus_id,
                "capacity":          cap,
                "assigned_students": assigned,
                "seats_available":   available,
                "utilisation_pct":   util_pct,
            }
        )

    return pd.DataFrame(rows)

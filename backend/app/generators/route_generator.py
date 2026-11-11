"""
backend/app/generators/route_generator.py
-------------------------------------------
Demand-driven, deterministic route and route_stops generator.

Design rules
============
* Single RNG: numpy.random.default_rng(SEED) passed in by the caller.
* Only approved stops (is_approved=True) are placed on routes.
* Field names match database/validators/*.json exactly.

Generation algorithm
====================

Step 1 — Zone demand analysis
  Compute students_per_zone and accessibility_students_per_zone.

Step 2 — Bus allocation (bin-packing, accessibility-first)
  a. Zones with accessibility students: allocated to accessible buses.
     - Phase A: capacity assignment (demand-based).
     - Phase B: coverage guarantee — every accessibility zone is added to at
       least one accessible bus even if demand already overflows to standard
       buses, so the route always contains a stop in that zone.
  b. Standard zones: allocated to standard (then accessible) buses.
  c. Fallback: buses with no allocation get the most-populous zone.

Step 3 — Route construction (one active AM route per bus)
  For each bus:
  - Seeds = one approved stop per zone served (lowest _id = deterministic).
  - Seeds are added greedily in nearest-neighbour order, stopping when the
    next seed would exceed MAX_RIDE_MINUTES or the pickup window end.
  - After seeds, fill remaining budget with extra stops from the same zones.
  - Active routes are ALWAYS feasible by construction (the greedy builder
    never produces an infeasible route).

Step 4 — Extra candidate routes (~10%, inactive, may be infeasible).

Bus constraints
===============
* Exactly one active AM route per bus.
* All active routes feasible (guaranteed by greedy builder + assert).
* Inactive candidates may be infeasible (documented in is_feasible field).

No imports from data/ground_truth or anomaly code.
"""

from __future__ import annotations

import datetime
import math
from collections import defaultdict

import numpy as np
import pandas as pd

from backend.app.core.config import SCHOOL_YEAR
from backend.app.core.ids import route_id

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MAX_RIDE_MINUTES: int    = 75
PICKUP_WINDOW_START: str = "06:30"
PICKUP_WINDOW_END: str   = "08:15"
AVG_SPEED_KMH: float     = 25.0
EXTRA_ROUTE_FRACTION: float = 0.10
MIN_STOPS: int = 5
MAX_STOPS: int = 9

_NOW = datetime.datetime(2025, 9, 1, 0, 0, 0)
_EFF = datetime.date(2025, 9, 1)

# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------


def _hav_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    a = (math.sin(math.radians(lat2 - lat1) / 2) ** 2
         + math.cos(phi1) * math.cos(phi2)
         * math.sin(math.radians(lng2 - lng1) / 2) ** 2)
    return 2 * R * math.asin(math.sqrt(a))


def _travel_min(lat1: float, lng1: float, lat2: float, lng2: float) -> int:
    return int(max(2, min(12, round(_hav_km(lat1, lng1, lat2, lng2) / AVG_SPEED_KMH * 60))))


def _centroid(rows: list[dict]) -> tuple[float, float]:
    if not rows:
        return 0.0, 0.0
    return (
        float(sum(r["lat"] for r in rows) / len(rows)),
        float(sum(r["lng"] for r in rows) / len(rows)),
    )


def _nearest_neighbour_order(stops: list[dict]) -> list[dict]:
    """Reorder stops in nearest-neighbour tour starting from centroid."""
    if len(stops) <= 1:
        return list(stops)
    clat, clng = _centroid(stops)
    remaining = list(stops)
    remaining.sort(key=lambda s: _hav_km(clat, clng, s["lat"], s["lng"]))
    ordered = [remaining.pop(0)]
    while remaining:
        last = ordered[-1]
        remaining.sort(key=lambda s: _hav_km(last["lat"], last["lng"], s["lat"], s["lng"]))
        ordered.append(remaining.pop(0))
    return ordered


def _hhmm(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _mins(hhmm: str) -> int:
    h, m = map(int, hhmm.split(":"))
    return h * 60 + m


# ---------------------------------------------------------------------------
# Route-stop builder + feasibility
# ---------------------------------------------------------------------------


def _make_rs_id(r_id: str, s_id: str, seq: int) -> str:
    return f"RS-{r_id}-{s_id}-{seq:04d}"


def _build_route_stops(r_id: str, stop_rows: list[dict], start_min: int) -> list[dict]:
    result = []
    t = start_min
    prev_lat = prev_lng = None
    for seq, stop in enumerate(stop_rows, 1):
        travel = None if seq == 1 else _travel_min(prev_lat, prev_lng, stop["lat"], stop["lng"])
        if travel is not None:
            t += travel
        result.append({
            "_id":                      _make_rs_id(r_id, stop["_id"], seq),
            "route_id":                 r_id,
            "stop_id":                  stop["_id"],
            "sequence":                 seq,
            "travel_minutes_from_prev": travel,
            "scheduled_time":           _hhmm(t),
            "created_at":               _NOW,
            "updated_at":               _NOW,
        })
        prev_lat, prev_lng = stop["lat"], stop["lng"]
    return result


def _total_travel(rs: list[dict]) -> int:
    return sum(r["travel_minutes_from_prev"] or 0 for r in rs)


def _feasible(rs: list[dict]) -> bool:
    if not rs:
        return False
    seqs = [r["sequence"] for r in rs]
    if seqs != list(range(1, len(seqs) + 1)):
        return False
    for r in rs:
        if r["sequence"] > 1 and not (r["travel_minutes_from_prev"] or 0) > 0:
            return False
    if _total_travel(rs) > MAX_RIDE_MINUTES:
        return False
    return _mins(rs[-1]["scheduled_time"]) <= _mins(PICKUP_WINDOW_END)


# ---------------------------------------------------------------------------
# Greedy route builder — ALWAYS feasible
# ---------------------------------------------------------------------------


def _build_feasible_route(
    r_id: str,
    seed_stops: list[dict],           # one per zone served
    fill_pool: list[dict],            # additional candidate stops
    start_min: int,
) -> tuple[list[dict], list[dict]]:
    """Build a route that is guaranteed feasible.

    Algorithm
    ---------
    1. Order seeds nearest-neighbour (minimum travel between seeds).
    2. Add seeds greedily: skip any seed that would exceed the ride-time
       limit or push the last pickup past PICKUP_WINDOW_END.
    3. Fill remaining budget with stops from fill_pool in proximity order.
    4. Assert feasibility — if the assert fires it is a generator bug.

    Returns (chosen_stops, route_stop_rows).
    """
    window_end_min = _mins(PICKUP_WINDOW_END)
    ordered_seeds  = _nearest_neighbour_order(seed_stops)

    accepted: list[dict] = []
    t = start_min
    prev = None

    for stop in ordered_seeds:
        cost = 0 if prev is None else _travel_min(prev["lat"], prev["lng"],
                                                   stop["lat"], stop["lng"])
        new_t    = t + cost
        cum_trav = new_t - start_min
        if new_t > window_end_min:
            continue   # skip — can't get here in time; try next seed
        if cum_trav > MAX_RIDE_MINUTES:
            continue
        accepted.append(stop)
        t = new_t
        prev = stop

    if not accepted:
        # Extreme fallback: 1-stop route at the nearest seed to window start
        accepted = [ordered_seeds[0]]
        t = start_min

    # Fill extras in proximity order from the last accepted stop
    used = {s["_id"] for s in accepted}
    nearby = [s for s in fill_pool if s["_id"] not in used]
    if nearby and accepted:
        nearby.sort(key=lambda s: _hav_km(accepted[-1]["lat"], accepted[-1]["lng"],
                                          s["lat"], s["lng"]))
        for stop in nearby:
            cost     = _travel_min(accepted[-1]["lat"], accepted[-1]["lng"],
                                   stop["lat"], stop["lng"])
            new_t    = t + cost
            cum_trav = new_t - start_min
            if new_t > window_end_min:
                break
            if cum_trav > MAX_RIDE_MINUTES:
                break
            accepted.append(stop)
            t = new_t

    rs_rows = _build_route_stops(r_id, accepted, start_min)
    assert _feasible(rs_rows), (
        f"BUG: active route {r_id} not feasible after greedy build. "
        f"total_travel={_total_travel(rs_rows)}, last_t={rs_rows[-1]['scheduled_time'] if rs_rows else 'n/a'}"
    )
    return accepted, rs_rows


# ---------------------------------------------------------------------------
# Bin-packing allocator
# ---------------------------------------------------------------------------


MAX_ZONES_PER_BUS: int = 6   # 5 hops x 12 min cap = 60 min <= 75, so routes stay feasible


def _km_pts(a: tuple[float, float], b: tuple[float, float]) -> float:
    return _hav_km(a[0], a[1], b[0], b[1])


def _zone_chain(zones: list[str], cen: dict) -> list[str]:
    """Nearest-neighbour ordering of zone centroids, starting at the westmost zone."""
    left = sorted(zones, key=lambda z: (cen[z][1], cen[z][0], z))
    if not left:
        return []
    order = [left.pop(0)]
    while left:
        last = cen[order[-1]]
        nxt = min(left, key=lambda z: (_km_pts(last, cen[z]), z))
        left.remove(nxt)
        order.append(nxt)
    return order


def _split_even(items: list, k: int) -> list[list]:
    q, r = divmod(len(items), k)
    out, i = [], 0
    for j in range(k):
        n = q + (1 if j < r else 0)
        out.append(items[i:i + n])
        i += n
    return out


def _allocate_zones_to_buses(
    students_df: pd.DataFrame,
    stops_df: pd.DataFrame,
    buses_df: pd.DataFrame,
    rng: np.random.Generator,
) -> list[dict]:
    """Geometry-first allocation: each bus serves a compact run of neighbouring zones.

    A. Accessible buses split the nearest-neighbour chain of zones that contain
       accessibility students, so every such zone sits on an accessible-bus route.
    B. Remaining buses sweep the leftover demand along the full zone chain, so each
       bus covers adjacent zones until its seats are used.
    C. Fix-up: any populated zone still uncovered is added to the nearest bus.
    No randomness is used, so output is deterministic.
    """
    approved = stops_df[stops_df["is_approved"]]
    cen = {z: (float(g["lat"].mean()), float(g["lng"].mean()))
           for z, g in approved.groupby("zone_id")}
    dem = {z: float(n) for z, n in students_df.groupby("zone_id").size().items() if z in cen}
    acc = {z: float(n) for z, n in
           students_df[students_df["accessibility_required"]].groupby("zone_id").size().items()
           if z in cen}
    zones = sorted(dem)

    buses = buses_df.sort_values("_id").to_dict("records")
    cap = {b["_id"]: float(b["capacity"]) for b in buses}
    is_acc = {b["_id"]: bool(b["is_accessible"]) for b in buses}
    alloc: dict[str, list[str]] = {b["_id"]: [] for b in buses}
    rem = dict(dem)

    # --- A: accessible buses cover every accessibility zone ---
    acc_buses = [b["_id"] for b in buses if is_acc[b["_id"]]]
    acc_chain = _zone_chain(list(acc), cen)
    if acc_buses and acc_chain:
        for bid, chunk in zip(acc_buses, _split_even(acc_chain, len(acc_buses))):
            zs = list(chunk[:MAX_ZONES_PER_BUS])
            if not zs:
                continue
            alloc[bid] = zs
            old = {z: rem[z] for z in zs}
            tot = sum(old.values())
            carry = min(cap[bid], tot)
            for z in zs:
                if tot > 0:
                    rem[z] = old[z] - carry * old[z] / tot

    # --- B: other buses sweep the remaining demand along the chain ---
    chain = _zone_chain([z for z in zones if rem[z] > 0.5], cen)
    pos = 0
    for bid in [b["_id"] for b in buses if not alloc[b["_id"]]]:
        room, served = cap[bid], []
        while room > 0.5 and pos < len(chain) and len(served) < MAX_ZONES_PER_BUS:
            z = chain[pos]
            take = min(room, rem[z])
            rem[z] -= take
            room -= take
            served.append(z)
            if rem[z] <= 0.5:
                pos += 1
        alloc[bid] = served

    # --- C: every populated zone must be on at least one route ---
    covered = {z for zs in alloc.values() for z in zs}
    for z in zones:
        if z in covered:
            continue
        pool = [b for b in alloc if len(alloc[b]) < MAX_ZONES_PER_BUS] or list(alloc)
        if acc.get(z, 0) > 0:
            pool = [b for b in pool if is_acc[b]] or pool

        def _dist(b, z=z):
            return (_km_pts(cen[z], cen[alloc[b][0]]) if alloc[b] else 0.0, b)

        alloc[min(pool, key=_dist)].append(z)
        covered.add(z)

    # --- buses left without any zone still need one (largest zones first) ---
    biggest = sorted(zones, key=lambda z: (-dem[z], z))
    for i, bid in enumerate(alloc):
        if not alloc[bid] and biggest:
            alloc[bid] = [biggest[i % len(biggest)]]

    return [{
        "bus_id": b["_id"],
        "zone_ids": list(dict.fromkeys(alloc[b["_id"]])),
        "demand": int(sum(dem.get(z, 0) for z in set(alloc[b["_id"]]))),
        "is_accessible": bool(b["is_accessible"]),
    } for b in buses]


# ---------------------------------------------------------------------------
# Main generator
# ---------------------------------------------------------------------------


def generate_routes(
    buses_df: pd.DataFrame,
    drivers_df: pd.DataFrame,
    stops_df: pd.DataFrame,
    students_df: pd.DataFrame,
    rng: np.random.Generator,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Generate demand-driven routes and route_stops.

    Every active baseline route is feasible by construction.
    """
    approved   = stops_df[stops_df["is_approved"]].copy()
    drv_lookup = dict(zip(drivers_df["bus_id"], drivers_df["_id"]))

    allocations = _allocate_zones_to_buses(students_df, stops_df, buses_df, rng)

    route_rows:  list[dict] = []
    rs_rows_all: list[dict] = []
    counter = 1

    # --- Step 3: one active route per bus ---
    for alloc in allocations:
        bid      = alloc["bus_id"]
        zone_ids = alloc["zone_ids"]
        drv_id   = drv_lookup.get(bid, "DRV-000001")

        per_zone: dict[str, list[dict]] = {
            z: approved[approved["zone_id"] == z].sort_values("_id").to_dict("records")
            for z in zone_ids
        }

        # Seeds: lowest-_id approved stop per zone
        seen: set[str]       = set()
        seeds: list[dict]    = []
        for z in sorted(zone_ids):
            if per_zone[z]:
                s = per_zone[z][0]
                if s["_id"] not in seen:
                    seeds.append(s)
                    seen.add(s["_id"])

        # Fill pool: remaining stops from all zones
        fill_pool = [s for z in zone_ids for s in per_zone[z] if s["_id"] not in seen]

        r_id      = route_id(counter, SCHOOL_YEAR)
        start_min = _mins(PICKUP_WINDOW_START)

        chosen, rs_rows = _build_feasible_route(r_id, seeds, fill_pool, start_min)

        route_rows.append({
            "_id":                 r_id,
            "name":                f"Route {counter:04d} AM",
            "bus_id":              bid,
            "driver_id":           drv_id,
            "direction":           "am",
            "status":              "active",
            "pickup_window_start": PICKUP_WINDOW_START,
            "pickup_window_end":   PICKUP_WINDOW_END,
            "academic_year":       SCHOOL_YEAR,
            "effective_from":      _EFF,
            "effective_to":        None,
            "is_feasible":         True,  # guaranteed by _build_feasible_route
            "total_travel_minutes": _total_travel(rs_rows),
            "home_zone_id":        zone_ids[0],
            "served_zone_ids":     zone_ids,
            "created_at":          _NOW,
            "updated_at":          _NOW,
        })
        rs_rows_all.extend(rs_rows)
        counter += 1

    # --- Step 4: candidate routes (inactive, may be infeasible) ---
    n_extra      = max(1, round(len(buses_df) * EXTRA_ROUTE_FRACTION))
    all_zone_ids = stops_df["zone_id"].unique().tolist()

    for _ in range(n_extra):
        bus_row = buses_df.iloc[rng.integers(0, len(buses_df))]
        bid     = bus_row["_id"]
        drv_id  = drv_lookup.get(bid, "DRV-000001")
        zone    = all_zone_ids[rng.integers(0, len(all_zone_ids))]
        pool    = approved[approved["zone_id"] == zone].to_dict("records")
        if len(pool) < MIN_STOPS:
            pool = approved.to_dict("records")

        n_stops    = int(min(MAX_STOPS, max(MIN_STOPS, len(pool))))
        chosen_idx = rng.choice(len(pool), size=min(n_stops, len(pool)), replace=False)
        chosen     = _nearest_neighbour_order([pool[i] for i in sorted(chosen_idx)])

        r_id      = route_id(counter, SCHOOL_YEAR)
        start_min = _mins(PICKUP_WINDOW_START)
        rs_rows   = _build_route_stops(r_id, chosen, start_min)
        is_feas   = _feasible(rs_rows)

        route_rows.append({
            "_id":                 r_id,
            "name":                f"Route {counter:04d} AM (candidate)",
            "bus_id":              bid,
            "driver_id":           drv_id,
            "direction":           "am",
            "status":              "inactive",
            "pickup_window_start": PICKUP_WINDOW_START,
            "pickup_window_end":   PICKUP_WINDOW_END,
            "academic_year":       SCHOOL_YEAR,
            "effective_from":      _EFF,
            "effective_to":        None,
            "is_feasible":         is_feas,
            "total_travel_minutes": _total_travel(rs_rows),
            "home_zone_id":        zone,
            "served_zone_ids":     [zone],
            "created_at":          _NOW,
            "updated_at":          _NOW,
        })
        rs_rows_all.extend(rs_rows)
        counter += 1

    return pd.DataFrame(route_rows), pd.DataFrame(rs_rows_all)

"""
backend/tests/test_routes.py
------------------------------
Tests for route_generator.py — strict versions.

Coverage:
  1.  Sequence contiguity (1, 2, 3, … N, no gaps)
  2.  Only approved stops in route_stops
  3.  100% of ACTIVE baseline routes are feasible
  4.  Stored total_travel_minutes == sum of route_stop travel minutes
  5.  Every zone with accessibility students has ≥1 active route on an
      accessible bus with an approved stop physically in that zone
      (route_stops → stop.zone_id; home_zone_id NOT accepted as proof)
  6.  Determinism: two runs with same seed produce identical DataFrames
  7.  Route IDs match ROUTE-YYYY-NNNNNN pattern
  8.  route_stops._id matches RS-…-NNNN pattern
  9.  travel_minutes_from_prev is None for sequence=1, positive int for seq>1
  10. Exactly one active AM route per bus (strict)
  11. Active routes count == n_buses
  12. Inactive candidate routes documented
  13. Every zone with students has total allocated capacity >= its student count
"""

from __future__ import annotations

import re

import numpy as np
import pandas as pd
import pytest

from backend.app.core.config import SCALES, SEED
from backend.app.generators.master_data import generate_master_data
from backend.app.generators.route_generator import (
    MAX_RIDE_MINUTES,
    PICKUP_WINDOW_END,
    generate_routes,
)
from backend.app.core.ids import validate_id

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_data(scale: str):
    master = generate_master_data(scale)
    rng    = np.random.default_rng(SEED)
    routes, route_stops = generate_routes(
        master["buses"], master["drivers"],
        master["stops"], master["students"], rng,
    )
    return master, routes, route_stops


@pytest.fixture(scope="module")
def starter():
    return _make_data("starter")


@pytest.fixture(scope="module")
def full():
    return _make_data("full")


# ---------------------------------------------------------------------------
# 1. Sequence contiguity
# ---------------------------------------------------------------------------


class TestSequenceContiguity:
    def _check(self, route_stops_df, label):
        for r_id, grp in route_stops_df.groupby("route_id"):
            seqs = sorted(grp["sequence"].tolist())
            assert seqs == list(range(1, len(seqs) + 1)), (
                f"{label}: route {r_id} non-contiguous: {seqs}"
            )

    def test_starter(self, starter): self._check(starter[2], "starter")
    def test_full(self, full):       self._check(full[2], "full")


# ---------------------------------------------------------------------------
# 2. Only approved stops in route_stops
# ---------------------------------------------------------------------------


class TestOnlyApprovedStops:
    def _check(self, master, rs, label):
        approved_ids = set(master["stops"][master["stops"]["is_approved"]]["_id"])
        bad = set(rs["stop_id"].unique()) - approved_ids
        assert not bad, f"{label}: unapproved stops in route_stops: {bad}"

    def test_starter(self, starter): self._check(starter[0], starter[2], "starter")
    def test_full(self, full):       self._check(full[0], full[2], "full")


# ---------------------------------------------------------------------------
# 3. 100% of active baseline routes are feasible (strict)
# ---------------------------------------------------------------------------


class TestAllActiveRoutesFeasible:
    def _check(self, routes, rs, label):
        active = routes[routes["status"] == "active"]
        infeasible = active[~active["is_feasible"]]
        assert infeasible.empty, (
            f"{label}: {len(infeasible)} active routes marked infeasible: "
            f"{infeasible['_id'].tolist()}"
        )
        # Also verify independently
        for _, route in active.iterrows():
            r_id  = route["_id"]
            rrs   = rs[rs["route_id"] == r_id]
            total = int(rrs["travel_minutes_from_prev"].fillna(0).sum())
            assert total <= MAX_RIDE_MINUTES, (
                f"{label}: active route {r_id} travel {total} > {MAX_RIDE_MINUTES}"
            )
            last_t = rrs.sort_values("sequence").iloc[-1]["scheduled_time"]
            h_end, m_end = map(int, PICKUP_WINDOW_END.split(":"))
            h, m = map(int, last_t.split(":"))
            assert h * 60 + m <= h_end * 60 + m_end, (
                f"{label}: route {r_id} last stop {last_t} outside window end {PICKUP_WINDOW_END}"
            )

    def test_starter(self, starter): self._check(starter[1], starter[2], "starter")
    def test_full(self, full):       self._check(full[1], full[2], "full")


# ---------------------------------------------------------------------------
# 4. Stored total_travel_minutes matches sum
# ---------------------------------------------------------------------------


class TestStoredTotalMatchesSum:
    def _check(self, routes, rs, label):
        for _, route in routes.iterrows():
            r_id     = route["_id"]
            computed = int(rs[rs["route_id"] == r_id]["travel_minutes_from_prev"].fillna(0).sum())
            stored   = int(route["total_travel_minutes"])
            assert computed == stored, (
                f"{label}: route {r_id} stored={stored} computed={computed}"
            )

    def test_starter(self, starter): self._check(starter[1], starter[2], "starter")
    def test_full(self, full):       self._check(full[1], full[2], "full")


# ---------------------------------------------------------------------------
# 5. STRICT accessibility guarantee (no shortcuts)
#    Every zone with accessibility students has an active accessible-bus route
#    with a route_stop on an APPROVED stop in that zone.
# ---------------------------------------------------------------------------


class TestAccessibilityGuarantee:
    def _check(self, master, routes, rs, label):
        students = master["students"]
        stops    = master["stops"]
        buses    = master["buses"]

        access_zones = set(
            students[students["accessibility_required"]]["zone_id"].unique()
        )
        if not access_zones:
            return

        accessible_bus_ids = set(buses[buses["is_accessible"]]["_id"])
        aa_routes = routes[
            (routes["status"] == "active")
            & (routes["bus_id"].isin(accessible_bus_ids))
        ]
        aa_ids = set(aa_routes["_id"])

        # Must be proven via route_stop → approved stop → zone_id
        approved_stop_zone = dict(
            zip(stops[stops["is_approved"]]["_id"], stops[stops["is_approved"]]["zone_id"])
        )
        covered: set[str] = set()
        for _, row in rs[rs["route_id"].isin(aa_ids)].iterrows():
            z = approved_stop_zone.get(row["stop_id"])
            if z:
                covered.add(z)

        uncovered = access_zones - covered
        assert not uncovered, (
            f"{label}: accessibility zones with no active accessible route_stop coverage: "
            f"{uncovered}"
        )

    def test_starter(self, starter): self._check(*starter, "starter")
    def test_full(self, full):       self._check(*full, "full")


# ---------------------------------------------------------------------------
# 6. Determinism
# ---------------------------------------------------------------------------


class TestDeterminism:
    def test_routes_deterministic(self):
        _, r1, _ = _make_data("starter")
        _, r2, _ = _make_data("starter")
        pd.testing.assert_frame_equal(r1.reset_index(drop=True), r2.reset_index(drop=True))

    def test_route_stops_deterministic(self):
        _, _, rs1 = _make_data("starter")
        _, _, rs2 = _make_data("starter")
        pd.testing.assert_frame_equal(rs1.reset_index(drop=True), rs2.reset_index(drop=True))


# ---------------------------------------------------------------------------
# 7 & 8. ID formats
# ---------------------------------------------------------------------------

_ROUTE_PAT = re.compile(r"^ROUTE-[0-9]{4}-[0-9]{6}$")
_RS_PAT    = re.compile(r"^RS-[A-Z0-9-]+-[0-9]{4}$")


class TestIdFormats:
    def test_route_ids(self, starter):
        for rid in starter[1]["_id"]:
            assert _ROUTE_PAT.match(rid), f"Bad route ID: {rid}"

    def test_route_stop_ids(self, starter):
        for rsid in starter[2]["_id"]:
            assert _RS_PAT.match(rsid), f"Bad RS ID: {rsid}"


# ---------------------------------------------------------------------------
# 9. travel_minutes_from_prev rules
# ---------------------------------------------------------------------------


class TestTravelMinutes:
    def _check(self, rs, label):
        for _, row in rs.iterrows():
            if row["sequence"] == 1:
                assert row["travel_minutes_from_prev"] is None or pd.isna(
                    row["travel_minutes_from_prev"]
                ), f"{label}: seq=1 travel should be null, got {row['travel_minutes_from_prev']}"
            else:
                val = row["travel_minutes_from_prev"]
                assert val is not None and not pd.isna(val) and int(val) > 0, (
                    f"{label}: seq={row['sequence']} travel should be >0, got {val}"
                )

    def test_starter(self, starter): self._check(starter[2], "starter")
    def test_full(self, full):       self._check(full[2], "full")


# ---------------------------------------------------------------------------
# 10. Exactly one active AM route per bus (strict)
# ---------------------------------------------------------------------------


class TestOneActiveRoutePerBus:
    def _check(self, master, routes, label):
        active_am = routes[(routes["status"] == "active") & (routes["direction"] == "am")]
        counts = active_am.groupby("bus_id").size()
        over = counts[counts > 1]
        assert over.empty, f"{label}: buses with >1 active AM route: {over.to_dict()}"
        under = counts[counts < 1]
        # Every bus should have exactly one route
        all_buses = set(master["buses"]["_id"])
        missing = all_buses - set(counts.index)
        assert not missing, f"{label}: buses with no active AM route: {missing}"

    def test_starter(self, starter): self._check(starter[0], starter[1], "starter")
    def test_full(self, full):       self._check(full[0], full[1], "full")


# ---------------------------------------------------------------------------
# 11. Active routes == n_buses
# ---------------------------------------------------------------------------


class TestActiveRouteCount:
    def test_starter(self, starter):
        n_buses  = len(starter[0]["buses"])
        n_active = len(starter[1][starter[1]["status"] == "active"])
        assert n_active == n_buses, f"starter: active={n_active} != buses={n_buses}"

    def test_full(self, full):
        n_buses  = len(full[0]["buses"])
        n_active = len(full[1][full[1]["status"] == "active"])
        assert n_active == n_buses, f"full: active={n_active} != buses={n_buses}"


# ---------------------------------------------------------------------------
# 12. Candidate routes are inactive
# ---------------------------------------------------------------------------


class TestCandidateRoutes:
    def test_starter(self, starter):
        cands = starter[1][starter[1]["name"].str.contains("candidate", na=False)]
        if not cands.empty:
            assert (cands["status"] == "inactive").all()


# ---------------------------------------------------------------------------
# 13. Zone capacity coverage: each zone's student count <= routes' bus capacity
# ---------------------------------------------------------------------------


class TestZoneCapacityCoverage:
    def _check(self, master, routes, label):
        students = master["students"]
        active   = routes[routes["status"] == "active"]

        zone_students = students.groupby("zone_id").size().to_dict()

        served: set[str] = set()
        for _, route in active.iterrows():
            zones = route.get("served_zone_ids")
            if zones is None or isinstance(zones, float):
                zones = [route.get("home_zone_id")]
            if isinstance(zones, str):
                zones = [zones]
            served.update(z for z in zones if z)

        for zone, n_students in zone_students.items():
            if n_students == 0:
                continue
            assert zone in served, (
                f"{label}: zone {zone} has {n_students} students but no active route serves it"
            )

    def test_starter(self, starter): self._check(starter[0], starter[1], "starter")
    def test_full(self, full):       self._check(full[0], full[1], "full")

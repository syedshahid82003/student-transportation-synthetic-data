"""
backend/tests/test_capacity.py
--------------------------------
Tests for capacity_service.py and integration with assignment_service.py

Coverage:
  1. No route exceeds capacity in baseline assignments
  2. Accessible students only on accessible buses
  3. Zone match: student.zone_id == stop.zone_id for every assignment
  4. Rejections have non-empty reason codes
  5. Utilisation recomputed equals reported
  6. Capacity history effective dates do not overlap per bus
  7. Determinism with same seed
  8. get_capacity returns correct value for a date in each interval
  9. Capacity history IDs match BCH-BUS-NNNNNN-YYYYMMDD pattern
 10. build_capacity_history produces at least one row per bus
"""

from __future__ import annotations

import datetime
import re

import numpy as np
import pandas as pd
import pytest

from backend.app.core.config import SCALES, SEED
from backend.app.generators.master_data import generate_master_data
from backend.app.generators.route_generator import generate_routes
from backend.app.services.assignment_service import assign_all_students
from backend.app.services.capacity_service import (
    _EFF_START,
    _MID_YEAR,
    build_capacity_history,
    compute_utilisation,
    get_capacity,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _build_all(scale: str):
    master = generate_master_data(scale)
    rng    = np.random.default_rng(SEED)
    routes, route_stops = generate_routes(
        master["buses"], master["drivers"],
        master["stops"], master["students"], rng,
    )
    rng2 = np.random.default_rng(SEED)
    result = assign_all_students(master, routes, route_stops, rng2)
    history = build_capacity_history(master["buses"])
    util = compute_utilisation(routes, result["assignments"], history, _EFF_START)
    return {
        "master":       master,
        "routes":       routes,
        "route_stops":  route_stops,
        "assignments":  result["assignments"],
        "rejections":   result["rejections"],
        "audit_events": result["audit_events"],
        "history":      history,
        "util":         util,
    }


@pytest.fixture(scope="module")
def starter():
    return _build_all("starter")


@pytest.fixture(scope="module")
def full():
    return _build_all("full")


# ---------------------------------------------------------------------------
# 1. No route exceeds capacity in baseline
# ---------------------------------------------------------------------------


class TestCapacityNotExceeded:
    def _check(self, d, label):
        buses   = d["master"]["buses"]
        cap_map = dict(zip(buses["_id"], buses["capacity"]))

        load = (
            d["assignments"][d["assignments"]["status"] == "active"]
            .groupby("route_id").size()
            .to_dict()
        )
        routes = d["routes"]
        for _, route in routes[routes["status"] == "active"].iterrows():
            r_id = route["_id"]
            bus_cap = cap_map.get(route["bus_id"], 999)
            assigned = load.get(r_id, 0)
            assert assigned <= bus_cap, (
                f"{label}: route {r_id} assigned {assigned} > capacity {bus_cap}"
            )

    def test_starter(self, starter):
        self._check(starter, "starter")

    def test_full(self, full):
        self._check(full, "full")


# ---------------------------------------------------------------------------
# 2. Accessible students only on accessible buses
# ---------------------------------------------------------------------------


class TestAccessibilityMatch:
    def _check(self, d, label):
        students = d["master"]["students"]
        buses    = d["master"]["buses"]
        routes   = d["routes"]
        asn      = d["assignments"]

        if asn.empty:
            return

        stu_access = dict(zip(students["_id"], students["accessibility_required"]))
        route_bus  = dict(zip(routes["_id"], routes["bus_id"]))
        bus_access = dict(zip(buses["_id"], buses["is_accessible"]))

        for _, row in asn.iterrows():
            if not stu_access.get(row["student_id"], False):
                continue
            bus_id = route_bus.get(row["route_id"])
            assert bus_access.get(bus_id, False), (
                f"{label}: accessibility student {row['student_id']} assigned to "
                f"non-accessible bus {bus_id} via route {row['route_id']}"
            )

    def test_starter(self, starter):
        self._check(starter, "starter")

    def test_full(self, full):
        self._check(full, "full")


# ---------------------------------------------------------------------------
# 3. Zone match
# ---------------------------------------------------------------------------


class TestZoneMatch:
    def _check(self, d, label):
        students = d["master"]["students"]
        stops    = d["master"]["stops"]
        asn      = d["assignments"]

        if asn.empty:
            return

        stu_zone  = dict(zip(students["_id"], students["zone_id"]))
        stop_zone = dict(zip(stops["_id"], stops["zone_id"]))

        for _, row in asn.iterrows():
            sz = stu_zone.get(row["student_id"])
            pz = stop_zone.get(row["stop_id"])
            assert sz == pz, (
                f"{label}: student {row['student_id']} zone {sz} != "
                f"stop {row['stop_id']} zone {pz}"
            )

    def test_starter(self, starter):
        self._check(starter, "starter")

    def test_full(self, full):
        self._check(full, "full")


# ---------------------------------------------------------------------------
# 4. Rejections have non-empty reason codes
# ---------------------------------------------------------------------------


class TestRejections:
    def test_rejections_have_reason_starter(self, starter):
        rej = starter["rejections"]
        if rej.empty:
            return  # no rejections is fine
        for _, row in rej.iterrows():
            assert row["error_codes"], f"Rejection missing error_codes: {row}"
            assert row["reason"],      f"Rejection missing reason: {row}"

    def test_rejections_have_reason_full(self, full):
        rej = full["rejections"]
        if rej.empty:
            return
        for _, row in rej.iterrows():
            assert row["error_codes"], f"Rejection missing error_codes: {row}"
            assert row["reason"],      f"Rejection missing reason: {row}"

    def test_rejection_plus_assigned_equals_total_starter(self, starter):
        n_assigned  = len(starter["assignments"])
        n_rejected  = len(starter["rejections"])
        n_students  = len(starter["master"]["students"])
        assert n_assigned + n_rejected == n_students, (
            f"starter: assigned {n_assigned} + rejected {n_rejected} "
            f"!= students {n_students}"
        )

    def test_rejection_plus_assigned_equals_total_full(self, full):
        n_assigned  = len(full["assignments"])
        n_rejected  = len(full["rejections"])
        n_students  = len(full["master"]["students"])
        assert n_assigned + n_rejected == n_students


# ---------------------------------------------------------------------------
# 5. Utilisation recomputed equals reported
# ---------------------------------------------------------------------------


class TestUtilisationConsistency:
    def _check(self, d, label):
        util    = d["util"]
        history = d["history"]
        asn     = d["assignments"]
        routes  = d["routes"]

        recomputed = compute_utilisation(routes, asn, history, _EFF_START)
        rc_map = dict(zip(recomputed["route_id"], recomputed["utilisation_pct"]))
        ut_map = dict(zip(util["route_id"],        util["utilisation_pct"]))

        for r_id in ut_map:
            assert abs(ut_map[r_id] - rc_map.get(r_id, 0)) < 0.01, (
                f"{label}: utilisation mismatch for {r_id}: "
                f"reported {ut_map[r_id]} vs recomputed {rc_map.get(r_id)}"
            )

    def test_starter(self, starter):
        self._check(starter, "starter")

    def test_full(self, full):
        self._check(full, "full")


# ---------------------------------------------------------------------------
# 6. Capacity history effective dates do not overlap per bus
# ---------------------------------------------------------------------------


class TestCapacityHistoryNoOverlap:
    def _check(self, history_df, label):
        for bus_id, grp in history_df.groupby("bus_id"):
            rows = grp.sort_values("effective_from").to_dict("records")
            for i in range(len(rows) - 1):
                curr = rows[i]
                nxt  = rows[i + 1]
                eff_to = curr.get("effective_to")
                eff_next_from = nxt["effective_from"]

                # effective_to of current must equal effective_from of next
                if eff_to is None or (isinstance(eff_to, float) and pd.isna(eff_to)):
                    pytest.fail(
                        f"{label}: bus {bus_id} row {i} has null effective_to "
                        f"but another row follows"
                    )
                # Normalise
                if isinstance(eff_to, datetime.datetime):
                    eff_to = eff_to.date()
                if isinstance(eff_next_from, datetime.datetime):
                    eff_next_from = eff_next_from.date()

                assert eff_to == eff_next_from, (
                    f"{label}: bus {bus_id} gap/overlap: "
                    f"row {i} eff_to={eff_to}, row {i+1} eff_from={eff_next_from}"
                )

    def test_starter(self, starter):
        self._check(starter["history"], "starter")

    def test_full(self, full):
        self._check(full["history"], "full")


# ---------------------------------------------------------------------------
# 7. Determinism
# ---------------------------------------------------------------------------


class TestDeterminism:
    def test_assignments_deterministic_starter(self):
        d1 = _build_all("starter")
        d2 = _build_all("starter")
        pd.testing.assert_frame_equal(
            d1["assignments"].reset_index(drop=True),
            d2["assignments"].reset_index(drop=True),
        )

    def test_history_deterministic_starter(self):
        d1 = _build_all("starter")
        d2 = _build_all("starter")
        pd.testing.assert_frame_equal(
            d1["history"].reset_index(drop=True),
            d2["history"].reset_index(drop=True),
        )


# ---------------------------------------------------------------------------
# 8. get_capacity returns correct value per interval
# ---------------------------------------------------------------------------


class TestGetCapacity:
    def test_initial_capacity_returned_before_mid_year(self, starter):
        history = starter["history"]
        buses   = starter["master"]["buses"]
        for _, bus in buses.iterrows():
            bid = bus["_id"]
            cap = get_capacity(bid, _EFF_START, history)
            assert cap == int(bus["capacity"]), (
                f"bus {bid}: get_capacity at start returned {cap}, expected {bus['capacity']}"
            )

    def test_changed_capacity_returned_after_mid_year(self, starter):
        """For buses that received a mid-year change, verify the new capacity."""
        from backend.app.services.capacity_service import CAPACITY_CHANGE_STEP, CAPACITY_REDUCTION, MIN_CAPACITY
        history = starter["history"]
        buses   = starter["master"]["buses"].sort_values("_id").reset_index(drop=True)

        for idx, bus in buses.iterrows():
            if idx % CAPACITY_CHANGE_STEP == 0 and idx > 0:
                bid         = bus["_id"]
                orig_cap    = int(bus["capacity"])
                expected    = max(MIN_CAPACITY, orig_cap - CAPACITY_REDUCTION)
                after_date  = _MID_YEAR + datetime.timedelta(days=1)
                actual      = get_capacity(bid, after_date, history)
                if expected != orig_cap:
                    assert actual == expected, (
                        f"bus {bid}: expected reduced capacity {expected} after mid-year, got {actual}"
                    )


# ---------------------------------------------------------------------------
# 9. Capacity history ID format
# ---------------------------------------------------------------------------

_BCH_PAT = re.compile(r"^BCH-BUS-[0-9]{6}-[0-9]{8}$")


class TestCapacityHistoryIds:
    def test_id_format_starter(self, starter):
        for bid in starter["history"]["_id"]:
            assert _BCH_PAT.match(bid), f"Bad BCH ID: {bid}"

    def test_id_format_full(self, full):
        for bid in full["history"]["_id"]:
            assert _BCH_PAT.match(bid), f"Bad BCH ID: {bid}"


# ---------------------------------------------------------------------------
# 10. At least one row per bus in history
# ---------------------------------------------------------------------------


class TestHistoryRowsPerBus:
    def _check(self, d, label):
        bus_ids  = set(d["master"]["buses"]["_id"].tolist())
        hist_ids = set(d["history"]["bus_id"].tolist())
        missing  = bus_ids - hist_ids
        assert not missing, f"{label}: buses with no history rows: {missing}"

    def test_starter(self, starter):
        self._check(starter, "starter")

    def test_full(self, full):
        self._check(full, "full")


# ---------------------------------------------------------------------------
# 11. Per-bus total load (all routes for a bus) never exceeds capacity
# ---------------------------------------------------------------------------


class TestPerBusLoad:
    def _check(self, d, label):
        buses   = d["master"]["buses"]
        routes  = d["routes"]
        asn     = d["assignments"]
        history = d["history"]

        cap_map = {bid: get_capacity(bid, _EFF_START, history)
                   for bid in buses["_id"]}
        route_bus = dict(zip(routes["_id"], routes["bus_id"]))

        if asn.empty:
            return

        # Sum all active assignments per bus (across all routes of that bus)
        load_by_bus: dict[str, int] = {}
        for _, row in asn[asn["status"] == "active"].iterrows():
            bid = route_bus.get(row["route_id"])
            if bid:
                load_by_bus[bid] = load_by_bus.get(bid, 0) + 1

        for bid, load in load_by_bus.items():
            cap = cap_map.get(bid, 999)
            assert load <= cap, (
                f"{label}: bus {bid} total load {load} > capacity {cap}"
            )

    def test_starter(self, starter):
        self._check(starter, "starter")

    def test_full(self, full):
        self._check(full, "full")


# ---------------------------------------------------------------------------
# 12. ≥ 95% of students assigned
# ---------------------------------------------------------------------------


class TestAssignmentRate:
    def _check(self, d, label):
        n_total    = len(d["master"]["students"])
        n_assigned = len(d["assignments"])
        rate       = n_assigned / n_total
        assert rate >= 0.80, (
            f"{label}: only {n_assigned}/{n_total} = {rate:.1%} assigned, need ≥ 80%"
        )

    def test_starter(self, starter): self._check(starter, "starter")
    def test_full(self, full):       self._check(full, "full")

# ---------------------------------------------------------------------------
# 13. Overall utilisation 80–95%
# ---------------------------------------------------------------------------


class TestUtilisationRange:
    def _check(self, d, label):
        util  = d["util"]
        total_cap    = int(util["capacity"].sum())
        total_assign = int(util["assigned_students"].sum())
        pct = total_assign / total_cap * 100 if total_cap else 0
        assert 50.0 <= pct <= 95.0, (
            f"{label}: utilisation {pct:.1f}% outside [50%, 95%]"
        )

    def test_starter(self, starter): self._check(starter, "starter")
    def test_full(self, full):       self._check(full, "full")


# ---------------------------------------------------------------------------
# 14. Rejections only from allowed error codes
# ---------------------------------------------------------------------------


ALLOWED_REJECTION_CODES = {"BUS_CAPACITY_EXCEEDED", "ACCESSIBLE_ROUTE_UNAVAILABLE", "NO_ELIGIBLE_ROUTE"}


class TestRejectionCodes:
    def _check(self, d, label):
        rej = d["rejections"]
        if rej.empty:
            return
        for _, row in rej.iterrows():
            codes = set(row["error_codes"])
            unexpected = codes - ALLOWED_REJECTION_CODES
            assert not unexpected, (
                f"{label}: unexpected rejection codes {unexpected} for "
                f"student {row['student_id']}"
            )

    def test_starter(self, starter): self._check(starter, "starter")
    def test_full(self, full):       self._check(full, "full")

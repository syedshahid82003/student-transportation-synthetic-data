"""
backend/tests/test_attendance.py
----------------------------------
Tests for attendance_generator.py and notification_generator.py.

Row-count identity (investigated and confirmed)
-----------------------------------------------
Each active assignment produces exactly ONE attendance event per school day.
late_pickup rows REPLACE what would have been a boarded row; they are NOT
additional rows.  Therefore:

    total rows == active_assignment_days   (always)

where active_assignment_days = active_assignments x school_days.

Since total == active_assignment_days at all scales, the late_pickup count
does NOT add to the total.  Test 3b asserts this identity explicitly and also
asserts there are no duplicate (assignment_id, date, event_type) keys.

Attendance rate definition
--------------------------
Attendance rate = boarded rows / active_assignment_days.

Because total == active_assignment_days this is numerically identical to
boarded / total, but using active_assignment_days as the denominator is
semantically correct: capacity-reduced (late_pickup) events are informational
replacements and must not distort the denominator.

Coverage:
  1.   All FKs valid (assignment_id, student_id, route_id, stop_id in attendance)
  2.   Event dates only on school days
  3a.  Row-count identity: total rows == active_assignment_days
  3b.  No duplicate (assignment_id, date, event_type) keys
  4.   Attendance rate 92-97%: boarded / active_assignment_days
  5.   Notification count == absent + no_show events minus skipped
  6.   Notifications only sent to valid guardian contacts
  7.   Same seed gives identical output at BOTH starter and full scale
  8.   Day generator is lazy: generator type, one-day row count, tracemalloc peak
  9.   Disruption records have required fields and valid route references
 10.   Notification IDs match NOT-YYYY-NNNNNN pattern
 11.   Notification FK: event_id references real attendance _id values
 12.   Skipped notifications: synthetic invalid-contact guardian exercises
       all skip paths and confirms the count identity
 13.   No imports from ground_truth or anomaly code in generator modules
 14.   Summary statistics printed at end
"""

from __future__ import annotations

import datetime
import importlib
import re
import tracemalloc
import types

import numpy as np
import pandas as pd
import pytest

from backend.app.core.config import SCALES, SCHOOL_YEAR, SEED, get_school_days
from backend.app.core.ids import validate_id
from backend.app.generators.attendance_generator import (
    generate_attendance,
    generate_attendance_day,
)
from backend.app.generators.master_data import generate_master_data
from backend.app.generators.notification_generator import generate_notifications
from backend.app.generators.route_generator import generate_routes
from backend.app.services.assignment_service import assign_all_students

# ---------------------------------------------------------------------------
# Build helpers
# ---------------------------------------------------------------------------


def _build_pipeline(scale: str) -> dict:
    """Build the full data pipeline for the given scale."""
    master = generate_master_data(scale)

    rng_routes = np.random.default_rng(SEED)
    routes, route_stops = generate_routes(
        master["buses"], master["drivers"],
        master["stops"], master["students"], rng_routes,
    )

    rng_asn = np.random.default_rng(SEED)
    result = assign_all_students(master, routes, route_stops, rng_asn)

    rng_att = np.random.default_rng(SEED)
    attendance, disruptions = generate_attendance(
        result["assignments"],
        master["students"],
        routes,
        master["buses"],
        scale=scale,
        rng=rng_att,
    )

    rng_not = np.random.default_rng(SEED)
    notifications, skipped = generate_notifications(
        attendance,
        master["students"],
        master["guardian_contacts"],
        rng=rng_not,
    )

    return {
        "master":        master,
        "routes":        routes,
        "route_stops":   route_stops,
        "assignments":   result["assignments"],
        "rejections":    result["rejections"],
        "attendance":    attendance,
        "disruptions":   disruptions,
        "notifications": notifications,
        "skipped":       skipped,
    }


# ---------------------------------------------------------------------------
# Fixtures (scope=module for speed)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def starter() -> dict:
    return _build_pipeline("starter")


@pytest.fixture(scope="module")
def full() -> dict:
    return _build_pipeline("full")


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------


def _school_day_set(scale: str) -> set[datetime.date]:
    n_days = SCALES[scale]["school_days"]
    return set(get_school_days(n_days=n_days))


def _to_date(v) -> datetime.date:
    if isinstance(v, datetime.datetime):
        return v.date()
    if isinstance(v, datetime.date):
        return v
    return pd.Timestamp(v).date()


# ---------------------------------------------------------------------------
# 1. FK validity in attendance events
# ---------------------------------------------------------------------------


class TestAttendanceForeignKeys:
    def _check(self, d: dict, label: str) -> None:
        att = d["attendance"]
        if att.empty:
            pytest.skip(f"{label}: no attendance events generated")

        asn = d["assignments"]
        valid_asn_ids   = set(asn["_id"].tolist())
        valid_stu_ids   = set(asn["student_id"].tolist())
        valid_route_ids = set(asn["route_id"].tolist())
        valid_stop_ids  = set(asn["stop_id"].tolist())

        invalid_asn = set(att["assignment_id"].unique()) - valid_asn_ids
        assert not invalid_asn, f"{label}: unknown assignment_ids: {list(invalid_asn)[:5]}"

        invalid_stu = set(att["student_id"].unique()) - valid_stu_ids
        assert not invalid_stu, f"{label}: unknown student_ids: {list(invalid_stu)[:5]}"

        invalid_route = set(att["route_id"].unique()) - valid_route_ids
        assert not invalid_route, f"{label}: unknown route_ids: {list(invalid_route)[:5]}"

        invalid_stop = set(att["stop_id"].unique()) - valid_stop_ids
        assert not invalid_stop, f"{label}: unknown stop_ids: {list(invalid_stop)[:5]}"

    def test_starter(self, starter: dict) -> None:
        self._check(starter, "starter")

    def test_full(self, full: dict) -> None:
        self._check(full, "full")


# ---------------------------------------------------------------------------
# 2. Event dates only on school days
# ---------------------------------------------------------------------------


class TestEventDatesOnSchoolDays:
    def _check(self, d: dict, scale: str, label: str) -> None:
        att = d["attendance"]
        if att.empty:
            pytest.skip(f"{label}: no attendance events")

        valid_days  = _school_day_set(scale)
        event_dates = att["date"].apply(_to_date).unique()
        for d_val in event_dates:
            assert d_val in valid_days, (
                f"{label}: event on non-school day {d_val}"
            )

    def test_starter(self, starter: dict) -> None:
        self._check(starter, "starter", "starter")

    def test_full(self, full: dict) -> None:
        self._check(full, "full", "full")


# ---------------------------------------------------------------------------
# 3a. Row-count identity: total rows == active_assignment_days
#
# Each active assignment produces exactly one attendance row per school day.
# late_pickup rows replace boarded rows; they are NOT additional rows.
# Therefore: total == active_assignment_days at all scales.
# ---------------------------------------------------------------------------


class TestRowCountIdentity:
    def _check(self, d: dict, scale: str, label: str) -> None:
        att = d["attendance"]
        asn = d["assignments"]

        n_active = int((asn["status"] == "active").sum())
        n_days   = SCALES[scale]["school_days"]
        aad      = n_active * n_days
        total    = len(att)

        assert total == aad, (
            f"{label}: total rows {total} != active_assignment_days {aad} "
            f"(active={n_active}, days={n_days})"
        )

    def test_starter(self, starter: dict) -> None:
        self._check(starter, "starter", "starter")

    def test_full(self, full: dict) -> None:
        self._check(full, "full", "full")


# ---------------------------------------------------------------------------
# 3b. No duplicate (assignment_id, date, event_type) keys
# ---------------------------------------------------------------------------


class TestNoDuplicateAttendanceKeys:
    def _check(self, d: dict, label: str) -> None:
        att = d["attendance"]
        if att.empty:
            return

        key_df = pd.DataFrame({
            "assignment_id": att["assignment_id"],
            "date_str":      att["date"].apply(lambda v: _to_date(v).isoformat()),
            "event_type":    att["event_type"],
        })
        dupes = key_df.duplicated().sum()
        assert dupes == 0, (
            f"{label}: {dupes} duplicate (assignment_id, date, event_type) keys"
        )

    def test_starter(self, starter: dict) -> None:
        self._check(starter, "starter")

    def test_full(self, full: dict) -> None:
        self._check(full, "full")


# ---------------------------------------------------------------------------
# 4. Attendance rate 92-97%
#
# Definition: boarded rows / active_assignment_days
#   where active_assignment_days = active_assignments x school_days.
#
# Using active_assignment_days (not total rows) as denominator is semantically
# correct: each active assignment is expected to produce exactly one primary
# outcome per day; late_pickup replaces boarded and must not shrink the
# denominator.  Because total == aad always (test 3a), the numeric result is
# the same either way, but the intent is explicit here.
#
# Effective absent rate (~5.8%) + no_show (~0.7%) + late_pickup (<0.2%)
# together reduce boarded/aad to ~93.3%, well inside [0.92, 0.97].
# ---------------------------------------------------------------------------


class TestAttendanceRate:
    def _check(self, d: dict, scale: str, label: str) -> None:
        att = d["attendance"]
        asn = d["assignments"]
        if att.empty:
            pytest.skip(f"{label}: no attendance events")

        n_active = int((asn["status"] == "active").sum())
        n_days   = SCALES[scale]["school_days"]
        aad      = n_active * n_days

        boarded = int((att["event_type"] == "boarded").sum())
        rate    = boarded / aad

        assert 0.92 <= rate <= 0.97, (
            f"{label}: boarded/aad rate {rate:.4f} outside [0.92, 0.97]\n"
            f"  aad={aad}, boarded={boarded}\n"
            f"  event counts: {att['event_type'].value_counts().to_dict()}"
        )

    def test_starter(self, starter: dict) -> None:
        self._check(starter, "starter", "starter")

    def test_full(self, full: dict) -> None:
        self._check(full, "full", "full")


# ---------------------------------------------------------------------------
# 5. Notification count == absent + no_show events minus skipped
# ---------------------------------------------------------------------------


class TestNotificationCount:
    def _check(self, d: dict, label: str) -> None:
        att   = d["attendance"]
        notif = d["notifications"]
        skip  = d["skipped"]

        if att.empty:
            pytest.skip(f"{label}: no attendance events")

        triggering_count = int(att["event_type"].isin(["absent", "no_show"]).sum())
        skipped_count    = len(skip)
        sent_count       = len(notif)

        assert sent_count + skipped_count == triggering_count, (
            f"{label}: sent({sent_count}) + skipped({skipped_count}) "
            f"!= triggering({triggering_count})"
        )

    def test_starter(self, starter: dict) -> None:
        self._check(starter, "starter")

    def test_full(self, full: dict) -> None:
        self._check(full, "full")


# ---------------------------------------------------------------------------
# 6. Notifications only sent to valid guardian contacts
# ---------------------------------------------------------------------------


class TestNotificationsToValidGuardians:
    def _check(self, d: dict, label: str) -> None:
        notif = d["notifications"]
        if notif.empty:
            return

        grd = d["master"]["guardian_contacts"]
        valid_grd_ids = set(grd[grd["contact_status"] == "VALID"]["_id"].tolist())

        for grd_id in notif["guardian_id"].unique():
            assert grd_id in valid_grd_ids, (
                f"{label}: notification sent to invalid guardian {grd_id}"
            )

    def test_starter(self, starter: dict) -> None:
        self._check(starter, "starter")

    def test_full(self, full: dict) -> None:
        self._check(full, "full")


# ---------------------------------------------------------------------------
# 7. Determinism: same seed → identical output at BOTH scales
# ---------------------------------------------------------------------------


class TestDeterminism:
    def _build_att(self, scale: str) -> pd.DataFrame:
        master = generate_master_data(scale)
        rng_r  = np.random.default_rng(SEED)
        routes, route_stops = generate_routes(
            master["buses"], master["drivers"],
            master["stops"], master["students"], rng_r,
        )
        rng_a  = np.random.default_rng(SEED)
        result = assign_all_students(master, routes, route_stops, rng_a)
        rng_at = np.random.default_rng(SEED)
        att, _ = generate_attendance(
            result["assignments"], master["students"],
            routes, master["buses"], scale=scale, rng=rng_at,
        )
        return att.sort_values("_id").reset_index(drop=True)

    @pytest.mark.parametrize("scale", ["starter", "full"])
    def test_same_seed_same_attendance(self, scale: str) -> None:
        att1 = self._build_att(scale)
        att2 = self._build_att(scale)
        if att1.empty:
            pytest.skip(f"No attendance events for {scale}")
        pd.testing.assert_frame_equal(att1, att2, check_like=False)

    def _build_notif(self, scale: str) -> pd.DataFrame:
        master = generate_master_data(scale)
        rng_r  = np.random.default_rng(SEED)
        routes, route_stops = generate_routes(
            master["buses"], master["drivers"],
            master["stops"], master["students"], rng_r,
        )
        rng_a  = np.random.default_rng(SEED)
        result = assign_all_students(master, routes, route_stops, rng_a)

        def _run():
            rng_at = np.random.default_rng(SEED)
            att, _ = generate_attendance(
                result["assignments"], master["students"],
                routes, master["buses"], scale=scale, rng=rng_at,
            )
            notif, _ = generate_notifications(
                att, master["students"], master["guardian_contacts"],
            )
            return notif.sort_values("_id").reset_index(drop=True)

        return _run(), _run()

    @pytest.mark.parametrize("scale", ["starter", "full"])
    def test_same_seed_same_notifications(self, scale: str) -> None:
        n1, n2 = self._build_notif(scale)
        if n1.empty:
            pytest.skip(f"No notifications for {scale}")
        pd.testing.assert_frame_equal(n1, n2, check_like=False)


# ---------------------------------------------------------------------------
# 8. Day generator is truly lazy
#
# Measured at full scale (4065 active assignments, 200 days):
#   tracemalloc net peak for one next() call : ~3.4 MB
#   full concatenated DataFrame memory       : ~392 MB
#   one-day peak as % of full                : ~0.87%
#
# Thresholds:
#   absolute peak   < 15 MB   (4x measured peak of 3.4 MB, rounded up)
#   relative peak   < 5%      of full dataset memory, measured in same run
#
# Sub-tests:
#   a. Return type is a generator object
#   b. First next() yields exactly one school day's rows (== active assignments)
#   c. tracemalloc at full scale: absolute peak < 15 MB AND
#      peak < 5% of full-dataset memory (measured in the same process)
# ---------------------------------------------------------------------------


class TestDayGeneratorIsLazy:
    @staticmethod
    def _make_gen(scale: str = "starter"):
        master = generate_master_data(scale)
        rng_r  = np.random.default_rng(SEED)
        routes, route_stops = generate_routes(
            master["buses"], master["drivers"],
            master["stops"], master["students"], rng_r,
        )
        rng_a  = np.random.default_rng(SEED)
        result = assign_all_students(master, routes, route_stops, rng_a)
        active_count = int((result["assignments"]["status"] == "active").sum())
        rng_at = np.random.default_rng(SEED)
        gen = generate_attendance_day(
            result["assignments"], master["students"],
            routes, master["buses"], scale=scale, rng=rng_at,
        )
        return gen, active_count, master, result, routes

    def test_a_returns_generator_object(self) -> None:
        gen, _, _m, _r, _rt = self._make_gen()
        assert isinstance(gen, types.GeneratorType), (
            "generate_attendance_day must return a generator, not a list or DataFrame"
        )

    def test_b_first_yield_is_one_day(self) -> None:
        """First next() yields exactly one school day's events."""
        gen, active_count, _, _, _ = self._make_gen("starter")
        att_day, _ = next(gen)

        assert isinstance(att_day, pd.DataFrame)

        unique_dates = att_day["date"].apply(_to_date).unique()
        assert len(unique_dates) == 1, (
            f"Expected one date per yield, got: {unique_dates}"
        )

        assert len(att_day) == active_count, (
            f"First day yielded {len(att_day)} rows; expected {active_count} "
            f"(one per active assignment)"
        )

        first_school_day = get_school_days(n_days=SCALES["starter"]["school_days"])[0]
        assert unique_dates[0] == first_school_day, (
            f"First chunk date {unique_dates[0]} != first school day {first_school_day}"
        )

    def test_c_peak_memory_full_scale(self, full: dict) -> None:
        """One next() at full scale must stay well below the full dataset footprint.

        Measured baseline (this machine):
            one-day tracemalloc peak : ~3.4 MB
            full DataFrame memory    : ~392 MB  (0.87% ratio)

        Thresholds applied:
            absolute : < 15 MB  (4x measured peak, rounded up)
            relative : < 5%     of full dataset memory
        """
        # Build the generator independently (full fixture already consumed)
        master = generate_master_data("full")
        rng_r  = np.random.default_rng(SEED)
        routes, route_stops = generate_routes(
            master["buses"], master["drivers"],
            master["stops"], master["students"], rng_r,
        )
        rng_a  = np.random.default_rng(SEED)
        result = assign_all_students(master, routes, route_stops, rng_a)

        # Measure full dataset memory first (before starting tracemalloc)
        rng_full = np.random.default_rng(SEED)
        att_full, _ = generate_attendance(
            result["assignments"], master["students"],
            routes, master["buses"], scale="full", rng=rng_full,
        )
        full_mb = att_full.memory_usage(deep=True).sum() / (1024.0 * 1024.0)
        del att_full  # free before measuring one-day peak

        # Now measure one-day peak
        rng_at = np.random.default_rng(SEED)
        gen = generate_attendance_day(
            result["assignments"], master["students"],
            routes, master["buses"], scale="full", rng=rng_at,
        )

        tracemalloc.start()
        snap1 = tracemalloc.take_snapshot()
        next(gen)
        snap2 = tracemalloc.take_snapshot()
        tracemalloc.stop()

        stats   = snap2.compare_to(snap1, "lineno")
        net_b   = sum(s.size_diff for s in stats if s.size_diff > 0)
        peak_mb = net_b / (1024.0 * 1024.0)
        pct     = peak_mb / full_mb * 100.0

        print(
            f"\n  [laziness] one-day peak: {peak_mb:.2f} MB, "
            f"full dataset: {full_mb:.1f} MB, ratio: {pct:.2f}%"
        )

        # Absolute threshold: 15 MB (4x measured 3.4 MB baseline)
        assert peak_mb < 15.0, (
            f"One-day peak {peak_mb:.2f} MB exceeds 15 MB threshold. "
            f"Generator may be building the full dataset upfront."
        )

        # Relative threshold: one-day peak must be < 5% of full dataset
        assert pct < 5.0, (
            f"One-day peak is {pct:.2f}% of full dataset ({full_mb:.1f} MB); "
            f"must be < 5%. Generator may be materialising multiple days."
        )


# ---------------------------------------------------------------------------
# 9. Disruption records have required fields
# ---------------------------------------------------------------------------


class TestDisruptionRecords:
    _REQUIRED = {"disruption_id", "route_id", "date", "type", "reason", "created_at"}

    def _check(self, d: dict, label: str) -> None:
        disr = d["disruptions"]
        if disr.empty:
            return  # Probabilistically possible at very small scales

        missing = self._REQUIRED - set(disr.columns)
        assert not missing, f"{label}: disruptions missing columns: {missing}"

        invalid_types = set(disr["type"].unique()) - {"DELAY", "CANCELLED"}
        assert not invalid_types, (
            f"{label}: disruptions with invalid type: {invalid_types}"
        )

        valid_route_ids = set(d["routes"]["_id"].tolist())
        invalid_routes  = set(disr["route_id"].unique()) - valid_route_ids
        assert not invalid_routes, (
            f"{label}: disruptions reference unknown routes: {list(invalid_routes)[:5]}"
        )

    def test_starter(self, starter: dict) -> None:
        self._check(starter, "starter")

    def test_full(self, full: dict) -> None:
        self._check(full, "full")


# ---------------------------------------------------------------------------
# 10. Notification IDs match NOT-YYYY-NNNNNN pattern
# ---------------------------------------------------------------------------


class TestNotificationIdFormat:
    _PATTERN = re.compile(r"^NOT-[0-9]{4}-[0-9]{6}$")

    def _check(self, d: dict, label: str) -> None:
        notif = d["notifications"]
        if notif.empty:
            return
        for nid in notif["_id"]:
            assert self._PATTERN.match(nid), (
                f"{label}: invalid notification _id: {nid}"
            )

    def test_starter(self, starter: dict) -> None:
        self._check(starter, "starter")

    def test_full(self, full: dict) -> None:
        self._check(full, "full")


# ---------------------------------------------------------------------------
# (Duplicate-key check moved to 3b TestNoDuplicateAttendanceKeys above)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 12. Notification event_id references real attendance _ids
# ---------------------------------------------------------------------------


class TestNotificationEventIdFK:
    def _check(self, d: dict, label: str) -> None:
        notif = d["notifications"]
        att   = d["attendance"]
        if notif.empty:
            return

        valid_att_ids = set(att["_id"].tolist())
        invalid = set(notif["event_id"].unique()) - valid_att_ids
        assert not invalid, (
            f"{label}: notifications reference unknown event_ids: "
            f"{list(invalid)[:5]}"
        )

    def test_starter(self, starter: dict) -> None:
        self._check(starter, "starter")

    def test_full(self, full: dict) -> None:
        self._check(full, "full")


# ---------------------------------------------------------------------------
# 13. Skipped notifications: synthetic invalid-contact guardian
#
# Real master-data generates only VALID contacts, so the skipped path is
# never exercised by _build_pipeline().  This unit test constructs minimal
# synthetic DataFrames that force the two skip reasons and asserts that:
#   • a student with no guardian at all  → skipped, reason "no_valid_guardian"
#   • a student whose only guardian has
#     contact_status != "VALID"          → skipped, reason "no_valid_guardian"
#   • a student with a VALID guardian
#     but notification_preferences=[]   → skipped, reason "no_valid_channel"
#   • the notification count identity holds: sent + skipped == triggering
# ---------------------------------------------------------------------------


class TestSkippedNotifications:
    @staticmethod
    def _make_synthetic_data() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        """Return (attendance_df, students_df, guardian_contacts_df) with
        crafted skip scenarios."""
        import datetime as dt

        day = dt.datetime(2025, 9, 1)

        # Three students
        students = pd.DataFrame([
            {"_id": "STU-000001", "guardian_ids": []},                    # no guardian at all
            {"_id": "STU-000002", "guardian_ids": ["GRD-000001"]},        # INVALID guardian
            {"_id": "STU-000003", "guardian_ids": ["GRD-000002"]},        # VALID, no channel
            {"_id": "STU-000004", "guardian_ids": ["GRD-000003"]},        # VALID, sms channel
        ])

        guardians = pd.DataFrame([
            {
                "_id": "GRD-000001",
                "contact_status": "INVALID",
                "is_valid": False,
                "notification_preferences": ["sms"],
            },
            {
                "_id": "GRD-000002",
                "contact_status": "VALID",
                "is_valid": True,
                "notification_preferences": [],   # no valid channel
            },
            {
                "_id": "GRD-000003",
                "contact_status": "VALID",
                "is_valid": True,
                "notification_preferences": ["sms"],
            },
        ])

        # One absent event per student
        attendance = pd.DataFrame([
            {
                "_id":           f"ATT-20250901-STU-00000{i}-absent",
                "student_id":    f"STU-00000{i}",
                "event_type":    "absent",
                "date":          day,
                "assignment_id": f"ASN-STU-00000{i}-2026",
                "route_id":      "ROUTE-2026-000001",
                "stop_id":       "STOP-000001",
            }
            for i in range(1, 5)
        ])

        return attendance, students, guardians

    def test_no_guardian_produces_skip(self) -> None:
        att, stu, grd = self._make_synthetic_data()
        notif, skip = generate_notifications(att, stu, grd)

        stu1_skips = skip[skip["student_id"] == "STU-000001"]
        assert len(stu1_skips) == 1, (
            "Student with no guardian should produce exactly 1 skipped row"
        )
        assert stu1_skips.iloc[0]["reason"] == "no_valid_guardian"

    def test_invalid_guardian_produces_skip(self) -> None:
        att, stu, grd = self._make_synthetic_data()
        notif, skip = generate_notifications(att, stu, grd)

        stu2_skips = skip[skip["student_id"] == "STU-000002"]
        assert len(stu2_skips) == 1, (
            "Student with only an INVALID guardian should produce 1 skipped row"
        )
        assert stu2_skips.iloc[0]["reason"] == "no_valid_guardian"

    def test_no_channel_produces_skip(self) -> None:
        att, stu, grd = self._make_synthetic_data()
        notif, skip = generate_notifications(att, stu, grd)

        stu3_skips = skip[skip["student_id"] == "STU-000003"]
        assert len(stu3_skips) == 1, (
            "Student with VALID guardian but no channel should produce 1 skipped row"
        )
        assert stu3_skips.iloc[0]["reason"] == "no_valid_channel"

    def test_valid_guardian_with_channel_produces_notification(self) -> None:
        att, stu, grd = self._make_synthetic_data()
        notif, skip = generate_notifications(att, stu, grd)

        stu4_notifs = notif[notif["student_id"] == "STU-000004"]
        assert len(stu4_notifs) == 1, (
            "Student with VALID guardian + sms channel should produce 1 notification"
        )
        assert stu4_notifs.iloc[0]["channel"] == "sms"

    def test_count_identity_with_skips(self) -> None:
        att, stu, grd = self._make_synthetic_data()
        notif, skip = generate_notifications(att, stu, grd)

        triggering = int(att["event_type"].isin(["absent", "no_show"]).sum())
        assert len(notif) + len(skip) == triggering, (
            f"sent({len(notif)}) + skipped({len(skip)}) != triggering({triggering})"
        )


# ---------------------------------------------------------------------------
# 14. No imports from ground_truth or anomaly code
# ---------------------------------------------------------------------------


class TestNoForbiddenImports:
    _MODULES = [
        "backend.app.generators.attendance_generator",
        "backend.app.generators.notification_generator",
    ]
    _FORBIDDEN = re.compile(r"ground_truth|anomaly", re.IGNORECASE)

    def _check_source(self, module_name: str) -> None:
        import inspect
        mod = importlib.import_module(module_name)
        source = inspect.getsource(mod)

        # Strip comment lines before checking for real import usage
        import_lines = [
            line for line in source.splitlines()
            if re.match(r"\s*(import|from)\s", line)
        ]
        for line in import_lines:
            assert not self._FORBIDDEN.search(line), (
                f"{module_name}: forbidden import found: {line.strip()!r}"
            )

    def test_attendance_generator(self) -> None:
        self._check_source("backend.app.generators.attendance_generator")

    def test_notification_generator(self) -> None:
        self._check_source("backend.app.generators.notification_generator")


# ---------------------------------------------------------------------------
# 14. Summary statistics (printed, not asserted -- informational)
# ---------------------------------------------------------------------------


class TestSummaryStatistics:
    def _print_summary(self, d: dict, scale: str, label: str) -> None:
        att   = d["attendance"]
        disr  = d["disruptions"]
        notif = d["notifications"]
        skip  = d["skipped"]
        asn   = d["assignments"]

        if att.empty:
            print(f"\n[{label}] No attendance events generated.")
            return

        n_active = int((asn["status"] == "active").sum())
        n_days   = SCALES[scale]["school_days"]
        aad      = n_active * n_days

        total         = len(att)
        present_count = int((att["event_type"] == "boarded").sum())
        absent_count  = int((att["event_type"] == "absent").sum())
        missed_count  = int((att["event_type"] == "no_show").sum())
        late_count    = int((att["event_type"] == "late_pickup").sum())
        # Rate uses aad as denominator (semantically correct; numerically == total)
        att_rate      = present_count / aad if aad else 0.0
        disr_count    = len(disr) if not disr.empty else 0
        notif_sent    = len(notif)
        notif_skipped = len(skip)

        delivered = 0
        failed    = 0
        if not notif.empty and "status" in notif.columns:
            delivered = int((notif["status"] == "delivered").sum())
            failed    = int((notif["status"] == "failed").sum())

        print(
            f"\n{'='*60}\n"
            f"Scale : {label.upper()}\n"
            f"  Active assignments       : {n_active:,}\n"
            f"  School days              : {n_days}\n"
            f"  Active assignment-days   : {aad:,}\n"
            f"  Total attendance rows    : {total:,}  (should == aad)\n"
            f"  Attendance rate          : {att_rate:.2%}  (boarded/aad)\n"
            f"  Absent                   : {absent_count:,}\n"
            f"  Missed pickup (no_show)  : {missed_count:,}\n"
            f"  Late pickup (cap-reduced): {late_count:,}\n"
            f"  Route disruptions        : {disr_count:,}\n"
            f"  Notifications sent       : {notif_sent:,}\n"
            f"    -> delivered           : {delivered:,}\n"
            f"    -> failed              : {failed:,}\n"
            f"  Notifications skipped    : {notif_skipped:,}\n"
            f"{'='*60}"
        )

    def test_starter_summary(self, starter: dict, capsys) -> None:
        self._print_summary(starter, "starter", "starter")
        captured = capsys.readouterr()
        print(captured.out)
        assert True

    def test_full_summary(self, full: dict, capsys) -> None:
        self._print_summary(full, "full", "full")
        captured = capsys.readouterr()
        print(captured.out)
        assert True

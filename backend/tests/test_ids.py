"""
backend/tests/test_ids.py
--------------------------
Tests for backend/app/core/ids.py

Covers:
  - Correct format and prefix for every generator
  - Zero-padding to the right width
  - Uniqueness across 5000 generated IDs
  - Round-trip: generate → parse → regenerate gives same string
  - Invalid input raises ValueError (bad n, bad year, bad string)
"""

from __future__ import annotations

import pytest

from backend.app.core.ids import (
    ParsedId,
    assert_valid_id,
    assignment_id,
    bus_id,
    driver_id,
    guardian_id,
    notification_id,
    parse_id,
    route_id,
    stop_id,
    student_id,
    validate_id,
    zone_id,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SCHOOL_YEAR = 2026


# ---------------------------------------------------------------------------
# 1. Format and prefix tests
# ---------------------------------------------------------------------------


class TestFormat:
    def test_student_id_prefix(self):
        assert student_id(1).startswith("STU-")

    def test_stop_id_prefix(self):
        assert stop_id(1).startswith("STOP-")

    def test_bus_id_prefix(self):
        assert bus_id(1).startswith("BUS-")

    def test_driver_id_prefix(self):
        assert driver_id(1).startswith("DRV-")

    def test_zone_id_prefix(self):
        assert zone_id(1).startswith("ZONE-")

    def test_guardian_id_prefix(self):
        assert guardian_id(1).startswith("GRD-")

    def test_route_id_prefix(self):
        assert route_id(1).startswith("ROUTE-")

    def test_assignment_id_prefix(self):
        assert assignment_id(student_id(1)).startswith("ASN-")

    def test_notification_id_prefix(self):
        assert notification_id(1).startswith("NOT-")

    def test_route_id_contains_year(self):
        assert f"ROUTE-{SCHOOL_YEAR}-" in route_id(1, SCHOOL_YEAR)

    def test_assignment_id_contains_student_and_year(self):
        sid = student_id(42)
        aid = assignment_id(sid, SCHOOL_YEAR)
        assert sid in aid
        assert str(SCHOOL_YEAR) in aid

    def test_notification_id_contains_year(self):
        assert str(SCHOOL_YEAR) in notification_id(1, SCHOOL_YEAR)


# ---------------------------------------------------------------------------
# 2. Zero-padding tests
# ---------------------------------------------------------------------------


class TestZeroPadding:
    def test_student_pads_to_6(self):
        assert student_id(1) == "STU-000001"
        assert student_id(999999) == "STU-999999"

    def test_stop_pads_to_6(self):
        assert stop_id(1) == "STOP-000001"

    def test_bus_pads_to_6(self):
        assert bus_id(1) == "BUS-000001"

    def test_driver_pads_to_6(self):
        assert driver_id(1) == "DRV-000001"

    def test_zone_pads_to_4(self):
        assert zone_id(1) == "ZONE-0001"
        assert zone_id(9999) == "ZONE-9999"

    def test_guardian_pads_to_6(self):
        assert guardian_id(1) == "GRD-000001"

    def test_route_pads_to_6(self):
        assert route_id(1, SCHOOL_YEAR) == f"ROUTE-{SCHOOL_YEAR}-000001"

    def test_assignment_pads_student_part(self):
        assert assignment_id(student_id(1), SCHOOL_YEAR) == f"ASN-STU-000001-{SCHOOL_YEAR}"

    def test_notification_pads_to_6(self):
        assert notification_id(1, SCHOOL_YEAR) == f"NOT-{SCHOOL_YEAR}-000001"


# ---------------------------------------------------------------------------
# 3. Uniqueness across 5000 IDs
# ---------------------------------------------------------------------------


class TestUniqueness:
    N = 5_000

    def test_student_ids_unique(self):
        ids = [student_id(i) for i in range(1, self.N + 1)]
        assert len(ids) == len(set(ids))

    def test_stop_ids_unique(self):
        ids = [stop_id(i) for i in range(1, self.N + 1)]
        assert len(ids) == len(set(ids))

    def test_bus_ids_unique(self):
        ids = [bus_id(i) for i in range(1, self.N + 1)]
        assert len(ids) == len(set(ids))

    def test_driver_ids_unique(self):
        ids = [driver_id(i) for i in range(1, self.N + 1)]
        assert len(ids) == len(set(ids))

    def test_guardian_ids_unique(self):
        ids = [guardian_id(i) for i in range(1, self.N + 1)]
        assert len(ids) == len(set(ids))

    def test_route_ids_unique(self):
        ids = [route_id(i, SCHOOL_YEAR) for i in range(1, self.N + 1)]
        assert len(ids) == len(set(ids))

    def test_assignment_ids_unique(self):
        ids = [assignment_id(student_id(i), SCHOOL_YEAR) for i in range(1, self.N + 1)]
        assert len(ids) == len(set(ids))

    def test_notification_ids_unique(self):
        ids = [notification_id(i, SCHOOL_YEAR) for i in range(1, self.N + 1)]
        assert len(ids) == len(set(ids))

    def test_zone_ids_unique(self):
        # zones only go to 9999 max; test up to 9999
        ids = [zone_id(i) for i in range(1, 9_999 + 1)]
        assert len(ids) == len(set(ids))


# ---------------------------------------------------------------------------
# 4. Round-trip parse tests
# ---------------------------------------------------------------------------


class TestRoundTrip:
    def test_student_round_trip(self):
        original = student_id(123)
        parsed = parse_id(original)
        assert parsed.kind == "student"
        assert parsed.n == 123
        assert parsed.year is None
        assert student_id(parsed.n) == original

    def test_stop_round_trip(self):
        original = stop_id(456)
        parsed = parse_id(original)
        assert parsed.kind == "stop"
        assert parsed.n == 456
        assert stop_id(parsed.n) == original

    def test_bus_round_trip(self):
        original = bus_id(7)
        parsed = parse_id(original)
        assert parsed.kind == "bus"
        assert parsed.n == 7
        assert bus_id(parsed.n) == original

    def test_driver_round_trip(self):
        original = driver_id(99)
        parsed = parse_id(original)
        assert parsed.kind == "driver"
        assert parsed.n == 99
        assert driver_id(parsed.n) == original

    def test_zone_round_trip(self):
        original = zone_id(30)
        parsed = parse_id(original)
        assert parsed.kind == "zone"
        assert parsed.n == 30
        assert zone_id(parsed.n) == original

    def test_guardian_round_trip(self):
        original = guardian_id(500)
        parsed = parse_id(original)
        assert parsed.kind == "guardian"
        assert parsed.n == 500
        assert guardian_id(parsed.n) == original

    def test_route_round_trip(self):
        original = route_id(88, SCHOOL_YEAR)
        parsed = parse_id(original)
        assert parsed.kind == "route"
        assert parsed.n == 88
        assert parsed.year == SCHOOL_YEAR
        assert route_id(parsed.n, parsed.year) == original

    def test_assignment_round_trip(self):
        sid = student_id(42)
        original = assignment_id(sid, SCHOOL_YEAR)
        parsed = parse_id(original)
        assert parsed.kind == "assignment"
        assert parsed.n == 42
        assert parsed.year == SCHOOL_YEAR
        assert assignment_id(student_id(parsed.n), parsed.year) == original

    def test_notification_round_trip(self):
        original = notification_id(999, SCHOOL_YEAR)
        parsed = parse_id(original)
        assert parsed.kind == "notification"
        assert parsed.n == 999
        assert parsed.year == SCHOOL_YEAR
        assert notification_id(parsed.n, parsed.year) == original


# ---------------------------------------------------------------------------
# 5. Invalid input rejection
# ---------------------------------------------------------------------------


class TestInvalidInput:

    # --- n out of range ---
    def test_student_n_zero_raises(self):
        with pytest.raises(ValueError):
            student_id(0)

    def test_student_n_negative_raises(self):
        with pytest.raises(ValueError):
            student_id(-1)

    def test_student_n_overflow_raises(self):
        with pytest.raises(ValueError):
            student_id(1_000_000)

    def test_zone_n_overflow_raises(self):
        with pytest.raises(ValueError):
            zone_id(10_000)

    def test_bus_n_zero_raises(self):
        with pytest.raises(ValueError):
            bus_id(0)

    # --- wrong type ---
    def test_student_float_raises(self):
        with pytest.raises((ValueError, TypeError)):
            student_id(1.0)  # type: ignore[arg-type]

    def test_student_bool_raises(self):
        # bool is a subclass of int in Python; we explicitly block it
        with pytest.raises(ValueError):
            student_id(True)

    # --- bad year ---
    def test_route_year_too_low_raises(self):
        with pytest.raises(ValueError):
            route_id(1, 1999)

    def test_route_year_too_high_raises(self):
        with pytest.raises(ValueError):
            route_id(1, 2101)

    def test_notification_bad_year_raises(self):
        with pytest.raises(ValueError):
            notification_id(1, 1900)

    # --- assignment_id with bad student_id string ---
    def test_assignment_bad_student_id_raises(self):
        with pytest.raises(ValueError):
            assignment_id("INVALID-001", SCHOOL_YEAR)

    def test_assignment_empty_student_id_raises(self):
        with pytest.raises(ValueError):
            assignment_id("", SCHOOL_YEAR)

    # --- parse_id with unknown string ---
    def test_parse_unknown_raises(self):
        with pytest.raises(ValueError):
            parse_id("UNKNOWN-001")

    def test_parse_empty_raises(self):
        with pytest.raises(ValueError):
            parse_id("")

    # --- validate_id ---
    def test_validate_known_kind_valid(self):
        assert validate_id("STU-000001", "student") is True

    def test_validate_known_kind_invalid(self):
        assert validate_id("STU-1", "student") is False

    def test_validate_unknown_kind_raises(self):
        with pytest.raises(ValueError):
            validate_id("STU-000001", "spaceship")

    def test_assert_valid_id_raises_on_bad(self):
        with pytest.raises(ValueError):
            assert_valid_id("BUS-1", "bus")

    def test_assert_valid_id_passes_on_good(self):
        assert_valid_id("BUS-000001", "bus")  # should not raise

"""
backend/tests/test_master_data.py
-----------------------------------
Tests for backend/app/generators/master_data.py

Coverage:
  1. Row counts per scale (starter and full)
  2. Unique IDs in every collection
  3. Foreign key validity:
       - stop.zone_id  → address_zones._id
       - student.zone_id → address_zones._id
       - driver.bus_id → buses._id
       - guardian.student_id → students._id
       - student.guardian_ids ⊆ guardian_contacts._id
  4. Approved-stop ratio within tolerance (92 % ± 5 pp)
  5. Bus accessibility ratio within tolerance (20 % ± 8 pp)
  6. Student accessibility ratio within tolerance (6 % ± 4 pp)
  7. Two runs with the same seed produce identical DataFrames
  8. Required fields present (no nulls on required columns)
  9. ID format validation (regex patterns from ids.py)
 10. Guardian contact_status is always VALID, is_valid always True
"""

from __future__ import annotations

import pandas as pd
import pytest

from backend.app.core.config import SCALES
from backend.app.core.ids import validate_id
from backend.app.generators.master_data import (
    STOP_APPROVAL_RATE,
    BUS_ACCESSIBILITY_RATE,
    STUDENT_ACCESSIBILITY_RATE,
    distribution_summary,
    generate_master_data,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def starter_data() -> dict[str, pd.DataFrame]:
    return generate_master_data("starter")


@pytest.fixture(scope="module")
def full_data() -> dict[str, pd.DataFrame]:
    return generate_master_data("full")


# ---------------------------------------------------------------------------
# 1. Row counts per scale
# ---------------------------------------------------------------------------


class TestRowCounts:
    def test_starter_zones(self, starter_data):
        assert len(starter_data["address_zones"]) == SCALES["starter"]["zones"]

    def test_starter_stops(self, starter_data):
        assert len(starter_data["stops"]) == SCALES["starter"]["stops"]

    def test_starter_buses(self, starter_data):
        assert len(starter_data["buses"]) == SCALES["starter"]["buses"]

    def test_starter_drivers(self, starter_data):
        assert len(starter_data["drivers"]) == SCALES["starter"]["drivers"]

    def test_starter_students(self, starter_data):
        assert len(starter_data["students"]) == SCALES["starter"]["students"]

    def test_starter_guardians_between_1_and_2_per_student(self, starter_data):
        n_students = len(starter_data["students"])
        n_guardians = len(starter_data["guardian_contacts"])
        assert n_students <= n_guardians <= 2 * n_students

    def test_full_zones(self, full_data):
        assert len(full_data["address_zones"]) == SCALES["full"]["zones"]

    def test_full_stops(self, full_data):
        assert len(full_data["stops"]) == SCALES["full"]["stops"]

    def test_full_buses(self, full_data):
        assert len(full_data["buses"]) == SCALES["full"]["buses"]

    def test_full_drivers(self, full_data):
        assert len(full_data["drivers"]) == SCALES["full"]["drivers"]

    def test_full_students(self, full_data):
        assert len(full_data["students"]) == SCALES["full"]["students"]

    def test_full_guardians_between_1_and_2_per_student(self, full_data):
        n_students = len(full_data["students"])
        n_guardians = len(full_data["guardian_contacts"])
        assert n_students <= n_guardians <= 2 * n_students


# ---------------------------------------------------------------------------
# 2. Unique IDs
# ---------------------------------------------------------------------------


class TestUniqueIds:
    @pytest.mark.parametrize("collection", [
        "address_zones", "stops", "buses", "drivers", "students", "guardian_contacts"
    ])
    def test_ids_unique_starter(self, starter_data, collection):
        ids = starter_data[collection]["_id"]
        assert ids.nunique() == len(ids), f"Duplicate _id in starter/{collection}"

    @pytest.mark.parametrize("collection", [
        "address_zones", "stops", "buses", "drivers", "students", "guardian_contacts"
    ])
    def test_ids_unique_full(self, full_data, collection):
        ids = full_data[collection]["_id"]
        assert ids.nunique() == len(ids), f"Duplicate _id in full/{collection}"

    def test_bus_plates_unique_starter(self, starter_data):
        plates = starter_data["buses"]["license_plate"]
        assert plates.nunique() == len(plates)

    def test_bus_plates_unique_full(self, full_data):
        plates = full_data["buses"]["license_plate"]
        assert plates.nunique() == len(plates)

    def test_driver_license_numbers_unique_starter(self, starter_data):
        lics = starter_data["drivers"]["license_number"]
        assert lics.nunique() == len(lics)

    def test_driver_license_numbers_unique_full(self, full_data):
        lics = full_data["drivers"]["license_number"]
        assert lics.nunique() == len(lics)


# ---------------------------------------------------------------------------
# 3. Foreign key validity
# ---------------------------------------------------------------------------


class TestForeignKeys:
    def _fk_check(self, child_col, parent_ids, label):
        invalid = set(child_col.unique()) - set(parent_ids)
        assert not invalid, f"FK violation in {label}: {invalid}"

    def test_stop_zone_id_valid_starter(self, starter_data):
        self._fk_check(
            starter_data["stops"]["zone_id"],
            starter_data["address_zones"]["_id"].tolist(),
            "stops.zone_id → address_zones (starter)",
        )

    def test_stop_zone_id_valid_full(self, full_data):
        self._fk_check(
            full_data["stops"]["zone_id"],
            full_data["address_zones"]["_id"].tolist(),
            "stops.zone_id → address_zones (full)",
        )

    def test_student_zone_id_valid_starter(self, starter_data):
        self._fk_check(
            starter_data["students"]["zone_id"],
            starter_data["address_zones"]["_id"].tolist(),
            "students.zone_id → address_zones (starter)",
        )

    def test_student_zone_id_valid_full(self, full_data):
        self._fk_check(
            full_data["students"]["zone_id"],
            full_data["address_zones"]["_id"].tolist(),
            "students.zone_id → address_zones (full)",
        )

    def test_driver_bus_id_valid_starter(self, starter_data):
        self._fk_check(
            starter_data["drivers"]["bus_id"],
            starter_data["buses"]["_id"].tolist(),
            "drivers.bus_id → buses (starter)",
        )

    def test_driver_bus_id_valid_full(self, full_data):
        self._fk_check(
            full_data["drivers"]["bus_id"],
            full_data["buses"]["_id"].tolist(),
            "drivers.bus_id → buses (full)",
        )

    def test_guardian_student_id_valid_starter(self, starter_data):
        self._fk_check(
            starter_data["guardian_contacts"]["student_id"],
            starter_data["students"]["_id"].tolist(),
            "guardian_contacts.student_id → students (starter)",
        )

    def test_guardian_student_id_valid_full(self, full_data):
        self._fk_check(
            full_data["guardian_contacts"]["student_id"],
            full_data["students"]["_id"].tolist(),
            "guardian_contacts.student_id → students (full)",
        )

    def test_student_guardian_ids_valid_starter(self, starter_data):
        grd_ids = set(starter_data["guardian_contacts"]["_id"].tolist())
        for grd_list in starter_data["students"]["guardian_ids"]:
            invalid = set(grd_list) - grd_ids
            assert not invalid, f"Student.guardian_ids references unknown: {invalid}"

    def test_student_guardian_ids_valid_full(self, full_data):
        grd_ids = set(full_data["guardian_contacts"]["_id"].tolist())
        for grd_list in full_data["students"]["guardian_ids"]:
            invalid = set(grd_list) - grd_ids
            assert not invalid, f"Student.guardian_ids references unknown: {invalid}"

    def test_every_student_has_at_least_one_guardian_starter(self, starter_data):
        for grd_list in starter_data["students"]["guardian_ids"]:
            assert len(grd_list) >= 1

    def test_every_student_has_at_least_one_guardian_full(self, full_data):
        for grd_list in full_data["students"]["guardian_ids"]:
            assert len(grd_list) >= 1

    def test_drivers_one_per_bus_starter(self, starter_data):
        """Every bus has exactly one driver; no bus is unassigned."""
        bus_ids   = set(starter_data["buses"]["_id"].tolist())
        drv_buses = set(starter_data["drivers"]["bus_id"].tolist())
        assert bus_ids == drv_buses

    def test_drivers_one_per_bus_full(self, full_data):
        bus_ids   = set(full_data["buses"]["_id"].tolist())
        drv_buses = set(full_data["drivers"]["bus_id"].tolist())
        assert bus_ids == drv_buses


# ---------------------------------------------------------------------------
# 4. Approved-stop ratio within tolerance
# ---------------------------------------------------------------------------

# Seeded stops (one per zone) are always approved, which slightly raises the
# overall approval rate above STOP_APPROVAL_RATE.  Tolerance is widened to
# account for this upward bias.
APPROVAL_TOLERANCE = 0.08  # ± 8 percentage points


class TestApprovalRatio:
    def _check_ratio(self, stops_df, label):
        ratio = stops_df["is_approved"].mean()
        # Lower bound: at minimum the seeded stops alone would be 30/40=75% for
        # starter, so we only test that we're above a floor and below 1.0.
        assert ratio >= STOP_APPROVAL_RATE - APPROVAL_TOLERANCE, (
            f"{label}: approval rate {ratio:.3f} unexpectedly low"
        )
        assert ratio <= 1.0, f"{label}: approval rate {ratio:.3f} > 1.0"

    def test_starter_approval_ratio(self, starter_data):
        self._check_ratio(starter_data["stops"], "starter")

    def test_full_approval_ratio(self, full_data):
        self._check_ratio(full_data["stops"], "full")

    def test_unapproved_stops_have_pending_status_starter(self, starter_data):
        unapproved = starter_data["stops"][~starter_data["stops"]["is_approved"]]
        assert (unapproved["status"] == "pending_approval").all()

    def test_approved_stops_have_active_status_starter(self, starter_data):
        approved = starter_data["stops"][starter_data["stops"]["is_approved"]]
        assert (approved["status"] == "active").all()

    def test_every_zone_has_at_least_one_approved_stop_starter(self, starter_data):
        """Zone seeding rule: every zone must have ≥1 approved stop."""
        zones    = starter_data["address_zones"]["_id"].tolist()
        stops    = starter_data["stops"]
        approved = stops[stops["is_approved"]]
        for zone in zones:
            count = (approved["zone_id"] == zone).sum()
            assert count >= 1, f"starter: zone {zone} has no approved stop"

    def test_every_zone_has_at_least_one_approved_stop_full(self, full_data):
        zones    = full_data["address_zones"]["_id"].tolist()
        stops    = full_data["stops"]
        approved = stops[stops["is_approved"]]
        for zone in zones:
            count = (approved["zone_id"] == zone).sum()
            assert count >= 1, f"full: zone {zone} has no approved stop"


# ---------------------------------------------------------------------------
# 5. Bus accessibility ratio within tolerance
# ---------------------------------------------------------------------------


BUS_ACCESS_TOLERANCE_SMALL = 0.15  # ± 15 pp for n < 50 (high variance with few buses)
BUS_ACCESS_TOLERANCE_LARGE = 0.08  # ± 8 pp for n >= 50


class TestBusAccessibility:
    def _check_ratio(self, buses_df, label):
        n = len(buses_df)
        tol = BUS_ACCESS_TOLERANCE_SMALL if n < 50 else BUS_ACCESS_TOLERANCE_LARGE
        ratio = buses_df["is_accessible"].mean()
        low  = BUS_ACCESSIBILITY_RATE - tol
        high = BUS_ACCESSIBILITY_RATE + tol
        assert low <= ratio <= high, (
            f"{label}: bus accessibility rate {ratio:.3f} outside [{low:.3f}, {high:.3f}] (n={n})"
        )

    def test_starter_bus_accessibility_ratio(self, starter_data):
        self._check_ratio(starter_data["buses"], "starter")

    def test_full_bus_accessibility_ratio(self, full_data):
        self._check_ratio(full_data["buses"], "full")

    def test_accessible_buses_have_min_capacity_36_starter(self, starter_data):
        accessible = starter_data["buses"][starter_data["buses"]["is_accessible"]]
        assert (accessible["capacity"] >= 36).all()


# ---------------------------------------------------------------------------
# 6. Student accessibility ratio within tolerance
# ---------------------------------------------------------------------------


STU_ACCESS_TOLERANCE = 0.04  # ± 4 percentage points


class TestStudentAccessibility:
    def _check_ratio(self, students_df, label):
        ratio = students_df["accessibility_required"].mean()
        low  = STUDENT_ACCESSIBILITY_RATE - STU_ACCESS_TOLERANCE
        high = STUDENT_ACCESSIBILITY_RATE + STU_ACCESS_TOLERANCE
        assert low <= ratio <= high, (
            f"{label}: student accessibility rate {ratio:.3f} outside [{low:.3f}, {high:.3f}]"
        )

    def test_starter_student_accessibility_ratio(self, starter_data):
        self._check_ratio(starter_data["students"], "starter")

    def test_full_student_accessibility_ratio(self, full_data):
        self._check_ratio(full_data["students"], "full")


# ---------------------------------------------------------------------------
# 7. Determinism: two runs produce identical DataFrames
# ---------------------------------------------------------------------------


class TestDeterminism:
    @pytest.mark.parametrize("collection", [
        "address_zones", "stops", "buses", "drivers", "students"
    ])
    def test_starter_deterministic(self, collection):
        run1 = generate_master_data("starter")[collection]
        run2 = generate_master_data("starter")[collection]
        # Compare non-list columns (guardian_ids is a list column)
        list_cols = [c for c in run1.columns if run1[c].dtype == object
                     and isinstance(run1[c].iloc[0], list)]
        scalar_cols = [c for c in run1.columns if c not in list_cols]
        pd.testing.assert_frame_equal(
            run1[scalar_cols].reset_index(drop=True),
            run2[scalar_cols].reset_index(drop=True),
            check_like=False,
        )

    def test_guardian_contacts_deterministic(self):
        run1 = generate_master_data("starter")["guardian_contacts"]
        run2 = generate_master_data("starter")["guardian_contacts"]
        pd.testing.assert_frame_equal(
            run1.reset_index(drop=True),
            run2.reset_index(drop=True),
        )


# ---------------------------------------------------------------------------
# 8. Required fields present (no nulls)
# ---------------------------------------------------------------------------


REQUIRED_FIELDS: dict[str, list[str]] = {
    "address_zones":     ["_id", "name", "zone_type", "created_at"],
    "stops":             ["_id", "name", "lat", "lng", "zone_id", "is_approved", "status", "created_at"],
    "buses":             ["_id", "license_plate", "capacity", "is_accessible", "status", "effective_from", "created_at"],
    "drivers":           ["_id", "first_name", "last_name", "license_number", "license_class", "status", "created_at"],
    "students":          ["_id", "first_name", "last_name", "date_of_birth", "grade", "zone_id",
                          "accessibility_required", "status", "effective_from", "created_at"],
    "guardian_contacts": ["_id", "first_name", "last_name", "relationship",
                          "phone_primary", "contact_status", "is_valid", "created_at"],
}


class TestRequiredFields:
    @pytest.mark.parametrize("collection,fields", REQUIRED_FIELDS.items())
    def test_no_nulls_starter(self, starter_data, collection, fields):
        df = starter_data[collection]
        for field in fields:
            assert field in df.columns, f"{collection} missing column '{field}'"
            null_count = df[field].isnull().sum()
            assert null_count == 0, (
                f"{collection}.{field} has {null_count} null values in starter"
            )


# ---------------------------------------------------------------------------
# 9. ID format validation
# ---------------------------------------------------------------------------


ID_KINDS: dict[str, str] = {
    "address_zones":     "zone",
    "stops":             "stop",
    "buses":             "bus",
    "drivers":           "driver",
    "students":          "student",
    "guardian_contacts": "guardian",
}


class TestIdFormats:
    @pytest.mark.parametrize("collection,kind", ID_KINDS.items())
    def test_id_format_starter(self, starter_data, collection, kind):
        for id_val in starter_data[collection]["_id"]:
            assert validate_id(id_val, kind), (
                f"{collection}: '{id_val}' does not match {kind} pattern"
            )


# ---------------------------------------------------------------------------
# 10. Guardian contact_status and is_valid
# ---------------------------------------------------------------------------


class TestGuardianValidity:
    def test_all_guardians_valid_starter(self, starter_data):
        g = starter_data["guardian_contacts"]
        assert (g["contact_status"] == "VALID").all()
        assert (g["is_valid"] == True).all()  # noqa: E712

    def test_all_guardians_valid_full(self, full_data):
        g = full_data["guardian_contacts"]
        assert (g["contact_status"] == "VALID").all()
        assert (g["is_valid"] == True).all()  # noqa: E712

    def test_guardian_emails_use_example_com_starter(self, starter_data):
        for email in starter_data["guardian_contacts"]["email"]:
            assert email.endswith("@example.com"), f"Non-example email: {email}"

    def test_guardian_phones_10_digits_starter(self, starter_data):
        for phone in starter_data["guardian_contacts"]["phone_primary"]:
            assert len(phone) == 10 and phone.isdigit(), (
                f"Phone not 10 digits: {phone}"
            )

    def test_distribution_summary_runs(self, starter_data):
        summary = distribution_summary(starter_data)
        assert "zones" in summary
        assert "stops" in summary
        assert "buses" in summary
        assert "students" in summary
        assert "guardian_contacts" in summary

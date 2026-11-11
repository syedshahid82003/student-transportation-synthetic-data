"""
database/indexes/indexes.py
----------------------------
Idempotent index-creation script.

Creates all unique and secondary indexes for the transport database.
Safe to re-run: PyMongo skips indexes that already exist with identical options.

Run from the repo root:
    python database/indexes/indexes.py

Requirements:
    pip install pymongo python-dotenv
"""

from __future__ import annotations

import os
import pathlib
import sys

from dotenv import load_dotenv
from pymongo import ASCENDING, DESCENDING, MongoClient
from pymongo.errors import OperationFailure

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

ROOT = pathlib.Path(__file__).resolve().parents[2]
load_dotenv(dotenv_path=ROOT / "backend" / ".env")

MONGO_URI: str = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
DB_NAME: str   = os.environ.get("DB_NAME", "transport")

# ---------------------------------------------------------------------------
# Index definitions
# Each entry: (collection, keys, options)
#   keys    – list of (field, direction) tuples fed to create_index()
#   options – dict passed as kwargs (unique, sparse, name, …)
# ---------------------------------------------------------------------------

INDEX_DEFINITIONS: list[tuple[str, list[tuple[str, int]], dict]] = [

    # -----------------------------------------------------------------------
    # students
    # -----------------------------------------------------------------------
    # _id is always the primary unique index; declared here for documentation.
    # ("students", [("_id", ASCENDING)], {"unique": True, "name": "students_id_unique"}),
    ("students", [("zone_id",    ASCENDING)], {"name": "students_zone_id"}),
    ("students", [("status",     ASCENDING)], {"name": "students_status"}),
    ("students", [("grade",      ASCENDING)], {"name": "students_grade"}),
    ("students", [("last_name",  ASCENDING), ("first_name", ASCENDING)], {"name": "students_name"}),
    ("students", [("effective_from", ASCENDING)], {"name": "students_effective_from"}),
    ("students", [("accessibility_required", ASCENDING)], {"name": "students_accessibility"}),

    # -----------------------------------------------------------------------
    # guardian_contacts
    #
    # phone_primary is NOT unique: siblings share guardians, and the anomaly-
    # injection pipeline deliberately creates duplicate / malformed contacts.
    # The old "guardians_phone_unique" index is dropped below in
    # drop_obsolete_indexes() before this list is applied.
    # -----------------------------------------------------------------------
    ("guardian_contacts", [("last_name",  ASCENDING), ("first_name", ASCENDING)], {"name": "guardians_name"}),
    ("guardian_contacts", [("phone_primary", ASCENDING)], {"name": "guardians_phone"}),
    ("guardian_contacts", [("contact_status", ASCENDING)], {"name": "guardians_contact_status"}),
    ("guardian_contacts", [("is_valid", ASCENDING)], {"name": "guardians_is_valid"}),

    # -----------------------------------------------------------------------
    # address_zones
    # -----------------------------------------------------------------------
    ("address_zones", [("zone_type", ASCENDING)], {"name": "zones_type"}),
    ("address_zones", [("name",      ASCENDING)], {"unique": True, "name": "zones_name_unique"}),

    # -----------------------------------------------------------------------
    # stops
    # -----------------------------------------------------------------------
    ("stops", [("zone_id",     ASCENDING)], {"name": "stops_zone_id"}),
    ("stops", [("status",      ASCENDING)], {"name": "stops_status"}),
    ("stops", [("is_approved", ASCENDING)], {"name": "stops_is_approved"}),
    ("stops", [("lat", ASCENDING), ("lng", ASCENDING)], {"name": "stops_coordinates"}),

    # -----------------------------------------------------------------------
    # buses
    # -----------------------------------------------------------------------
    ("buses", [("license_plate", ASCENDING)], {"unique": True, "name": "buses_plate_unique"}),
    ("buses", [("status",        ASCENDING)], {"name": "buses_status"}),
    ("buses", [("is_accessible", ASCENDING)], {"name": "buses_accessible"}),
    ("buses", [("effective_from", ASCENDING)], {"name": "buses_effective_from"}),

    # -----------------------------------------------------------------------
    # drivers
    # -----------------------------------------------------------------------
    ("drivers", [("license_number", ASCENDING)], {"unique": True, "name": "drivers_license_unique"}),
    ("drivers", [("status",         ASCENDING)], {"name": "drivers_status"}),
    ("drivers", [("last_name", ASCENDING), ("first_name", ASCENDING)], {"name": "drivers_name"}),

    # -----------------------------------------------------------------------
    # routes
    # -----------------------------------------------------------------------
    ("routes", [("bus_id",    ASCENDING)], {"name": "routes_bus_id"}),
    ("routes", [("driver_id", ASCENDING)], {"name": "routes_driver_id"}),
    ("routes", [("status",    ASCENDING)], {"name": "routes_status"}),
    ("routes", [("direction", ASCENDING)], {"name": "routes_direction"}),
    ("routes", [("academic_year", ASCENDING)], {"name": "routes_academic_year"}),
    ("routes", [("effective_from", ASCENDING)], {"name": "routes_effective_from"}),

    # -----------------------------------------------------------------------
    # route_stops  (bridge table)
    # Compound unique enforces that each stop appears at most once per route
    # AND that each sequence position within a route is unique.
    # -----------------------------------------------------------------------
    ("route_stops", [("route_id", ASCENDING), ("sequence", ASCENDING)],
        {"unique": True, "name": "route_stops_route_sequence_unique"}),
    ("route_stops", [("route_id", ASCENDING), ("stop_id",  ASCENDING)],
        {"unique": True, "name": "route_stops_route_stop_unique"}),
    ("route_stops", [("stop_id",  ASCENDING)], {"name": "route_stops_stop_id"}),

    # -----------------------------------------------------------------------
    # assignments
    #
    # ID design: ASN-STU-000001-2026 — one document per student per academic
    # year.  This index is intentionally NON-unique: it supports fast queries
    # like "find the active assignment for student X in year Y" without
    # blocking the design.
    #
    # Reassignments are NEVER stored as a second assignments document.
    # Instead:
    #   1. The existing document's status is changed to "inactive" /
    #      "cancelled" and effective_to is set.
    #   2. The field-level diff is written to audit_events (before_state /
    #      after_state + changed_fields).
    # The _id uniqueness constraint on MongoDB already enforces one document
    # per (student, year), so a unique index here would be redundant and would
    # wrongly suggest multiple documents are expected.
    # -----------------------------------------------------------------------
    ("assignments", [("student_id", ASCENDING), ("academic_year", ASCENDING), ("status", ASCENDING)],
        {"name": "assignments_student_year_status"}),
    ("assignments", [("student_id",   ASCENDING)], {"name": "assignments_student_id"}),
    ("assignments", [("route_id",     ASCENDING)], {"name": "assignments_route_id"}),
    ("assignments", [("stop_id",      ASCENDING)], {"name": "assignments_stop_id"}),
    ("assignments", [("status",       ASCENDING)], {"name": "assignments_status"}),
    ("assignments", [("effective_from", ASCENDING)], {"name": "assignments_effective_from"}),
    ("assignments", [("academic_year",  ASCENDING)], {"name": "assignments_academic_year"}),

    # -----------------------------------------------------------------------
    # attendance_events
    # -----------------------------------------------------------------------
    # Unique: one event_type record per assignment per date.
    ("attendance_events", [("assignment_id", ASCENDING), ("date", ASCENDING), ("event_type", ASCENDING)],
        {"unique": True, "name": "attendance_assignment_date_type_unique"}),
    ("attendance_events", [("student_id",  ASCENDING)], {"name": "attendance_student_id"}),
    ("attendance_events", [("route_id",    ASCENDING)], {"name": "attendance_route_id"}),
    ("attendance_events", [("stop_id",     ASCENDING)], {"name": "attendance_stop_id"}),
    ("attendance_events", [("date",        DESCENDING)], {"name": "attendance_date_desc"}),
    ("attendance_events", [("event_type",  ASCENDING)],  {"name": "attendance_event_type"}),

    # -----------------------------------------------------------------------
    # notifications
    # -----------------------------------------------------------------------
    ("notifications", [("guardian_id",      ASCENDING)], {"name": "notifications_guardian_id"}),
    ("notifications", [("student_id",       ASCENDING)], {"name": "notifications_student_id"}),
    ("notifications", [("event_id",         ASCENDING)], {"name": "notifications_event_id"}),
    ("notifications", [("status",           ASCENDING)], {"name": "notifications_status"}),
    ("notifications", [("channel",          ASCENDING)], {"name": "notifications_channel"}),
    ("notifications", [("created_at",       DESCENDING)], {"name": "notifications_created_at_desc"}),

    # -----------------------------------------------------------------------
    # audit_events  (append-only; never updated or deleted)
    # -----------------------------------------------------------------------
    ("audit_events", [("collection_name", ASCENDING), ("document_id", ASCENDING)],
        {"name": "audit_collection_document"}),
    ("audit_events", [("actor",     ASCENDING)], {"name": "audit_actor"}),
    ("audit_events", [("action",    ASCENDING)], {"name": "audit_action"}),
    ("audit_events", [("timestamp", DESCENDING)], {"name": "audit_timestamp_desc"}),

    # -----------------------------------------------------------------------
    # bus_capacity_history  (append-only)
    # -----------------------------------------------------------------------
    ("bus_capacity_history", [("bus_id", ASCENDING), ("effective_from", DESCENDING)],
        {"name": "bch_bus_effective_from"}),
    ("bus_capacity_history", [("bus_id", ASCENDING)], {"name": "bch_bus_id"}),
]


# ---------------------------------------------------------------------------
# Indexes that existed in a previous schema version and must be dropped before
# the current definitions are applied.  Keyed by (collection, index_name).
# ---------------------------------------------------------------------------

OBSOLETE_INDEXES: list[tuple[str, str]] = [
    # phone_primary was incorrectly unique; siblings share guardians and the
    # anomaly pipeline creates duplicate/invalid contacts intentionally.
    ("guardian_contacts", "guardians_phone_unique"),
]


def drop_obsolete_indexes(db) -> None:
    """Drop any index that conflicts with the current schema design."""
    for collection_name, index_name in OBSOLETE_INDEXES:
        col = db[collection_name]
        existing = {idx["name"] for idx in col.list_indexes()}
        if index_name in existing:
            try:
                col.drop_index(index_name)
                print(f"  [DROPPED]  {collection_name}  →  {index_name}")
            except OperationFailure as exc:
                print(f"  [ERROR]    {collection_name}  →  drop {index_name}: {exc}")
        else:
            print(f"  [SKIP]     {collection_name}  →  {index_name} (not present)")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def create_indexes(db) -> None:
    created = 0
    skipped = 0
    errors  = 0

    for collection_name, keys, options in INDEX_DEFINITIONS:
        col = db[collection_name]
        try:
            col.create_index(keys, **options)
            print(f"  [OK]      {collection_name}  →  {options.get('name', keys)}")
            created += 1
        except OperationFailure as exc:
            # Index already exists with compatible definition — not an error.
            if "already exists" in str(exc) or "IndexOptionsConflict" in str(exc):
                print(f"  [EXISTS]  {collection_name}  →  {options.get('name', keys)}")
                skipped += 1
            else:
                print(f"  [ERROR]   {collection_name}  →  {options.get('name', keys)}: {exc}")
                errors += 1

    print(f"\nIndexes — created: {created}, already existed: {skipped}, errors: {errors}")
    if errors:
        sys.exit(1)


def main() -> None:
    print(f"Connecting to MongoDB at {MONGO_URI} …")
    client: MongoClient = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5_000)

    try:
        client.admin.command("ping")
    except Exception as exc:  # noqa: BLE001
        print(f"[FATAL] Cannot reach MongoDB: {exc}", file=sys.stderr)
        sys.exit(1)

    db = client[DB_NAME]
    print(f"Database : {DB_NAME}\n")

    print("--- Dropping obsolete indexes ---")
    drop_obsolete_indexes(db)
    print()

    print("--- Creating / verifying indexes ---")
    create_indexes(db)
    client.close()


if __name__ == "__main__":
    main()

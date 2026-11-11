"""
database/scripts/setup_db.py
-----------------------------
Idempotent database setup script.

Reads MONGO_URI and DB_NAME from a .env file (or environment), then:
  1. Creates all 13 collections if they do not already exist.
  2. Applies (or updates) a $jsonSchema validator to each collection.
  3. Calls the indexes script to drop obsolete indexes and create/verify all
     current indexes — so one command does the full database setup.

Run from the repo root:
    python database/scripts/setup_db.py

Requirements:
    pip install pymongo python-dotenv
"""

from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import sys

from dotenv import load_dotenv
from pymongo import MongoClient
from pymongo.errors import CollectionInvalid, OperationFailure

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

ROOT = pathlib.Path(__file__).resolve().parents[2]
ENV_FILE = ROOT / "backend" / ".env"
VALIDATORS_DIR = ROOT / "database" / "validators"

load_dotenv(dotenv_path=ENV_FILE)

MONGO_URI: str = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
DB_NAME: str = os.environ.get("DB_NAME", "transport")

# Ordered list of collections to create (order matters for readability, not for
# MongoDB itself, since there are no FK constraints).
COLLECTIONS: list[str] = [
    "students",
    "guardian_contacts",
    "address_zones",
    "stops",
    "buses",
    "drivers",
    "routes",
    "route_stops",
    "assignments",
    "attendance_events",
    "notifications",
    "audit_events",
    "bus_capacity_history",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def load_validator(collection_name: str) -> dict | None:
    """Load the $jsonSchema validator for *collection_name*, if it exists."""
    path = VALIDATORS_DIR / f"{collection_name}.json"
    if not path.exists():
        print(f"  [WARN] No validator file found for '{collection_name}' at {path}")
        return None
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def ensure_collection(db, name: str) -> None:
    """Create *name* if absent; always (re-)apply the JSON Schema validator."""
    validator_doc = load_validator(name)
    validation_opts: dict = {}
    if validator_doc:
        validation_opts = {
            "validator": validator_doc,
            "validationLevel": "strict",
            "validationAction": "error",
        }

    # --- Create collection if it does not exist ---
    if name not in db.list_collection_names():
        try:
            db.create_collection(name, **validation_opts)
            print(f"  [CREATED]  {name}")
        except CollectionInvalid:
            # Race condition: another process created it between the check and here.
            print(f"  [EXISTS]   {name}  (created concurrently, skipping)")
    else:
        # --- Collection exists – update the validator in place ---
        if validator_doc:
            try:
                db.command(
                    "collMod",
                    name,
                    **validation_opts,
                )
                print(f"  [UPDATED]  {name}  (validator refreshed)")
            except OperationFailure as exc:
                print(f"  [ERROR]    {name}  collMod failed: {exc}")
        else:
            print(f"  [EXISTS]   {name}  (no validator to apply)")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    print(f"Connecting to MongoDB at {MONGO_URI} …")
    client: MongoClient = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5_000)

    # Fail fast if the server is unreachable.
    try:
        client.admin.command("ping")
    except Exception as exc:  # noqa: BLE001
        print(f"[FATAL] Cannot reach MongoDB: {exc}", file=sys.stderr)
        sys.exit(1)

    db = client[DB_NAME]
    print(f"Database : {DB_NAME}\n")

    for collection_name in COLLECTIONS:
        ensure_collection(db, collection_name)

    print(f"\nSetup complete. {len(COLLECTIONS)} collections ensured.")

    # --- Now create/verify all indexes ---
    print("\n" + "=" * 70)
    print("Running index setup…")
    print("=" * 70 + "\n")

    # Import and call the indexes script directly rather than subprocess
    # (cleaner, uses the same DB connection context)
    indexes_module_path = ROOT / "database" / "indexes" / "indexes.py"
    spec = importlib.util.spec_from_file_location("indexes", indexes_module_path)
    if not spec or not spec.loader:
        print(f"[ERROR] Could not load {indexes_module_path}", file=sys.stderr)
        sys.exit(1)
    indexes_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(indexes_module)

    # Call the functions directly (they expect an already-connected db object)
    indexes_module.drop_obsolete_indexes(db)
    print()
    indexes_module.create_indexes(db)

    client.close()
    print("\n" + "=" * 70)
    print("Database setup complete: collections + validators + indexes.")
    print("=" * 70)


if __name__ == "__main__":
    main()

"""
scripts/export_pipeline_data.py
--------------------------------
Export complete synthetic dataset for submission.

Runs the full pipeline and writes:
- CSV files for all 11 core entities + auxiliary tables
- Ground truth files (rejections, disruptions, skipped notifications)
- Validation summary
- Manifest with SHA-256 checksums

Usage (from repo root):
    python scripts/export_pipeline_data.py

Outputs to:
- data/generated/*.csv
- data/ground_truth/*.{csv,json}
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import pathlib
import sys

# Set scale to full for complete export
os.environ["DATA_SCALE"] = os.environ.get("DATA_SCALE", "full")

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd

from backend.app.core.config import SEED, DATA_SCALE, SCALES
from backend.app.generators.master_data import generate_master_data
from backend.app.generators.route_generator import generate_routes
from backend.app.services.assignment_service import assign_all_students
from backend.app.services.capacity_service import build_capacity_history
from backend.app.generators.attendance_generator import generate_attendance
from backend.app.generators.notification_generator import generate_notifications

# Output directories
GENERATED_DIR = ROOT / "data" / "generated"
GROUND_TRUTH_DIR = ROOT / "data" / "ground_truth"

GENERATED_DIR.mkdir(parents=True, exist_ok=True)
GROUND_TRUTH_DIR.mkdir(parents=True, exist_ok=True)


def file_sha256(path: pathlib.Path) -> str:
    """Compute SHA-256 hash of a file."""
    sha = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(8192):
            sha.update(chunk)
    return sha.hexdigest()


def write_csv(df: pd.DataFrame, name: str, target_dir: pathlib.Path) -> pathlib.Path:
    """Write DataFrame to CSV and return path."""
    path = target_dir / name
    df.to_csv(path, index=False)
    size_kb = path.stat().st_size / 1024
    print(f"  ✓ {name:35s} {len(df):>6,} rows  {size_kb:>8.1f} KB")
    return path


def main() -> None:
    print(f"\n{'='*70}")
    print("SYNTHETIC DATA EXPORT PIPELINE")
    print(f"{'='*70}\n")
    print(f"Seed: {SEED}")
    print(f"Scale: {DATA_SCALE}")
    print(f"Target volumes: {SCALES[DATA_SCALE]}\n")
    
    print("=" * 70)
    print("STEP 1: Generate Master Data")
    print("=" * 70)
    master = generate_master_data(DATA_SCALE)
    
    print("\n" + "=" * 70)
    print("STEP 2: Generate Routes")
    print("=" * 70)
    rng_routes = np.random.default_rng(SEED)
    routes_df, route_stops_df = generate_routes(
        master["buses"], master["drivers"],
        master["stops"], master["students"], rng_routes,
    )
    
    print("\n" + "=" * 70)
    print("STEP 3: Assign Students")
    print("=" * 70)
    rng_asn = np.random.default_rng(SEED)
    assign_result = assign_all_students(master, routes_df, route_stops_df, rng_asn)
    assignments_df = assign_result["assignments"]
    rejections_df = assign_result["rejections"]
    
    print("\n" + "=" * 70)
    print("STEP 4: Build Capacity History")
    print("=" * 70)
    cap_history = build_capacity_history(master["buses"])
    
    print("\n" + "=" * 70)
    print("STEP 5: Generate Attendance")
    print("=" * 70)
    rng_att = np.random.default_rng(SEED)
    att_df, disr_df = generate_attendance(
        assignments_df, master["students"],
        routes_df, master["buses"],
        scale=DATA_SCALE, rng=rng_att,
    )
    
    print("\n" + "=" * 70)
    print("STEP 6: Generate Notifications")
    print("=" * 70)
    rng_not = np.random.default_rng(SEED)
    notif_df, skipped_df = generate_notifications(
        att_df, master["students"], master["guardian_contacts"], rng=rng_not,
    )
    
    print("\n" + "=" * 70)
    print("STEP 7: Write CSV Files")
    print("=" * 70)
    print("\nCore entity files (data/generated/):")
    
    written_files = []
    
    # Core entities
    written_files.append(write_csv(master["students"], "students.csv", GENERATED_DIR))
    written_files.append(write_csv(master["guardian_contacts"], "guardian_contacts.csv", GENERATED_DIR))
    written_files.append(write_csv(master["address_zones"], "address_zones.csv", GENERATED_DIR))
    written_files.append(write_csv(master["stops"], "stops.csv", GENERATED_DIR))
    written_files.append(write_csv(master["buses"], "buses.csv", GENERATED_DIR))
    written_files.append(write_csv(master["drivers"], "drivers.csv", GENERATED_DIR))
    written_files.append(write_csv(routes_df, "routes.csv", GENERATED_DIR))
    written_files.append(write_csv(route_stops_df, "route_stops.csv", GENERATED_DIR))
    written_files.append(write_csv(assignments_df, "assignments.csv", GENERATED_DIR))
    written_files.append(write_csv(cap_history, "bus_capacity_history.csv", GENERATED_DIR))
    written_files.append(write_csv(att_df, "attendance_events.csv", GENERATED_DIR))
    written_files.append(write_csv(notif_df, "notifications.csv", GENERATED_DIR))
    
    print("\nGround truth files (data/ground_truth/):")
    written_files.append(write_csv(rejections_df, "rejections.csv", GROUND_TRUTH_DIR))
    written_files.append(write_csv(disr_df, "disruptions.csv", GROUND_TRUTH_DIR))
    written_files.append(write_csv(skipped_df, "skipped_notifications.csv", GROUND_TRUTH_DIR))
    
    print("\n" + "=" * 70)
    print("STEP 8: Compute Checksums")
    print("=" * 70)
    
    manifest = {
        "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
        "seed": SEED,
        "scale": DATA_SCALE,
        "volumes": SCALES[DATA_SCALE],
        "files": []
    }
    
    for path in written_files:
        rel_path = path.relative_to(ROOT)
        sha = file_sha256(path)
        manifest["files"].append({
            "path": str(rel_path).replace("\\", "/"),
            "name": path.name,
            "size_bytes": path.stat().st_size,
            "sha256": sha,
        })
        print(f"  {path.name:35s} {sha[:16]}...")
    
    manifest_path = GENERATED_DIR / "manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    print(f"\n  ✓ Manifest written to {manifest_path.name}")
    
    print("\n" + "=" * 70)
    print("STEP 9: Validation Summary")
    print("=" * 70)
    
    n_students = len(master["students"])
    n_assigned = int((assignments_df["status"] == "active").sum())
    n_rejected = len(rejections_df)
    n_routes = int((routes_df["status"] == "active").sum())
    n_attendance = len(att_df)
    n_disruptions = len(disr_df)
    n_notifications = len(notif_df)
    n_skipped = len(skipped_df)
    
    validation = {
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
        "seed": SEED,
        "scale": DATA_SCALE,
        "summary": {
            "students_total": n_students,
            "students_assigned": n_assigned,
            "students_rejected": n_rejected,
            "routes_active": n_routes,
            "attendance_events": n_attendance,
            "disruptions": n_disruptions,
            "notifications_sent": n_notifications,
            "notifications_skipped": n_skipped,
        },
        "primary_key_checks": {
            "students_unique": master["students"]["_id"].is_unique,
            "buses_unique": master["buses"]["_id"].is_unique,
            "stops_unique": master["stops"]["_id"].is_unique,
            "routes_unique": routes_df["_id"].is_unique,
            "assignments_unique": assignments_df["_id"].is_unique,
        },
        "referential_integrity": {
            "all_assignments_valid_student_id": assignments_df["student_id"].isin(master["students"]["_id"]).all(),
            "all_assignments_valid_route_id": assignments_df["route_id"].isin(routes_df["_id"]).all(),
            "all_assignments_valid_stop_id": assignments_df["stop_id"].isin(master["stops"]["_id"]).all(),
            "all_attendance_valid_student_id": att_df["student_id"].isin(master["students"]["_id"]).all(),
            "all_notifications_valid_student_id": notif_df["student_id"].isin(master["students"]["_id"]).all() if not notif_df.empty else True,
        },
    }
    
    validation_path = GENERATED_DIR / "validation_summary.json"
    with open(validation_path, "w", encoding="utf-8") as f:
        json.dump(validation, f, indent=2)
    
    print(f"\nSummary:")
    print(f"  Students (total):      {n_students:>6,}")
    print(f"  Students (assigned):   {n_assigned:>6,}")
    print(f"  Students (rejected):   {n_rejected:>6,}")
    print(f"  Routes (active):       {n_routes:>6,}")
    print(f"  Attendance events:     {n_attendance:>6,}")
    print(f"  Disruptions:           {n_disruptions:>6,}")
    print(f"  Notifications:         {n_notifications:>6,}")
    print(f"  Skipped notifications: {n_skipped:>6,}")
    
    all_valid = all(validation["primary_key_checks"].values()) and \
                all(validation["referential_integrity"].values())
    
    if all_valid:
        print(f"\n  ✓ All validation checks PASSED")
    else:
        print(f"\n  ✗ Some validation checks FAILED")
    
    print(f"\n  Validation summary written to {validation_path.name}")
    
    print("\n" + "=" * 70)
    print("EXPORT COMPLETE")
    print("=" * 70)
    print(f"\nGenerated: {GENERATED_DIR}")
    print(f"Ground truth: {GROUND_TRUTH_DIR}")
    print(f"\nTotal files: {len(written_files)}")
    print(f"Manifest: {manifest_path.name}")
    print(f"Validation: {validation_path.name}\n")


if __name__ == "__main__":
    main()

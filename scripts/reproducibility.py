"""
scripts/reproducibility.py
---------------------------
Reproducibility verification for the Student Transportation data generator.

Runs the full pipeline twice with the same seed and compares SHA-256 checksums
for every entity table to demonstrate deterministic output.

Usage (from repo root):
    python scripts/reproducibility.py

Writes reproducibility_report.json to the current directory.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import pathlib
import sys

# Set scale before imports
os.environ["DATA_SCALE"] = os.environ.get("DATA_SCALE", "starter")

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd

from backend.app.core.config import SEED, DATA_SCALE
from backend.app.generators.master_data import generate_master_data
from backend.app.generators.route_generator import generate_routes
from backend.app.services.assignment_service import assign_all_students
from backend.app.services.capacity_service import build_capacity_history
from backend.app.generators.attendance_generator import generate_attendance
from backend.app.generators.notification_generator import generate_notifications


def dataframe_sha256(df: pd.DataFrame) -> str:
    """Compute SHA-256 hash of a DataFrame's CSV representation."""
    csv_bytes = df.to_csv(index=False).encode("utf-8")
    return hashlib.sha256(csv_bytes).hexdigest()


def run_pipeline() -> dict[str, str]:
    """
    Run the complete data generation pipeline and return SHA-256 hashes
    for all entity tables.
    """
    print(f"  Generating master data (seed {SEED}, scale {DATA_SCALE})...")
    master = generate_master_data(DATA_SCALE)
    
    print("  Generating routes...")
    rng_routes = np.random.default_rng(SEED)
    routes_df, route_stops_df = generate_routes(
        master["buses"], master["drivers"],
        master["stops"], master["students"], rng_routes,
    )
    
    print("  Assigning students...")
    rng_asn = np.random.default_rng(SEED)
    assign_result = assign_all_students(master, routes_df, route_stops_df, rng_asn)
    assignments_df = assign_result["assignments"]
    rejections_df = assign_result["rejections"]
    
    print("  Building capacity history...")
    cap_history = build_capacity_history(master["buses"])
    
    print("  Generating attendance...")
    rng_att = np.random.default_rng(SEED)
    att_df, disr_df = generate_attendance(
        assignments_df, master["students"],
        routes_df, master["buses"],
        scale=DATA_SCALE, rng=rng_att,
    )
    
    print("  Generating notifications...")
    rng_not = np.random.default_rng(SEED)
    notif_df, skipped_df = generate_notifications(
        att_df, master["students"], master["guardian_contacts"], rng=rng_not,
    )
    
    print("  Computing checksums...")
    checksums = {
        "students": dataframe_sha256(master["students"]),
        "guardian_contacts": dataframe_sha256(master["guardian_contacts"]),
        "address_zones": dataframe_sha256(master["address_zones"]),
        "stops": dataframe_sha256(master["stops"]),
        "buses": dataframe_sha256(master["buses"]),
        "drivers": dataframe_sha256(master["drivers"]),
        "routes": dataframe_sha256(routes_df),
        "route_stops": dataframe_sha256(route_stops_df),
        "assignments": dataframe_sha256(assignments_df),
        "rejections": dataframe_sha256(rejections_df),
        "bus_capacity_history": dataframe_sha256(cap_history),
        "attendance_events": dataframe_sha256(att_df),
        "disruptions": dataframe_sha256(disr_df),
        "notifications": dataframe_sha256(notif_df),
        "skipped_notifications": dataframe_sha256(skipped_df),
    }
    
    return checksums


def main() -> None:
    print(f"\n{'='*70}")
    print("REPRODUCIBILITY VERIFICATION")
    print(f"{'='*70}\n")
    print(f"Seed: {SEED}")
    print(f"Scale: {DATA_SCALE}\n")
    
    print("Run 1:")
    print("-" * 70)
    checksums_1 = run_pipeline()
    
    print("\nRun 2:")
    print("-" * 70)
    checksums_2 = run_pipeline()
    
    print(f"\n{'='*70}")
    print("COMPARISON")
    print(f"{'='*70}\n")
    
    all_match = True
    mismatches = []
    
    for entity in sorted(checksums_1.keys()):
        hash_1 = checksums_1[entity]
        hash_2 = checksums_2[entity]
        match = hash_1 == hash_2
        status = "✓ MATCH" if match else "✗ MISMATCH"
        
        print(f"{entity:25s} {status}")
        print(f"  Run 1: {hash_1[:16]}...")
        print(f"  Run 2: {hash_2[:16]}...")
        
        if not match:
            all_match = False
            mismatches.append(entity)
    
    print(f"\n{'='*70}")
    if all_match:
        print("✓ SUCCESS: All entities match across both runs")
        print("Deterministic reproducibility verified.")
    else:
        print(f"✗ FAILURE: {len(mismatches)} entities differ between runs")
        print(f"Mismatched entities: {', '.join(mismatches)}")
    print(f"{'='*70}\n")
    
    # Write report
    report = {
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
        "seed": SEED,
        "scale": DATA_SCALE,
        "reproducible": all_match,
        "entities_compared": len(checksums_1),
        "entities_matched": len(checksums_1) - len(mismatches),
        "entities_mismatched": len(mismatches),
        "mismatched_entities": mismatches,
        "checksums": {
            "run_1": checksums_1,
            "run_2": checksums_2,
        },
    }
    
    report_path = ROOT / "reproducibility_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    
    print(f"Report written to: {report_path}")
    
    sys.exit(0 if all_match else 1)


if __name__ == "__main__":
    main()

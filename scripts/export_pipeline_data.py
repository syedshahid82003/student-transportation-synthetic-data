"""
scripts/export_pipeline_data.py
--------------------------------
Export complete synthetic dataset with anomalies for submission.

Runs the full pipeline and writes:
- Baseline CSV/JSON files for all entities
- Anomaly-injected versions with ground truth labels
- Validation summary from validate_dataset.py
- Source manifest with SHA-256 checksums

Usage (from repo root):
    DATA_SCALE=starter python scripts/export_pipeline_data.py
    DATA_SCALE=full python scripts/export_pipeline_data.py

Outputs to sample_output/{scale}/:
- baseline/*.csv (clean baseline data)
- injected/*.csv (data with anomalies)
- ground_truth.csv (anomaly labels)
- validation_summary.json
- source_manifest.json
- checksums.sha256
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import pathlib
import sys

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
from backend.app.generators.anomaly_injector import inject_anomalies
from backend.app.validation.validate_dataset import validate_dataset

# Output directories
OUT_DIR = ROOT / "sample_output" / DATA_SCALE
BASELINE_DIR = OUT_DIR / "baseline"
INJECTED_DIR = OUT_DIR / "injected"

OUT_DIR.mkdir(parents=True, exist_ok=True)
BASELINE_DIR.mkdir(parents=True, exist_ok=True)
INJECTED_DIR.mkdir(parents=True, exist_ok=True)


def file_sha256(path: pathlib.Path) -> str:
    sha = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(8192):
            sha.update(chunk)
    return sha.hexdigest()


def write_csv_json(df: pd.DataFrame, name: str, target_dir: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path]:
    csv_path = target_dir / f"{name}.csv"
    json_path = target_dir / f"{name}.json"
    df.to_csv(csv_path, index=False)
    df.to_json(json_path, orient="records", indent=2, date_format="iso")
    size_kb = csv_path.stat().st_size / 1024
    print(f"  ✓ {name:30s} {len(df):>6,} rows  {size_kb:>8.1f} KB")
    return csv_path, json_path


def main() -> None:
    print(f"\n{'='*70}")
    print("SYNTHETIC DATA EXPORT PIPELINE")
    print(f"{'='*70}\n")
    print(f"Seed: {SEED}")
    print(f"Scale: {DATA_SCALE}")
    print(f"Volumes: {SCALES[DATA_SCALE]}\n")
    
    # Step 1: Generate baseline
    print("=" * 70)
    print("STEP 1: Generate Baseline Data")
    print("=" * 70)
    master = generate_master_data(DATA_SCALE)
    rng_routes = np.random.default_rng(SEED)
    routes_df, route_stops_df = generate_routes(
        master["buses"], master["drivers"], master["stops"], master["students"], rng_routes
    )
    rng_asn = np.random.default_rng(SEED)
    assign_result = assign_all_students(master, routes_df, route_stops_df, rng_asn)
    assignments_df = assign_result["assignments"]
    cap_history = build_capacity_history(master["buses"])
    rng_att = np.random.default_rng(SEED)
    att_df, disr_df = generate_attendance(
        assignments_df, master["students"], routes_df, master["buses"], scale=DATA_SCALE, rng=rng_att
    )
    rng_not = np.random.default_rng(SEED)
    notif_df, _ = generate_notifications(att_df, master["students"], master["guardian_contacts"], rng=rng_not)
    
    baseline = {
        **master,
        "routes": routes_df,
        "route_stops": route_stops_df,
        "assignments": assignments_df,
        "attendance_events": att_df,
        "notifications": notif_df,
    }
    
    # Step 2: Inject anomalies
    print("\n" + "=" * 70)
    print("STEP 2: Inject Anomalies")
    print("=" * 70)
    rng_anom = np.random.default_rng(SEED)
    injected, ground_truth = inject_anomalies(baseline, rng_anom)
    print(f"  Injected {len(ground_truth)} anomalies across {ground_truth['issue_type'].nunique()} types")
    
    # Step 3: Write baseline
    print("\n" + "=" * 70)
    print("STEP 3: Write Baseline CSVs and JSON")
    print("=" * 70)
    written_files = []
    for name, df in baseline.items():
        csv, json_f = write_csv_json(df, name, BASELINE_DIR)
        written_files.extend([csv, json_f])
    
    # Step 4: Write injected
    print("\n" + "=" * 70)
    print("STEP 4: Write Injected CSVs and JSON")
    print("=" * 70)
    for name, df in injected.items():
        csv, json_f = write_csv_json(df, name, INJECTED_DIR)
        written_files.extend([csv, json_f])
    
    # Step 5: Write ground truth
    print("\n" + "=" * 70)
    print("STEP 5: Write Ground Truth")
    print("=" * 70)
    gt_csv = OUT_DIR / "ground_truth.csv"
    gt_json = OUT_DIR / "ground_truth.json"
    ground_truth.to_csv(gt_csv, index=False)
    ground_truth.to_json(gt_json, orient="records", indent=2)
    written_files.extend([gt_csv, gt_json])
    print(f"  ✓ ground_truth.csv/json  {len(ground_truth)} anomalies")
    
    # Step 6: Validation
    print("\n" + "=" * 70)
    print("STEP 6: Run Validation")
    print("=" * 70)
    violations = validate_dataset(injected)
    validation = {
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
        "seed": SEED,
        "scale": DATA_SCALE,
        "baseline_row_counts": {k: len(v) for k, v in baseline.items()},
        "injected_row_counts": {k: len(v) for k, v in injected.items()},
        "anomaly_counts": ground_truth["issue_type"].value_counts().to_dict(),
        "total_anomalies": len(ground_truth),
        "validation_violations": len(violations),
    }
    val_path = OUT_DIR / "validation_summary.json"
    with open(val_path, "w") as f:
        json.dump(validation, f, indent=2)
    written_files.append(val_path)
    print(f"  ✓ validation_summary.json  {len(violations)} violations found in injected data")
    
    # Step 7: Manifest
    print("\n" + "=" * 70)
    print("STEP 7: Write Manifest and Checksums")
    print("=" * 70)
    manifest = {
        "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
        "seed": SEED,
        "scale": DATA_SCALE,
        "files": []
    }
    checksums = []
    for path in written_files:
        rel = path.relative_to(OUT_DIR)
        sha = file_sha256(path)
        manifest["files"].append({
            "path": str(rel).replace("\\", "/"),
            "size_bytes": path.stat().st_size,
            "sha256": sha
        })
        checksums.append(f"{sha}  {rel}")
    
    manifest_path = OUT_DIR / "source_manifest.json"
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)
    
    checksum_path = OUT_DIR / "checksums.sha256"
    with open(checksum_path, "w") as f:
        f.write("\n".join(checksums))
    
    print(f"  ✓ source_manifest.json")
    print(f"  ✓ checksums.sha256")
    
    print("\n" + "=" * 70)
    print("EXPORT COMPLETE")
    print("=" * 70)
    print(f"\nOutput: {OUT_DIR}")
    print(f"Files: {len(written_files) + 2}")


if __name__ == "__main__":
    main()

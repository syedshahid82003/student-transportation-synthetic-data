# Student Transportation Synthetic Data Generator

Synthetic data pipeline for school bus routing: assigns students to routes/stops respecting capacity, pickup windows, safety, and attendance patterns.

## Quick Start

```bash
cd backend
python -m venv venv
venv\Scripts\activate  # Windows
pip install -r requirements.txt
cd ..
python -m pytest backend/tests/ -q
```

## Generate Data

```bash
# Starter scale (fast: 500 students, 20 buses, 20 school days)
$env:DATA_SCALE='starter'; python scripts/export_pipeline_data.py

# Full scale (slow: 5k students, 100 buses, 200 school days)
$env:DATA_SCALE='full'; python scripts/export_pipeline_data.py
```

Outputs to `sample_output/{scale}/`:
- `baseline/` — clean CSV + JSON for 11 entities
- `injected/` — same data with 35 anomalies injected
- `ground_truth.csv` — labels for all 35 anomalies (5 types)
- `validation_summary.json` — row counts and anomaly breakdown
- `source_manifest.json` + `checksums.sha256`

## Run Tests

```bash
# Fast: starter scale only (167 tests, ~20 seconds)
python -m pytest backend/tests/ -k "not full" --tb=short -q

# Slow: all tests including full scale (233 tests, ~3 minutes)
python -m pytest backend/tests/ --tb=short -q
```

## Entities

11 core: Student, GuardianContact, AddressZone, Stop, Bus, Driver, Route, RouteStop, Assignment, AttendanceEvent, Notification

Auxiliary: BusCapacityHistory, Disruption, RejectedAssignment, SkippedNotification

See `docs/data_dictionary.md` and `docs/erd.md`.

## Reproducibility

**Seed:** `20261022`

All generators use `numpy.random.default_rng(20261022)`. Same seed + scale = byte-identical output.

```bash
python scripts/reproducibility.py
```

## Edge Cases (5 types, 35 instances at starter scale)

1. **bus_capacity_exceeded** — route has more active assignments than bus capacity
2. **incompatible_accessibility_route** — accessible student assigned to non-accessible bus  
3. **impossible_sequential_travel_time** — consecutive stops too far apart for pickup window
4. **notification_to_invalid_contact** — notification sent to contact with opted-out preferences
5. **unapproved_stop_exposed** — "unapproved address" modeled as stop with `is_approved=False`

All anomalies are in `ground_truth.csv` with `issue_type`, `severity`, and `expected_decision`.

## Sample Output

Starter-scale export committed to `sample_output/starter/` (baseline + injected + ground truth).

Full-scale too large for git. Generate locally: `DATA_SCALE=full python scripts/export_pipeline_data.py`

## What's Missing

- **SQL export:** Step 9 lists CSV/JSON/SQL; only CSV/JSON implemented
- **FastAPI routes:** Stub directories exist but no runtime API  
- **MongoDB integration:** Validators documented but not deployed

Deferred to Phase 2.

## Data Provenance

Fully synthetic. No real PII. Names from fictional word-lists. Phones: 555-01xx. Emails: @example.com.

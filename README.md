# Student Transportation Synthetic Data Generator

Synthetic data pipeline for school bus routing: assigns students to routes/stops respecting capacity, pickup windows, safety, and attendance patterns.

## Quick Start

```powershell
cd backend
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
cd ..
python -m pytest backend/tests/ -q
```

On Linux or macOS, activate the environment with `source venv/bin/activate`.

## Generate Data

```powershell
# Starter scale (fast: 500 students, 20 buses, 20 school days)
$env:DATA_SCALE='starter'; python scripts/export_pipeline_data.py

# Full scale (slow: 5k students, 100 buses, 200 school days)
$env:DATA_SCALE='full'; python scripts/export_pipeline_data.py
```

On Linux or macOS:

```bash
DATA_SCALE=starter python scripts/export_pipeline_data.py
DATA_SCALE=full python scripts/export_pipeline_data.py
```

Outputs to `sample_output/{scale}/`:
- `baseline/` — clean CSV + JSON for 11 entities (attendance is CSV-only)
- `injected/` — same data with anomalies injected (attendance is CSV-only)
- `ground_truth.csv` — labels for all 35 anomalies (5 types)
- `validation_summary.json` — baseline violations, detected violations, and per-issue precision/recall against ground truth
- `source_manifest.json` + `checksums.sha256`

## Run Tests

```bash
# Fast: starter-scale tests (~20 seconds)
python -m pytest backend/tests/ -k "not full" --tb=short -q

# Slow: all tests including full scale (233 tests, ~3 minutes)
python -m pytest backend/tests/ --tb=short -q
```

The fast command selects 167 starter-scale tests; 66 full-scale tests are deselected with `-k 'not full'`.

## Entities

11 core: Student, GuardianContact, AddressZone, Stop, Bus, Driver, Route, RouteStop, Assignment, AttendanceEvent, Notification

Auxiliary: BusCapacityHistory, Disruption, RejectedAssignment, SkippedNotification

See `docs/data_dictionary.md` and `docs/erd.md`.

## Reproducibility

**Seed:** `20261022`

All generators use numpy.random.default_rng(20261022). For the same seed and scale,
the entity data files, ground truth, source_manifest.json, validation_summary.json and
checksums.sha256 are identical across runs (verified at starter scale by running the
export twice and comparing checksums.sha256).

```bash
python scripts/reproducibility.py
```

The reproducibility script compares baseline entity tables only; it defaults to starter scale and also accepts `DATA_SCALE=full`.

## Edge Cases (5 types, 35 instances at starter scale)

1. **bus_capacity_exceeded** — route has more active assignments than bus capacity
2. **incompatible_accessibility_route** — accessible student assigned to non-accessible bus  
3. **impossible_sequential_travel_time** — consecutive stops too far apart for pickup window
4. **notification_to_invalid_contact** — notification sent to a contact whose `contact_status` is `INVALID` or `BOUNCED` and whose `is_valid` is false
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

## Dashboard (starter scale)

The dashboard reads generated JSON from frontend/public/data/, which is not committed.

    python scripts/export_frontend_data.py
    cd frontend
    npm install
    npm run dev

Notes:
- Shows starter scale (500 students, 20 buses, 20 school days).
- The anomaly page is a read-only placeholder with no access control.
  Ground truth is in sample_output/starter/ground_truth.csv and .json.
- Architecture is file-based by design: generators write CSV/JSON, the dashboard
  reads exported JSON. FastAPI and MongoDB loading are out of scope.

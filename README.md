# Student Transportation Synthetic Data Generator

End-to-end synthetic data pipeline for a school bus routing system.
Assigns students to routes/stops respecting capacity, pickup windows, safety.

## Quick start

    cd backend
    python -m venv venv
    venv\Scripts\activate
    pip install -r requirements.txt
    cd ..
    python -m pytest backend/tests/ -q

## Generate data

    python scripts/export_frontend_data.py     # frontend JSON (starter)
    python scripts/export_pipeline_data.py     # CSVs + ground truth + manifest
    python scripts/reproducibility.py          # reproducibility report

## Frontend dashboard

    cd frontend
    npm install
    npm start                      # dev server http://localhost:5173
    npm run build                  # production -> frontend/dist/

## Entities

Student, GuardianContact, AddressZone, Stop, Bus, Driver, Route, RouteStop,
Assignment, AttendanceEvent, Notification (+ audit_events, bus_capacity_history).
See docs/data_dictionary.md and docs/erd.md.

## ID formats

| Entity | Format | Example |
|---|---|---|
| Student | STU-000001 | STU-000042 |
| Stop | STOP-000001 | STOP-000015 |
| Bus | BUS-000001 | BUS-000002 |
| Route | ROUTE-2026-000001 | ROUTE-2026-000008 |
| Assignment | ASN-STU-000001-2026 | ASN-STU-000042-2026 |
| Notification | NOT-2026-000001 | NOT-2026-000099 |

## Seed and reproducibility

All generators: numpy.random.default_rng(20261022). No default state.
Same seed + scale = byte-identical output (SHA-256 verified per table).
Run python scripts/reproducibility.py to confirm.

## Volumes (full scale)

| Entity | Count |
|---|---|
| Students | 5000 |
| Buses | 100 |
| Stops | 300 |
| School days | 200 |
| Active assignments | 4065 |
| Attendance events | 813000 |
| Notifications sent | 53059 |
| Anomaly edge cases | 150-250 (30-50 per type x 5 types) |

## Key design decisions

| Decision | Rationale |
|---|---|
| Seed 20261022 | Passed explicitly to every numpy.default_rng(). No default state. |
| Parent-before-child | zones->stops->buses->drivers->students->guardians->routes->assignments->attendance->notifications |
| Append-only history | effective_from/effective_to versioning; history tables never overwritten |
| Separate ground truth | anomaly_injector deep-copies tables; labels never in entity columns |
| Deterministic delivery | sha256(notification_id) % 100 < 85 -- no RNG, reproduces without seed |
| Lazy attendance | generate_attendance_day() yields one day at a time |
| event_type mapping | late_pickup used for capacity-reduced events (validator has no CAPACITY_REDUCED type) |

## Data provenance

Fully synthetic. No real PII. Names from fictional word-lists.
Phones: 555-01xx (non-geographic). Emails: @example.com. No external datasets.

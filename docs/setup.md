# Student Transportation System — Developer Guide

## Setup

### Prerequisites

- Python 3.12+
- MongoDB 7+ running locally (or a reachable URI)
- `pip install pymongo python-dotenv`

### 1. Configure environment

Copy the example env file and edit it if needed:

```bash
cp backend/.env.example backend/.env
```

The defaults work for a local MongoDB instance with no authentication:

```
MONGO_URI=mongodb://localhost:27017
DB_NAME=transport
```

### 2. Create collections and apply JSON Schema validators

Run from the **repo root**:

```bash
python database/scripts/setup_db.py
```

This script is **idempotent** — safe to re-run at any time. It will:

- Create all 13 collections if they do not already exist.
- Apply (or refresh) the `$jsonSchema` validator from `database/validators/<collection>.json` to each collection.
- Print a line per collection showing whether it was created or updated.
- Exit with code `1` if the MongoDB server is unreachable.

### 3. Create indexes

Run from the **repo root**:

```bash
python database/indexes/indexes.py
```

Also idempotent. It will:

- Create all unique and secondary indexes defined in `database/indexes/indexes.py`.
- Skip indexes that already exist with compatible definitions.
- Exit with code `1` if any index creation fails with an unexpected error.

### 4. Typical first-time flow

```bash
# From repo root
python database/scripts/setup_db.py
python database/indexes/indexes.py
```

---

## Collections

| Collection | Purpose |
|---|---|
| `students` | Enrolled students |
| `guardian_contacts` | Parents / guardians |
| `address_zones` | Geographic school zones |
| `stops` | Physical bus stop locations |
| `buses` | Fleet inventory |
| `drivers` | Drivers assigned to routes |
| `routes` | Individual bus runs |
| `route_stops` | Route ↔ Stop N:M bridge |
| `assignments` | Student ↔ Route ↔ Stop per academic year |
| `attendance_events` | Immutable per-day stop events |
| `notifications` | Outbound guardian notifications |
| `audit_events` | Append-only write audit trail |
| `bus_capacity_history` | Append-only bus capacity changelog |

See [`data_dictionary.md`](data_dictionary.md) for full field-level documentation.

---

## ID Formats

| Entity | Format | Example |
|---|---|---|
| Student | `STU-000001` | `STU-000042` |
| Guardian | `GRD-000001` | `GRD-000007` |
| Zone | `ZONE-0001` | `ZONE-0003` |
| Stop | `STOP-000001` | `STOP-000015` |
| Bus | `BUS-000001` | `BUS-000002` |
| Driver | `DRV-000001` | `DRV-000011` |
| Route | `ROUTE-2026-000001` | `ROUTE-2026-000008` |
| Route-Stop | `RS-ROUTE-2026-000001-STOP-000003-0002` | — |
| Assignment | `ASN-STU-000001-2026` | `ASN-STU-000042-2026` |
| Attendance | `ATT-20261022-STU-000001-boarded` | — |
| Notification | `NOT-2026-000001` | `NOT-2026-000099` |
| Audit | `AUD-20261022143000-a1b2c3d4` | — |
| Bus Capacity History | `BCH-BUS-000001-20261022` | — |

---

## Key Rules

- **Seed `20261022`** must be passed to every random generator call. Never rely on default random state.
- **`data/ground_truth/`** is read-only. No application code may write to it.
- **History is immutable.** Use `effective_from / effective_to` versioning; never overwrite payload fields.
- **Referential integrity** must be validated before every insert or update that references another collection. The validator lives in `backend/app/validators/`.

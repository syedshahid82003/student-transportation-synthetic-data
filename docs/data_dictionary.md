# Data Dictionary — Student Transportation System

This document describes the MongoDB collection validators in
`database/validators/*.json` and the unique indexes declared in
`database/indexes/indexes.py`. The 11 core entities are followed by two
supporting history collections (`audit_events` and `bus_capacity_history`).

MongoDB's `_id` field is the primary key (PK) in every collection. All
validators set `additionalProperties: true`: fields not listed here are not
rejected by JSON Schema validation. A validator's required-field list and
field constraints are the source of truth for requiredness and validation.

## Conventions

- **Required** means listed in the collection validator's `required` array.
  Other declared fields are optional; nullable fields explicitly allow `null`.
- **FK** identifies a logical reference by ID format. JSON Schema validates
  the value's type and pattern, not that the referenced document exists.
  Referential integrity must be checked by the application.
- **Unique** reflects MongoDB's `_id` constraint or an explicit unique index
  in `database/indexes/indexes.py`. A pattern or ID convention alone does not
  make a field or combination unique.
- **Date** is a BSON date (UTC instant); a field described as a calendar date
  uses UTC midnight. HH:MM values are strings in local time.
- **Units** are specified where meaningful: coordinates are decimal degrees,
  travel time is minutes, capacities are student passengers, and lengths are
  characters unless noted.
- Unless stated otherwise, a string without a pattern or enum has no
  validator-defined allowed values beyond its stated length constraints.

## ID formats

These are the validator patterns and representative formats for all entities.
The pattern is the validation rule; uniqueness is provided by MongoDB `_id`.

| Entity | `_id` format / pattern |
|---|---|
| `students` | `STU-000001` (`^STU-[0-9]{6}$`) |
| `guardian_contacts` | `GRD-000001` (`^GRD-[0-9]{6}$`) |
| `address_zones` | `ZONE-0001` (`^ZONE-[0-9]{4}$`) |
| `stops` | `STOP-000001` (`^STOP-[0-9]{6}$`) |
| `buses` | `BUS-000001` (`^BUS-[0-9]{6}$`) |
| `drivers` | `DRV-000001` (`^DRV-[0-9]{6}$`) |
| `routes` | `ROUTE-2026-000001` (`^ROUTE-[0-9]{4}-[0-9]{6}$`) |
| `route_stops` | `RS-ROUTE-2026-000001-STOP-000003-0002` (`^RS-[A-Z0-9-]+-[0-9]{4}$`) |
| `assignments` | `ASN-<student-id>-2026`, e.g. `ASN-STU-000001-2026` (`^ASN-STU-[0-9]{6}-[0-9]{4}$`) |
| `attendance_events` | `ATT-YYYYMMDD-STU-######-type`, e.g. `ATT-20261022-STU-000001-boarded` (`^ATT-[0-9]{8}-STU-[0-9]{6}-[a-z_]+$`) |
| `notifications` | `NOT-2026-000001` (`^NOT-[0-9]{4}-[0-9]{6}$`) |
| `audit_events` | `AUD-20261022143000-a1b2c3d4` (`^AUD-[0-9]{14}-[A-Za-z0-9]{8}$`) |
| `bus_capacity_history` | `BCH-BUS-000001-20261022` (`^BCH-BUS-[0-9]{6}-[0-9]{8}$`) |

## 1. `students` — core entity

**PK:** `_id` (`STU-` plus six digits). **Purpose:** Student profile and current
record version.

| Field | BSON type | Req. | FK / unique | Allowed values, units, and validator rule |
|---|---|---:|---|---|
| `_id` | string | Yes | PK; unique | `^STU-[0-9]{6}$` |
| `first_name` | string | Yes | — | 1–100 characters |
| `last_name` | string | Yes | — | 1–100 characters |
| `date_of_birth` | date | Yes | — | UTC date |
| `grade` | int | Yes | — | 0–12; 0 = Kindergarten |
| `zone_id` | string | Yes | FK → `address_zones._id` | `^ZONE-[0-9]{4}$` |
| `home_address` | object | No | — | Optional nested object; declared subfields below |
| `home_address.street` | string | No | — | No additional constraint |
| `home_address.city` | string | No | — | No additional constraint |
| `home_address.state` | string | No | — | Exactly 2 characters |
| `home_address.zip` | string | No | — | `^[0-9]{5}$` |
| `home_address.lat` | double | No | — | No range constraint; decimal degrees |
| `home_address.lng` | double | No | — | No range constraint; decimal degrees |
| `guardian_ids` | array of string | No | FK[] → `guardian_contacts._id` | Each item matches `^GRD-[0-9]{6}$` |
| `accessibility_required` | bool | Yes | — | `true` or `false` |
| `accessibility_notes` | string | No | — | Maximum 500 characters |
| `status` | string | Yes | — | `active`, `inactive`, `suspended`, `transferred` |
| `effective_from` | date | Yes | — | Start of this record's validity |
| `effective_to` | date or null | No | — | End of validity; `null` permitted |
| `created_at` | date | Yes | — | BSON date |
| `updated_at` | date | No | — | BSON date |

**Other uniqueness:** None beyond `_id`. **Cardinality:** Many students belong
to one zone (N:1); students and guardians are N:M through `guardian_ids`.
**Effective dates:** `effective_from` required; `effective_to` optional and
nullable. **Lifecycle:** `active`, `inactive`, `suspended`, `transferred`;
the validator defines the states, not transition rules.

## 2. `guardian_contacts` — core entity

**PK:** `_id` (`GRD-` plus six digits). **Purpose:** Guardian/contact records.

| Field | BSON type | Req. | FK / unique | Allowed values, units, and validator rule |
|---|---|---:|---|---|
| `_id` | string | Yes | PK; unique | `^GRD-[0-9]{6}$` |
| `first_name` | string | Yes | — | 1–100 characters |
| `last_name` | string | Yes | — | 1–100 characters |
| `relationship` | string | Yes | — | `parent`, `legal_guardian`, `emergency_contact`, `other` |
| `phone_primary` | string | Yes | — | 1–30 characters; no phone-format rule |
| `phone_secondary` | string | No | — | 1–30 characters; no phone-format rule |
| `email` | string | No | — | 1–254 characters; no email-format rule |
| `contact_status` | string | Yes | — | `VALID`, `INVALID`, `BOUNCED` |
| `is_valid` | bool | Yes | — | `true` or `false` |
| `notification_preferences` | array of string | No | — | Each item: `sms`, `email`, `push`, `none` |
| `created_at` | date | Yes | — | BSON date |
| `updated_at` | date | No | — | BSON date |

**Other uniqueness:** No unique phone or email index; duplicate and malformed
contact values are permitted. **Cardinality:** Guardians and students are N:M
through `students.guardian_ids`; a guardian may have zero or more notification
records (1:N). **Effective dates:** None. **Lifecycle/contact states:**
`VALID`, `INVALID`, `BOUNCED`; `is_valid` is a separate required boolean.

## 3. `address_zones` — core entity

**PK:** `_id` (`ZONE-` plus four digits). **Purpose:** Geographic school zones.

| Field | BSON type | Req. | FK / unique | Allowed values, units, and validator rule |
|---|---|---:|---|---|
| `_id` | string | Yes | PK; unique | `^ZONE-[0-9]{4}$` |
| `name` | string | Yes | Unique index | 1–100 characters; unique across collection |
| `zone_type` | string | Yes | — | `elementary`, `middle`, `high`, `mixed`, `special_education` |
| `boundary_geojson` | object | No | — | Described as GeoJSON Polygon; validator checks object only |
| `school_ids` | array of string | No | — | Each item is a string; no pattern |
| `notes` | string | No | — | Maximum 500 characters |
| `created_at` | date | Yes | — | BSON date |
| `updated_at` | date | No | — | BSON date |

**Other uniqueness:** `name` has the explicit unique index `zones_name_unique`.
**Cardinality:** One zone may contain many students and stops (1:N for each);
each student and stop has one required `zone_id`. **Effective dates:** None.
**Lifecycle:** No lifecycle field or states.

## 4. `stops` — core entity

**PK:** `_id` (`STOP-` plus six digits). **Purpose:** Approved or prospective
physical pickup/dropoff locations.

| Field | BSON type | Req. | FK / unique | Allowed values, units, and validator rule |
|---|---|---:|---|---|
| `_id` | string | Yes | PK; unique | `^STOP-[0-9]{6}$` |
| `name` | string | Yes | — | 1–150 characters |
| `lat` | double | Yes | — | -90 to 90 decimal degrees |
| `lng` | double | Yes | — | -180 to 180 decimal degrees |
| `street_address` | string | No | — | Maximum 200 characters |
| `zone_id` | string | Yes | FK → `address_zones._id` | `^ZONE-[0-9]{4}$` |
| `is_approved` | bool | Yes | — | `true` or `false` |
| `is_accessible` | bool | No | — | `true` or `false` |
| `status` | string | Yes | — | `active`, `inactive`, `pending_approval`, `retired` |
| `notes` | string | No | — | Maximum 500 characters |
| `created_at` | date | Yes | — | BSON date |
| `updated_at` | date | No | — | BSON date |

**Other uniqueness:** None beyond `_id`. **Cardinality:** One zone has many
stops (1:N); a stop may be linked to many routes through `route_stops` (N:M).
**Effective dates:** None. **Lifecycle:** `active`, `inactive`,
`pending_approval`, `retired`; approval is tracked separately by
`is_approved`.

## 5. `buses` — core entity

**PK:** `_id` (`BUS-` plus six digits). **Purpose:** Fleet and current capacity.

| Field | BSON type | Req. | FK / unique | Allowed values, units, and validator rule |
|---|---|---:|---|---|
| `_id` | string | Yes | PK; unique | `^BUS-[0-9]{6}$` |
| `license_plate` | string | Yes | Unique index | 2–10 characters; unique across collection |
| `make` | string | No | — | Maximum 50 characters |
| `model` | string | No | — | Maximum 50 characters |
| `year` | int | No | — | 1990–2100 |
| `capacity` | int | Yes | — | 1–100 student passengers |
| `is_accessible` | bool | Yes | — | `true` or `false` |
| `status` | string | Yes | — | `active`, `inactive`, `maintenance`, `retired` |
| `effective_from` | date | Yes | — | Start of this record's validity |
| `effective_to` | date or null | No | — | End of validity; `null` permitted |
| `created_at` | date | Yes | — | BSON date |
| `updated_at` | date | No | — | BSON date |

**Other uniqueness:** `license_plate` has the explicit unique index
`buses_plate_unique`. **Cardinality:** One bus may be used by many routes and
have many capacity-history records (1:N); every route/history record refers to
one bus. **Effective dates:** `effective_from` required; `effective_to`
optional and nullable. Capacity changes are additionally represented in
`bus_capacity_history`. **Lifecycle:** `active`, `inactive`, `maintenance`,
`retired`.

## 6. `drivers` — core entity

**PK:** `_id` (`DRV-` plus six digits). **Purpose:** Driver profile and license.

| Field | BSON type | Req. | FK / unique | Allowed values, units, and validator rule |
|---|---|---:|---|---|
| `_id` | string | Yes | PK; unique | `^DRV-[0-9]{6}$` |
| `first_name` | string | Yes | — | 1–100 characters |
| `last_name` | string | Yes | — | 1–100 characters |
| `license_number` | string | Yes | Unique index | 5–20 characters; unique across collection |
| `license_class` | string | Yes | — | `A`, `B`, `C` |
| `license_expiry` | date | No | — | BSON date; no future-date constraint in validator |
| `phone` | string | No | — | `^[0-9]{10}$` |
| `status` | string | Yes | — | `active`, `inactive`, `on_leave`, `terminated` |
| `created_at` | date | Yes | — | BSON date |
| `updated_at` | date | No | — | BSON date |

**Other uniqueness:** `license_number` has the explicit unique index
`drivers_license_unique`. **Cardinality:** One driver may be assigned to many
routes (1:N); each route has one required driver. **Effective dates:** No
effective-date fields. **Lifecycle:** `active`, `inactive`, `on_leave`,
`terminated`.

## 7. `routes` — core entity

**PK:** `_id` (`ROUTE-` + four-digit year + six digits). **Purpose:** Scheduled
bus run with driver, bus, direction, and time window.

| Field | BSON type | Req. | FK / unique | Allowed values, units, and validator rule |
|---|---|---:|---|---|
| `_id` | string | Yes | PK; unique | `^ROUTE-[0-9]{4}-[0-9]{6}$` |
| `name` | string | No | — | 1–150 characters |
| `bus_id` | string | Yes | FK → `buses._id` | `^BUS-[0-9]{6}$` |
| `driver_id` | string | Yes | FK → `drivers._id` | `^DRV-[0-9]{6}$` |
| `direction` | string | Yes | — | `am`, `pm`, `midday` |
| `status` | string | Yes | — | `active`, `inactive`, `cancelled`, `completed` |
| `pickup_window_start` | string | Yes | — | `HH:MM`, 00:00–23:59 local time |
| `pickup_window_end` | string | Yes | — | `HH:MM`, 00:00–23:59 local time |
| `academic_year` | int | No | — | 2000–2100 |
| `effective_from` | date | Yes | — | Start of this record's validity |
| `effective_to` | date or null | No | — | End of validity; `null` permitted |
| `notes` | string | No | — | Maximum 500 characters |
| `created_at` | date | Yes | — | BSON date |
| `updated_at` | date | No | — | BSON date |

**Other uniqueness:** None beyond `_id`. **Cardinality:** Each route uses one
bus and one driver; each bus/driver can be referenced by many routes (N:1 /
1:N). Routes and stops are N:M through `route_stops`; a route may have many
assignments (1:N). **Effective dates:** `effective_from` required;
`effective_to` optional and nullable. **Lifecycle:** `active`, `inactive`,
`cancelled`, `completed`.

## 8. `route_stops` — core bridge entity

**PK:** `_id` (`RS-` + route/stop identifier content + four-digit suffix).
**Purpose:** Ordered route-to-stop association.

| Field | BSON type | Req. | FK / unique | Allowed values, units, and validator rule |
|---|---|---:|---|---|
| `_id` | string | Yes | PK; unique | `^RS-[A-Z0-9-]+-[0-9]{4}$` |
| `route_id` | string | Yes | FK → `routes._id` | `^ROUTE-[0-9]{4}-[0-9]{6}$` |
| `stop_id` | string | Yes | FK → `stops._id` | `^STOP-[0-9]{6}$` |
| `sequence` | int | Yes | Unique with `route_id` | Minimum 1; 1-based route order |
| `travel_minutes_from_prev` | int or null | No | — | 0–240 minutes when integer; `null` permitted |
| `scheduled_time` | string | No | — | `HH:MM` (00:00–23:59) |
| `created_at` | date | Yes | — | BSON date |
| `updated_at` | date | No | — | BSON date |

**Other uniqueness:** Explicit unique indexes on `(route_id, sequence)` and
`(route_id, stop_id)`. **Cardinality:** Routes and stops are N:M, implemented
as one route-to-many bridge rows and one stop-to-many bridge rows (1:N on
each side). **Effective dates:** None. **Lifecycle:** No lifecycle field or
states.

## 9. `assignments` — core entity

**PK:** `_id` (`ASN-STU-` + six digits + four-digit year). **Purpose:** Student
route/stop assignment.

| Field | BSON type | Req. | FK / unique | Allowed values, units, and validator rule |
|---|---|---:|---|---|
| `_id` | string | Yes | PK; unique | `^ASN-STU-[0-9]{6}-[0-9]{4}$` |
| `student_id` | string | Yes | FK → `students._id` | `^STU-[0-9]{6}$` |
| `route_id` | string | Yes | FK → `routes._id` | `^ROUTE-[0-9]{4}-[0-9]{6}$` |
| `stop_id` | string | Yes | FK → `stops._id` | `^STOP-[0-9]{6}$` |
| `status` | string | Yes | — | `active`, `inactive`, `pending`, `cancelled` |
| `effective_from` | date | Yes | — | Start of this assignment's validity |
| `effective_to` | date or null | No | — | End of validity; `null` permitted |
| `academic_year` | int | No | — | 2000–2100 |
| `notes` | string | No | — | Maximum 500 characters |
| `created_at` | date | Yes | — | BSON date |
| `updated_at` | date | No | — | BSON date |

**Other uniqueness:** No unique secondary index. The ID pattern encodes a
student and year, but the validator does not require `academic_year` or enforce
that it agrees with the ID. **Cardinality:** Each assignment refers to one
student, route, and stop (N:1 from assignments to each); each of those may
have many assignments (1:N). A student may also have many assignments across
years. **Effective dates:** `effective_from` required; `effective_to`
optional and nullable. **Lifecycle:** `active`, `inactive`, `pending`,
`cancelled`.

## 10. `attendance_events` — core entity

**PK:** `_id` (`ATT-` + eight-digit date + student ID + event type). **Purpose:**
Per-assignment event log.

| Field | BSON type | Req. | FK / unique | Allowed values, units, and validator rule |
|---|---|---:|---|---|
| `_id` | string | Yes | PK; unique | `^ATT-[0-9]{8}-STU-[0-9]{6}-[a-z_]+$` |
| `assignment_id` | string | Yes | FK → `assignments._id` | `^ASN-STU-[0-9]{6}-[0-9]{4}$` |
| `student_id` | string | Yes | Logical FK → `students._id` | `^STU-[0-9]{6}$`; denormalized |
| `route_id` | string | Yes | Logical FK → `routes._id` | `^ROUTE-[0-9]{4}-[0-9]{6}$`; denormalized |
| `stop_id` | string | Yes | Logical FK → `stops._id` | `^STOP-[0-9]{6}$`; denormalized |
| `date` | date | Yes | — | Calendar date at UTC midnight |
| `event_type` | string | Yes | Unique with assignment/date | `boarded`, `alighted`, `no_show`, `absent`, `late_pickup`, `emergency_exit` |
| `recorded_at` | date | No | — | BSON date (UTC timestamp) |
| `recorded_by` | string | No | — | No pattern; driver or system identifier by convention |
| `notes` | string | No | — | Maximum 500 characters |
| `created_at` | date | Yes | — | BSON date |

**Other uniqueness:** Explicit unique index on
`(assignment_id, date, event_type)`; one event of a given type per assignment
per date. **Cardinality:** One assignment may have many attendance events
(1:N); each event refers to one assignment. Student, route, and stop IDs are
also required denormalized references (each may appear in many events, 1:N).
**Effective dates:** No effective-date fields; `date` is the event day.
**Lifecycle:** No lifecycle field; `event_type` is an event classification,
not a state.

### Enum mapping

Normalize upstream attendance codes to values accepted by the
`attendance_events.event_type` validator:

| Upstream value | Stored validator value | Why |
|---|---|---|
| `PRESENT` | `boarded` | `PRESENT` is not in the validator enum; `boarded` is the accepted boarding/present value. |
| `ABSENT` | `absent` | `absent` is already an allowed validator value. |
| `MISSED_PICKUP` | `no_show` | `MISSED_PICKUP` is not in the enum; `no_show` is the accepted missed-pickup equivalent. |
| `CAPACITY_REDUCED` | `late_pickup` | `CAPACITY_REDUCED` is not an allowed validator value; `late_pickup` is used because the validator has no capacity-reduced event type. |

These are normalization mappings, not additional enum values. The validator
rejects an `event_type` outside its declared six-value enum. On a
capacity-reduced day, the affected assignment's event is `late_pickup` instead
of `boarded`; the assignment is kept, not removed. The event notes carry
`capacity_reduced` to distinguish this validator-limited mapping from an
ordinary late pickup.

## 11. `notifications` — core entity

**PK:** `_id` (`NOT-` + four-digit year + six digits). **Purpose:** Outbound
guardian delivery record.

| Field | BSON type | Req. | FK / unique | Allowed values, units, and validator rule |
|---|---|---:|---|---|
| `_id` | string | Yes | PK; unique | `^NOT-[0-9]{4}-[0-9]{6}$` |
| `guardian_id` | string | Yes | FK → `guardian_contacts._id` | `^GRD-[0-9]{6}$` |
| `student_id` | string | Yes | Logical FK → `students._id` | `^STU-[0-9]{6}$`; denormalized |
| `event_id` | string | Yes | Polymorphic FK | String; target collection is `event_collection` |
| `event_collection` | string | Yes | — | `attendance_events`, `assignments`, `routes` |
| `channel` | string | Yes | — | `sms`, `email`, `push` |
| `status` | string | Yes | — | `pending`, `sent`, `delivered`, `failed`, `cancelled` |
| `sent_at` | date or null | No | — | BSON date or `null` |
| `delivered_at` | date or null | No | — | BSON date or `null` |
| `failed_at` | date or null | No | — | BSON date or `null` |
| `failure_reason` | string | No | — | Maximum 500 characters |
| `template_id` | string | No | — | Maximum 50 characters |
| `created_at` | date | Yes | — | BSON date |
| `updated_at` | date | No | — | BSON date |

**Other uniqueness:** None beyond `_id`. **Cardinality:** Each notification
refers to one guardian and one student; either may have many notifications
(1:N). It refers to one event in the collection named by `event_collection`
(polymorphic N:1); that reference's existence is not validated by MongoDB.
**Effective dates:** None. **Lifecycle:** `pending`, `sent`, `delivered`,
`failed`, `cancelled`.

## 12. `audit_events` — supporting history

**PK:** `_id` (`AUD-` + 14 digits + eight alphanumeric characters). **Purpose:**
Audit record for an operation on a collection document.

| Field | BSON type | Req. | FK / unique | Allowed values, units, and validator rule |
|---|---|---:|---|---|
| `_id` | string | Yes | PK; unique | `^AUD-[0-9]{14}-[A-Za-z0-9]{8}$` |
| `collection_name` | string | Yes | Polymorphic reference target | `students`, `guardian_contacts`, `address_zones`, `stops`, `buses`, `drivers`, `routes`, `route_stops`, `assignments`, `attendance_events`, `notifications`, `audit_events`, `bus_capacity_history` |
| `document_id` | string | Yes | Polymorphic FK | String; no ID pattern |
| `action` | string | Yes | — | `insert`, `update`, `delete`, `read` |
| `actor` | string | Yes | — | String; no pattern |
| `timestamp` | date | Yes | — | BSON UTC date/time |
| `before_state` | object or null | No | — | Object or `null` |
| `after_state` | object or null | No | — | Object or `null` |
| `changed_fields` | array of string | No | — | Each item is a string |
| `request_id` | string | No | — | No additional constraint |
| `ip_address` | string | No | — | No additional constraint |

**Other uniqueness:** None beyond `_id`. **Cardinality:** One audited document
may have many audit events (1:N), but the target is polymorphic and is not
enforced as a MongoDB FK. **Effective dates:** None; `timestamp` is the
operation time. **Lifecycle:** No lifecycle field; append-only behavior is an
application policy, not a validator constraint.

## 13. `bus_capacity_history` — supporting history

**PK:** `_id` (`BCH-BUS-` + six digits + eight-digit date). **Purpose:** Bus
capacity/accessibility value as of an effective date.

| Field | BSON type | Req. | FK / unique | Allowed values, units, and validator rule |
|---|---|---:|---|---|
| `_id` | string | Yes | PK; unique | `^BCH-BUS-[0-9]{6}-[0-9]{8}$` |
| `bus_id` | string | Yes | FK → `buses._id` | `^BUS-[0-9]{6}$` |
| `capacity` | int | Yes | — | 1–100 student passengers |
| `is_accessible` | bool | No | — | `true` or `false` |
| `reason` | string | No | — | Maximum 500 characters |
| `effective_from` | date | Yes | — | Date this value becomes effective |
| `effective_to` | date or null | No | — | Superseding date; `null` permitted |
| `changed_by` | string | Yes | — | String; no pattern |
| `created_at` | date | Yes | — | BSON date |

**Other uniqueness:** No unique secondary index. **Cardinality:** One bus may
have many capacity-history records (1:N); each record refers to one bus.
**Effective dates:** `effective_from` required; `effective_to` optional and
nullable. **Lifecycle:** No lifecycle field; history is append-only by
application policy.

## Relationships and cardinality

| Relationship | Cardinality | Implementation / required reference |
|---|---|---|
| `address_zones` → `students` | 1:N | Required `students.zone_id` |
| `address_zones` → `stops` | 1:N | Required `stops.zone_id` |
| `students` ↔ `guardian_contacts` | N:M | Optional `students.guardian_ids[]` |
| `buses` → `routes` | 1:N | Required `routes.bus_id` |
| `drivers` → `routes` | 1:N | Required `routes.driver_id` |
| `routes` ↔ `stops` | N:M | Required bridge rows in `route_stops` |
| `students` → `assignments` | 1:N | Required `assignments.student_id` |
| `routes` → `assignments` | 1:N | Required `assignments.route_id` |
| `stops` → `assignments` | 1:N | Required `assignments.stop_id` |
| `assignments` → `attendance_events` | 1:N | Required `attendance_events.assignment_id` |
| `guardians` → `notifications` | 1:N | Required `notifications.guardian_id` |
| `students` → `notifications` | 1:N | Required denormalized `notifications.student_id` |
| Event collection → `notifications` | 1:N per target | `event_id` plus `event_collection`; polymorphic |
| `buses` → `bus_capacity_history` | 1:N | Required `bus_capacity_history.bus_id` |
| Audited document → `audit_events` | 1:N per target | `collection_name` plus `document_id`; polymorphic |

Cardinality types are explicitly considered: no defined relationship is 1:1;
the model uses 1:N relationships and the N:M relationships implemented by
`route_stops` and `students.guardian_ids`. MongoDB validators check reference
field shapes, not referential existence or cross-field consistency.

## Effective dates and lifecycle summary

| Collection | Effective-date fields | Lifecycle/status values |
|---|---|---|
| `students` | Required `effective_from`; optional nullable `effective_to` | `active`, `inactive`, `suspended`, `transferred` |
| `guardian_contacts` | None | `contact_status`: `VALID`, `INVALID`, `BOUNCED` |
| `address_zones` | None | No lifecycle field |
| `stops` | None | `active`, `inactive`, `pending_approval`, `retired` |
| `buses` | Required `effective_from`; optional nullable `effective_to` | `active`, `inactive`, `maintenance`, `retired` |
| `drivers` | None | `active`, `inactive`, `on_leave`, `terminated` |
| `routes` | Required `effective_from`; optional nullable `effective_to` | `active`, `inactive`, `cancelled`, `completed` |
| `route_stops` | None | No lifecycle field |
| `assignments` | Required `effective_from`; optional nullable `effective_to` | `active`, `inactive`, `pending`, `cancelled` |
| `attendance_events` | Event `date`; no effective interval | `event_type` is an event enum, not a lifecycle |
| `notifications` | None | `pending`, `sent`, `delivered`, `failed`, `cancelled` |
| `audit_events` | Operation `timestamp`; no effective interval | No lifecycle field |
| `bus_capacity_history` | Required `effective_from`; optional nullable `effective_to` | No lifecycle field |

Where effective intervals are used, consumers should interpret a nullable
`effective_to` as an open-ended end date. The validators do not enforce date
ordering, non-overlap, transition rules, or that a record with an open end is
the only current record. Append-only behavior for history collections is a
policy and is not enforced by these validators.

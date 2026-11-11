# Entity Relationship Diagram

The diagram covers the 11 core entities and the two supporting history
collections. Relationships show logical references described by the
validators; MongoDB schema validation checks referenced ID shapes but does not
enforce that referenced documents exist.

```mermaid
erDiagram
    ADDRESS_ZONES ||--o{ STUDENTS : zone_id
    ADDRESS_ZONES ||--o{ STOPS : zone_id
    STUDENTS }o--o{ GUARDIAN_CONTACTS : guardian_ids
    BUSES ||--o{ ROUTES : bus_id
    DRIVERS ||--o{ ROUTES : driver_id
    ROUTES ||--o{ ROUTE_STOPS : route_id
    STOPS ||--o{ ROUTE_STOPS : stop_id
    STUDENTS ||--o{ ASSIGNMENTS : student_id
    ROUTES ||--o{ ASSIGNMENTS : route_id
    STOPS ||--o{ ASSIGNMENTS : stop_id
    ASSIGNMENTS ||--o{ ATTENDANCE_EVENTS : assignment_id
    STUDENTS ||--o{ ATTENDANCE_EVENTS : student_id
    ROUTES ||--o{ ATTENDANCE_EVENTS : route_id
    STOPS ||--o{ ATTENDANCE_EVENTS : stop_id
    GUARDIAN_CONTACTS ||--o{ NOTIFICATIONS : guardian_id
    STUDENTS ||--o{ NOTIFICATIONS : student_id
    BUSES ||--o{ BUS_CAPACITY_HISTORY : bus_id

    ADDRESS_ZONES {
        string _id PK
        string name UK
        string zone_type
    }
    STUDENTS {
        string _id PK
        string zone_id FK
        array guardian_ids FK
        string status
        date effective_from
        date effective_to
    }
    GUARDIAN_CONTACTS {
        string _id PK
        string contact_status
        bool is_valid
    }
    STOPS {
        string _id PK
        string zone_id FK
        bool is_approved
        string status
    }
    BUSES {
        string _id PK
        string license_plate UK
        int capacity
        string status
        date effective_from
        date effective_to
    }
    DRIVERS {
        string _id PK
        string license_number UK
        string status
    }
    ROUTES {
        string _id PK
        string bus_id FK
        string driver_id FK
        string direction
        string status
        date effective_from
        date effective_to
    }
    ROUTE_STOPS {
        string _id PK
        string route_id FK
        string stop_id FK
        int sequence "unique per route"
    }
    ASSIGNMENTS {
        string _id PK
        string student_id FK
        string route_id FK
        string stop_id FK
        string status
        date effective_from
        date effective_to
    }
    ATTENDANCE_EVENTS {
        string _id PK
        string assignment_id FK
        string student_id FK
        string route_id FK
        string stop_id FK
        date date
        string event_type
    }
    NOTIFICATIONS {
        string _id PK
        string guardian_id FK
        string student_id FK
        string event_id "polymorphic reference"
        string event_collection
        string status
    }
    AUDIT_EVENTS {
        string _id PK
        string collection_name "polymorphic target"
        string document_id "polymorphic target id"
        string action
        date timestamp
    }
    BUS_CAPACITY_HISTORY {
        string _id PK
        string bus_id FK
        int capacity
        date effective_from
        date effective_to
    }
```

## Cardinality and special references

- `address_zones` to `students`/`stops`, `buses`/`drivers` to `routes`, and
  each of `students`/`routes`/`stops` to `assignments` are **1:N**.
- `routes` to `stops` is **N:M**, implemented by `route_stops`. The bridge
  has unique indexes on `(route_id, sequence)` and `(route_id, stop_id)`.
- `students` to `guardian_contacts` is **N:M**, represented by the optional
  `students.guardian_ids` array.
- `assignments` to `attendance_events`, `guardians` to `notifications`, and
  `buses` to `bus_capacity_history` are **1:N**.
- `notifications.event_id` is a polymorphic reference selected by
  `event_collection` (`attendance_events`, `assignments`, or `routes`).
  `audit_events` targets any collection selected by `collection_name` and
  `document_id`. These polymorphic relationships cannot be represented as
  ordinary fixed entity-to-entity FKs.
- No **1:1** relationship is defined. Reference existence and cross-field
  agreement are application responsibilities, not validator guarantees.

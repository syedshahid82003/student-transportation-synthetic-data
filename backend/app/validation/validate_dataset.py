"""Independent, read-only validation for generated transportation datasets."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pandas as pd

ISSUE_TYPES = (
    "bus_capacity_exceeded",
    "incompatible_accessibility_route",
    "impossible_sequential_travel_time",
    "notification_to_invalid_contact",
    "unapproved_stop_exposed",
)

VALIDATION_RULES = {
    "bus_capacity_exceeded": (
        "Active assignment count for an active route must not exceed its bus capacity."
    ),
    "incompatible_accessibility_route": (
        "A student requiring accessibility must use an active route with an accessible bus."
    ),
    "impossible_sequential_travel_time": (
        "Each sequential stop arrival must be at least travel_minutes_from_prev "
        "after the previous stop arrival."
    ),
    "notification_to_invalid_contact": (
        "A sent notification must target a contact with contact_status VALID "
        "and is_valid true."
    ),
    "unapproved_stop_exposed": (
        "Active routes must not expose stops whose is_approved value is false."
    ),
}

VIOLATION_COLUMNS = ["rule_id", "entity", "record_id", "issue_type"]

ENTITY_TABLES = (
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
)

ID_PATTERNS = {
    "students": re.compile(r"^STU-[0-9]{6}$"),
    "guardian_contacts": re.compile(r"^GRD-[0-9]{6}$"),
    "address_zones": re.compile(r"^ZONE-[0-9]{4}$"),
    "stops": re.compile(r"^STOP-[0-9]{6}$"),
    "buses": re.compile(r"^BUS-[0-9]{6}$"),
    "drivers": re.compile(r"^DRV-[0-9]{6}$"),
    "routes": re.compile(r"^ROUTE-[0-9]{4}-[0-9]{6}$"),
    "route_stops": re.compile(r"^RS-[A-Z0-9-]+-[0-9]{4}$"),
    "assignments": re.compile(r"^ASN-STU-[0-9]{6}-[0-9]{4}$"),
    "attendance_events": re.compile(
        r"^ATT-[0-9]{8}-STU-[0-9]{6}-[a-z_]+$"
    ),
    "notifications": re.compile(r"^NOT-[0-9]{4}-[0-9]{6}$"),
}

ENUMS = {
    ("students", "status"): {
        "active", "inactive", "suspended", "transferred",
    },
    ("guardian_contacts", "relationship"): {
        "parent", "legal_guardian", "emergency_contact", "other",
    },
    ("guardian_contacts", "contact_status"): {"VALID", "INVALID", "BOUNCED"},
    ("guardian_contacts", "notification_preferences"): {
        "sms", "email", "push", "none",
    },
    ("address_zones", "zone_type"): {
        "elementary", "middle", "high", "mixed", "special_education",
    },
    ("stops", "status"): {
        "active", "inactive", "pending_approval", "retired",
    },
    ("buses", "status"): {"active", "inactive", "maintenance", "retired"},
    ("drivers", "license_class"): {"A", "B", "C"},
    ("drivers", "status"): {"active", "inactive", "on_leave", "terminated"},
    ("routes", "direction"): {"am", "pm", "midday"},
    ("routes", "status"): {"active", "inactive", "cancelled", "completed"},
    ("assignments", "status"): {
        "active", "inactive", "pending", "cancelled",
    },
    ("attendance_events", "event_type"): {
        "boarded", "alighted", "no_show", "absent", "late_pickup",
        "emergency_exit",
    },
    ("notifications", "event_collection"): {
        "attendance_events", "assignments", "routes",
    },
    ("notifications", "channel"): {"sms", "email", "push"},
    ("notifications", "status"): {
        "pending", "sent", "delivered", "failed", "cancelled",
    },
}

LIFECYCLE_TRANSITIONS = {
    "students": {
        "active": {"inactive", "suspended", "transferred"},
        "inactive": {"active", "suspended", "transferred"},
        "suspended": {"active", "inactive", "transferred"},
        "transferred": set(),
    },
    "stops": {
        "pending_approval": {"active", "inactive", "retired"},
        "active": {"inactive", "retired"},
        "inactive": {"active", "retired"},
        "retired": set(),
    },
    "buses": {
        "active": {"inactive", "maintenance", "retired"},
        "inactive": {"active", "retired"},
        "maintenance": {"active", "inactive", "retired"},
        "retired": set(),
    },
    "drivers": {
        "active": {"inactive", "on_leave", "terminated"},
        "inactive": {"active", "terminated"},
        "on_leave": {"active", "inactive", "terminated"},
        "terminated": set(),
    },
    "routes": {
        "active": {"inactive", "cancelled", "completed"},
        "inactive": {"active", "cancelled", "completed"},
        "cancelled": set(),
        "completed": set(),
    },
    "assignments": {
        "pending": {"active", "inactive", "cancelled"},
        "active": {"inactive", "cancelled"},
        "inactive": {"active", "cancelled"},
        "cancelled": set(),
    },
    "notifications": {
        "pending": {"sent", "failed", "cancelled"},
        "sent": {"delivered", "failed", "cancelled"},
        "failed": {"sent", "cancelled"},
        "delivered": set(),
        "cancelled": set(),
    },
}

FOREIGN_KEYS = {
    ("students", "zone_id"): "address_zones",
    ("students", "guardian_ids"): "guardian_contacts",
    ("stops", "zone_id"): "address_zones",
    ("routes", "bus_id"): "buses",
    ("routes", "driver_id"): "drivers",
    ("route_stops", "route_id"): "routes",
    ("route_stops", "stop_id"): "stops",
    ("assignments", "student_id"): "students",
    ("assignments", "route_id"): "routes",
    ("assignments", "stop_id"): "stops",
    ("attendance_events", "assignment_id"): "assignments",
    ("attendance_events", "student_id"): "students",
    ("attendance_events", "route_id"): "routes",
    ("attendance_events", "stop_id"): "stops",
    ("notifications", "guardian_id"): "guardian_contacts",
    ("notifications", "student_id"): "students",
}

OPTIONAL_FOREIGN_KEYS = {
    ("drivers", "bus_id"): "buses",
    ("guardian_contacts", "student_id"): "students",
}

RULE_ISSUE_TYPE_MAPPING = {
    "capacity_vs_assigned": "bus_capacity_exceeded",
    "accessibility_route_compatibility": "incompatible_accessibility_route",
    "sequential_travel_time": "impossible_sequential_travel_time",
    "notification_contact_validity": "notification_to_invalid_contact",
    "unapproved_stop_exposure": "unapproved_stop_exposed",
}


def _record(
    violations: list[dict[str, Any]],
    rule_id: str,
    entity: str,
    record_id: Any,
    issue_type: str | None = None,
) -> None:
    violations.append(
        {
            "rule_id": rule_id,
            "entity": entity,
            "record_id": str(record_id),
            "issue_type": issue_type,
        }
    )


def _time_minutes(value: Any) -> int | None:
    if not isinstance(value, str) or not re.fullmatch(
        r"([01][0-9]|2[0-3]):[0-5][0-9]", value
    ):
        return None
    hour, minute = map(int, value.split(":"))
    return hour * 60 + minute


def _date_value(value: Any) -> pd.Timestamp | None:
    if value is None or pd.isna(value):
        return None
    try:
        return pd.Timestamp(value)
    except (TypeError, ValueError, OverflowError):
        return None


def _emit_fk_violations(
    tables: dict[str, pd.DataFrame],
    violations: list[dict[str, Any]],
) -> None:
    keys = list(FOREIGN_KEYS.items()) + list(OPTIONAL_FOREIGN_KEYS.items())
    valid_id_sets = {
        target: set(tables[target]["_id"].dropna())
        for _, target in keys
        if target in tables
    }
    for (entity, field), target in keys:
        frame = tables.get(entity)
        if frame is None or field not in frame.columns or target not in tables:
            continue
        valid_ids = valid_id_sets[target]
        if field == "guardian_ids" and entity == "students":
            for _, row in frame[["_id", field]].iterrows():
                value = row[field]
                if not isinstance(value, (list, tuple, set)):
                    if value is None or value is pd.NA or (
                        isinstance(value, float) and pd.isna(value)
                    ):
                        continue
                    _record(
                        violations,
                        f"fk_{entity}_{field}",
                        entity,
                        row["_id"],
                    )
                    continue
                invalid_reference = False
                for reference in value:
                    if reference is None or reference is pd.NA or (
                        isinstance(reference, float) and pd.isna(reference)
                    ):
                        invalid_reference = True
                    elif reference not in valid_ids:
                        invalid_reference = True
                    if invalid_reference:
                        _record(
                            violations,
                            f"fk_{entity}_{field}",
                            entity,
                            row["_id"],
                        )
                        break
            continue

        values = frame[field]
        missing = values.isna()
        invalid = values.notna() & ~values.isin(valid_ids)
        if (entity, field) in FOREIGN_KEYS:
            invalid |= missing
        for record_id in frame.loc[invalid, "_id"]:
            _record(
                violations,
                f"fk_{entity}_{field}",
                entity,
                record_id,
            )

    notifications = tables.get("notifications")
    if (
        notifications is None
        or "event_collection" not in notifications
        or "event_id" not in notifications
    ):
        return
    event_id_sets = {
        name: set(frame["_id"].dropna())
        for name, frame in tables.items()
        if "_id" in frame
    }
    for target, group in notifications.groupby(
        "event_collection", dropna=False, sort=False
    ):
        target_ids = event_id_sets.get(str(target))
        if target_ids is None:
            continue
        invalid = group["event_id"].isna() | ~group["event_id"].isin(target_ids)
        for record_id in group.loc[invalid, "_id"]:
            _record(
                violations,
                "fk_notifications_event_id",
                "notifications",
                record_id,
            )


def _emit_unique_violations(
    tables: dict[str, pd.DataFrame],
    violations: list[dict[str, Any]],
) -> None:
    unique_columns = {
        "address_zones": ["name"],
        "buses": ["license_plate"],
        "drivers": ["license_number"],
    }
    for entity in ENTITY_TABLES:
        frame = tables.get(entity)
        if frame is None or "_id" not in frame:
            continue
        duplicated = frame["_id"].duplicated(keep=False)
        for record_id in frame.loc[duplicated, "_id"].dropna().unique():
            _record(violations, "pk_unique", entity, record_id)
        pattern = ID_PATTERNS.get(entity)
        if pattern is not None:
            invalid = frame["_id"].dropna().astype(str).map(
                lambda value: pattern.fullmatch(value) is None
            )
            for record_id in frame.loc[invalid, "_id"]:
                _record(violations, "pk_format", entity, record_id)

        for column in unique_columns.get(entity, []):
            if column not in frame:
                continue
            duplicated_values = frame[column].notna() & frame[column].duplicated(
                keep=False
            )
            for record_id in frame.loc[duplicated_values, "_id"].dropna().unique():
                _record(
                    violations,
                    f"unique_{entity}_{column}",
                    entity,
                    record_id,
                )

    for entity, columns in (
        ("route_stops", ["route_id", "sequence"]),
        ("route_stops", ["route_id", "stop_id"]),
        ("attendance_events", ["assignment_id", "date", "event_type"]),
    ):
        frame = tables.get(entity)
        if frame is None or not set(columns).issubset(frame.columns):
            continue
        duplicated = frame.duplicated(columns, keep=False)
        for record_id in frame.loc[duplicated, "_id"].dropna().unique():
            _record(
                violations,
                f"unique_{entity}_{'_'.join(columns)}",
                entity,
                record_id,
            )


def _emit_enum_violations(
    tables: dict[str, pd.DataFrame],
    violations: list[dict[str, Any]],
) -> None:
    for (entity, field), allowed in ENUMS.items():
        frame = tables.get(entity)
        if frame is None or field not in frame.columns:
            continue
        if field == "notification_preferences":
            invalid_ids = []
            for _, row in frame[["_id", field]].iterrows():
                value = row[field]
                values = (
                    value
                    if isinstance(value, (list, tuple, set))
                    else [value]
                )
                if any(
                    not pd.isna(item) and item not in allowed
                    for item in values
                ):
                    invalid_ids.append(row["_id"])
        else:
            invalid = frame[field].notna() & ~frame[field].isin(allowed)
            invalid_ids = frame.loc[invalid, "_id"].tolist()
        for record_id in invalid_ids:
            if record_id is not None:
                _record(
                    violations,
                    f"enum_{entity}_{field}",
                    entity,
                    record_id,
                )


def _emit_date_violations(
    tables: dict[str, pd.DataFrame],
    violations: list[dict[str, Any]],
) -> None:
    for entity in ("students", "buses", "routes", "assignments", "bus_capacity_history"):
        frame = tables.get(entity)
        if frame is None or not {"effective_from", "effective_to"}.issubset(frame):
            continue
        for _, row in frame.iterrows():
            start = _date_value(row["effective_from"])
            end = _date_value(row["effective_to"])
            if end is not None and (start is None or end <= start):
                _record(
                    violations,
                    "effective_date_order",
                    entity,
                    row["_id"],
                )


def _emit_lifecycle_violations(
    tables: dict[str, pd.DataFrame],
    violations: list[dict[str, Any]],
) -> None:
    for entity, transitions in LIFECYCLE_TRANSITIONS.items():
        frame = tables.get(entity)
        if frame is None:
            continue
        pairs: list[tuple[Any, Any, Any]] = []
        if {"previous_status", "status"}.issubset(frame.columns):
            pairs.extend(
                (row["_id"], row["previous_status"], row["status"])
                for _, row in frame.iterrows()
            )
        history = tables.get("lifecycle_history")
        if history is not None and {"entity", "record_id", "from_status", "to_status"}.issubset(history):
            rows = history[history["entity"].eq(entity)]
            pairs.extend(
                (row["record_id"], row["from_status"], row["to_status"])
                for _, row in rows.iterrows()
            )
        for record_id, previous, current in pairs:
            if pd.isna(previous) or pd.isna(current):
                continue
            if current not in transitions.get(previous, set()):
                _record(
                    violations,
                    f"lifecycle_transition_{entity}",
                    entity,
                    record_id,
                )


def _emit_anomaly_violations(
    tables: dict[str, pd.DataFrame],
    violations: list[dict[str, Any]],
) -> None:
    active_routes = tables["routes"].loc[
        tables["routes"]["status"].eq("active"), ["_id", "bus_id"]
    ]
    active_assignments = tables["assignments"].loc[
        tables["assignments"]["status"].eq("active"),
        ["_id", "student_id", "route_id"],
    ]
    bus_lookup = tables["buses"].drop_duplicates("_id").set_index("_id")
    student_lookup = (
        tables["students"].drop_duplicates("_id").set_index("_id")
    )
    active_route_buses = (
        active_routes.drop_duplicates("_id").set_index("_id")["bus_id"]
    )

    # Rule -> issue_type: bus_capacity_exceeded
    route_load = active_assignments.groupby("route_id").size()
    for _, route in active_routes.iterrows():
        if route["bus_id"] not in bus_lookup.index:
            continue
        bus = bus_lookup.loc[route["bus_id"]]
        if int(route_load.get(route["_id"], 0)) > int(bus["capacity"]):
            _record(
                violations,
                "capacity_vs_assigned",
                "routes",
                route["_id"],
                "bus_capacity_exceeded",
            )

    # Rule -> issue_type: incompatible_accessibility_route
    for _, assignment in active_assignments.iterrows():
        student_id = assignment["student_id"]
        if student_id not in student_lookup.index:
            continue
        bus_id = active_route_buses.get(assignment["route_id"])
        if pd.isna(bus_id):
            continue
        if bus_id not in bus_lookup.index:
            continue
        if (
            bool(student_lookup.loc[student_id, "accessibility_required"])
            and not bool(bus_lookup.loc[bus_id, "is_accessible"])
        ):
            _record(
                violations,
                "accessibility_route_compatibility",
                "assignments",
                assignment["_id"],
                "incompatible_accessibility_route",
            )

    # Rule -> issue_type: impossible_sequential_travel_time
    ordered_stops = tables["route_stops"].sort_values(
        ["route_id", "sequence"], kind="stable"
    )
    for _, group in ordered_stops.groupby("route_id", sort=True):
        ordered = group.sort_values("sequence", kind="stable")
        previous_rows = ordered.iloc[:-1].to_dict("records")
        current_rows = ordered.iloc[1:].to_dict("records")
        for previous, current in zip(previous_rows, current_rows):
            travel = current["travel_minutes_from_prev"]
            previous_time = _time_minutes(previous["scheduled_time"])
            current_time = _time_minutes(current["scheduled_time"])
            if (
                int(current["sequence"]) == int(previous["sequence"]) + 1
                and pd.notna(travel)
                and int(travel) > 0
                and previous_time is not None
                and current_time is not None
                and current_time - previous_time < int(travel)
            ):
                _record(
                    violations,
                    "sequential_travel_time",
                    "route_stops",
                    current["_id"],
                    "impossible_sequential_travel_time",
                )

    # Rule -> issue_type: notification_to_invalid_contact
    sent = tables["notifications"][
        tables["notifications"]["sent_at"].notna()
    ]
    guardian_lookup = (
        tables["guardian_contacts"].drop_duplicates("_id").set_index("_id")
    )
    for _, notification in sent.iterrows():
        guardian_id = notification["guardian_id"]
        invalid = guardian_id not in guardian_lookup.index
        if not invalid:
            guardian = guardian_lookup.loc[guardian_id]
            invalid = (
                guardian["contact_status"] != "VALID"
                or not bool(guardian["is_valid"])
            )
        if invalid:
            _record(
                violations,
                "notification_contact_validity",
                "notifications",
                notification["_id"],
                "notification_to_invalid_contact",
            )

    # Rule -> issue_type: unapproved_stop_exposed
    active_route_ids = set(active_routes["_id"])
    route_stop_rows = tables["route_stops"][
        tables["route_stops"]["route_id"].isin(active_route_ids)
    ]
    stop_lookup = tables["stops"].drop_duplicates("_id").set_index("_id")
    for stop_id in route_stop_rows["stop_id"].drop_duplicates():
        if stop_id in stop_lookup.index and not bool(
            stop_lookup.loc[stop_id, "is_approved"]
        ):
            _record(
                violations,
                "unapproved_stop_exposure",
                "stops",
                stop_id,
                "unapproved_stop_exposed",
            )


def _reconciliation_results(
    tables: dict[str, pd.DataFrame],
    violations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []

    assignments = tables["assignments"]
    active_assignments = assignments[assignments["status"].eq("active")]
    active_routes = tables["routes"][tables["routes"]["status"].eq("active")]
    route_load = active_assignments.groupby("route_id").size()
    active_route_ids = set(active_routes["_id"])
    computed_total = int(
        sum(
            count
            for route_id, count in route_load.items()
            if route_id in active_route_ids
        )
    )
    active_assignment_count = len(active_assignments)
    unmatched_assignment_ids = active_assignments.loc[
        ~active_assignments["route_id"].isin(active_route_ids), "_id"
    ].astype(str).tolist()
    if computed_total != active_assignment_count:
        for assignment_id in unmatched_assignment_ids:
            _record(
                violations,
                "reconcile_route_load",
                "assignments",
                assignment_id,
            )
    results.append(
        {
            "rule_id": "reconcile_route_load",
            "issue_type": None,
            "checks": len(active_routes),
            "violations": len(unmatched_assignment_ids),
            "details": {
                "active_routes": len(active_routes),
                "active_assignments": active_assignment_count,
                "sum_of_route_loads": computed_total,
                "unmatched_assignments": unmatched_assignment_ids,
            },
        }
    )
    route_load_fields = (
        "assignment_count",
        "assigned_count",
        "student_count",
        "route_load",
    )
    for field in route_load_fields:
        if field not in active_routes:
            continue
        mismatched_routes = []
        for _, route in active_routes.iterrows():
            expected_load = int(route_load.get(route["_id"], 0))
            stored_load = route[field]
            if pd.notna(stored_load) and int(stored_load) != expected_load:
                mismatched_routes.append(str(route["_id"]))
                _record(
                    violations,
                    "reconcile_route_load",
                    "routes",
                    route["_id"],
                )
        results[0]["violations"] += len(mismatched_routes)
        results[0]["details"]["mismatched_routes"] = mismatched_routes
        break

    attendance = tables["attendance_events"]
    triggers = attendance[
        attendance["event_type"].isin(["absent", "no_show"])
    ]
    skipped = tables.get("skipped")
    skipped_count = 0 if skipped is None else len(skipped)
    actual_notifications = tables["notifications"]
    if "event_collection" in actual_notifications:
        actual_notifications = actual_notifications[
            actual_notifications["event_collection"].eq("attendance_events")
        ]
    expected_count = len(triggers) - skipped_count
    actual_count = len(actual_notifications)
    mismatch = expected_count != actual_count
    if mismatch:
        _record(
            violations,
            "reconcile_notifications",
            "notifications",
            "__aggregate__",
        )
    results.append(
        {
            "rule_id": "reconcile_notifications",
            "issue_type": None,
            "checks": 1,
            "violations": int(mismatch),
            "details": {
                "absent_and_no_show": len(triggers),
                "skipped": skipped_count,
                "expected_notifications": expected_count,
                "actual_notifications": actual_count,
            },
        }
    )
    return results


def validate_dataset(
    tables: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    """Validate all core entities and return data-only violations.

    Each returned row has ``rule_id``, ``entity``, ``record_id``, and
    ``issue_type``. The five anomaly checks carry their corresponding
    ground-truth issue type; general integrity checks use ``None``.
    """
    missing = set(ENTITY_TABLES) - set(tables)
    if missing:
        raise ValueError(f"validation data is missing tables: {sorted(missing)}")
    for entity in ENTITY_TABLES:
        if not isinstance(tables[entity], pd.DataFrame):
            raise TypeError(f"{entity} must be a pandas DataFrame")
        if "_id" not in tables[entity]:
            raise ValueError(f"{entity} is missing the _id primary key")

    violations: list[dict[str, Any]] = []
    _emit_unique_violations(tables, violations)
    _emit_fk_violations(tables, violations)
    _emit_enum_violations(tables, violations)
    _emit_date_violations(tables, violations)
    _emit_lifecycle_violations(tables, violations)
    _emit_anomaly_violations(tables, violations)
    _reconciliation_results(tables, violations)

    result = pd.DataFrame(violations, columns=VIOLATION_COLUMNS)
    if not result.empty:
        result = result.drop_duplicates(VIOLATION_COLUMNS).reset_index(drop=True)
    return result


def detect_violations(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Compatibility view of the five anomaly rules only."""
    violations = validate_dataset(tables)
    return violations.loc[violations["issue_type"].isin(ISSUE_TYPES)].reset_index(
        drop=True
    )


def validation_summary(
    ground_truth: pd.DataFrame, violations: pd.DataFrame
) -> pd.DataFrame:
    """Return per-issue true/false positive and negative evaluation metrics."""
    required_truth = {"issue_type", "entity", "record_id"}
    required_violations = set(VIOLATION_COLUMNS)
    if not required_truth.issubset(ground_truth.columns):
        raise ValueError("ground_truth is missing issue_type/entity/record_id")
    if not required_violations.issubset(violations.columns):
        raise ValueError(
            "violations is missing rule_id/entity/record_id/issue_type"
        )

    results = []
    for issue_type in ISSUE_TYPES:
        expected = {
            (str(row.entity), str(row.record_id))
            for row in ground_truth.loc[
                ground_truth["issue_type"].eq(issue_type)
            ].itertuples()
        }
        detected = {
            (str(row.entity), str(row.record_id))
            for row in violations.loc[
                violations["issue_type"].eq(issue_type)
            ].itertuples()
        }
        true_positive = len(expected & detected)
        false_positive = len(detected - expected)
        false_negative = len(expected - detected)
        results.append(
            {
                "issue_type": issue_type,
                "true_positives": true_positive,
                "false_positives": false_positive,
                "false_negatives": false_negative,
                "precision": (
                    true_positive / (true_positive + false_positive)
                    if true_positive + false_positive else 0.0
                ),
                "recall": (
                    true_positive / (true_positive + false_negative)
                    if true_positive + false_negative else 0.0
                ),
            }
        )
    return pd.DataFrame(results)


def evaluate_datasets(
    baseline: dict[str, pd.DataFrame],
    mutated: dict[str, pd.DataFrame],
    ground_truth: pd.DataFrame,
) -> dict[str, Any]:
    """Validate baseline and mutated data and prepare a JSON-safe summary."""
    baseline_violations = validate_dataset(baseline)
    mutated_violations = validate_dataset(mutated)
    metrics = validation_summary(ground_truth, mutated_violations)
    baseline_reconciliation: dict[str, dict[str, Any]] = {}
    mutated_reconciliation: dict[str, dict[str, Any]] = {}
    for result in _reconciliation_results(baseline, []):
        baseline_reconciliation[result["rule_id"]] = result
    for result in _reconciliation_results(mutated, []):
        mutated_reconciliation[result["rule_id"]] = result

    rule_results = []
    composite_uniques = (
        ("route_stops", ("route_id", "sequence")),
        ("route_stops", ("route_id", "stop_id")),
        ("attendance_events", ("assignment_id", "date", "event_type")),
    )
    all_rules = {
        f"fk_{entity}_{field}"
        for entity, field in (*FOREIGN_KEYS, *OPTIONAL_FOREIGN_KEYS)
    }
    all_rules.update(
        f"unique_{entity}_{column}"
        for entity, columns in {
            "address_zones": ("name",),
            "buses": ("license_plate",),
            "drivers": ("license_number",),
        }.items()
        for column in columns
    )
    all_rules.update(
        f"unique_{entity}_{'_'.join(columns)}"
        for entity, columns in composite_uniques
    )
    all_rules.update(
        f"enum_{entity}_{field}" for entity, field in ENUMS
    )
    all_rules.update(
        f"lifecycle_transition_{entity}" for entity in LIFECYCLE_TRANSITIONS
    )
    all_rules.update(
        {
            "pk_unique",
            "pk_format",
            "fk_notifications_event_id",
            "effective_date_order",
            "reconcile_route_load",
            "reconcile_notifications",
            *RULE_ISSUE_TYPE_MAPPING,
        }
    )
    all_rules = sorted(
        all_rules
        | set(baseline_violations["rule_id"])
        | set(mutated_violations["rule_id"])
    )
    baseline_counts = baseline_violations["rule_id"].value_counts().to_dict()
    mutated_counts = mutated_violations["rule_id"].value_counts().to_dict()
    for rule_id in all_rules:
        rule_results.append(
            {
                "rule_id": rule_id,
                "issue_type": RULE_ISSUE_TYPE_MAPPING.get(rule_id),
                "baseline_violations": int(baseline_counts.get(rule_id, 0)),
                "mutated_violations": int(mutated_counts.get(rule_id, 0)),
                "baseline_details": baseline_reconciliation.get(
                    rule_id, {}
                ).get("details", {}),
                "mutated_details": mutated_reconciliation.get(
                    rule_id, {}
                ).get("details", {}),
            }
        )

    return {
        "rule_issue_type_mapping": RULE_ISSUE_TYPE_MAPPING,
        "rule_results": rule_results,
        "issue_type_metrics": metrics.to_dict(orient="records"),
        "baseline_violation_count": len(baseline_violations),
        "baseline_violations": baseline_violations.to_dict(orient="records"),
        "mutated_violations": mutated_violations.to_dict(orient="records"),
    }


def write_validation_summary(
    summary: dict[str, Any], output_path: str | Path
) -> Path:
    """Write a validation report as ``validation_summary.json``."""
    path = Path(output_path)
    if path.suffix.lower() != ".json":
        path = path / "validation_summary.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(summary, indent=2, sort_keys=True, default=str) + "\n",
        encoding="ascii",
    )
    return path


def _require_columns(
    tables: dict[str, pd.DataFrame],
    table_name: str,
    columns: set[str],
) -> None:
    missing = columns - set(tables[table_name].columns)
    if missing:
        raise ValueError(
            f"{table_name} is missing required columns: {sorted(missing)}"
        )


def _minutes(value: str) -> int:
    hour, minute = map(int, value.split(":"))
    return hour * 60 + minute

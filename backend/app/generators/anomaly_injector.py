"""Inject deterministic labelled edge cases into copies of baseline data.

The injector never mutates its input DataFrames. Labels are written only to
ground truth, never to the entity tables. Starter produces 6-10 anomalies per
issue type and full produces 30-50 per type.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from backend.app.core.config import SEED
from backend.app.validation.validate_dataset import (
    ISSUE_TYPES,
    VALIDATION_RULES,
    detect_violations,
    validation_summary,
)

GROUND_TRUTH_COLUMNS = [
    "anomaly_id",
    "issue_type",
    "entity",
    "record_id",
    "rule_violated",
    "expected_decision",
    "severity",
]

_REQUIRED_TABLES = {
    "assignments",
    "buses",
    "guardian_contacts",
    "notifications",
    "route_stops",
    "routes",
    "stops",
    "students",
}


def _require_columns(
    tables: dict[str, pd.DataFrame], table_name: str, columns: set[str]
) -> None:
    missing = columns - set(tables[table_name].columns)
    if missing:
        raise ValueError(
            f"{table_name} is missing required columns: {sorted(missing)}"
        )


def _sample_rows(
    frame: pd.DataFrame,
    count: int,
    rng: np.random.Generator,
    description: str,
) -> pd.DataFrame:
    """Sample unique rows in stable ID order with the supplied RNG."""
    ordered = frame.sort_values("_id", kind="stable").reset_index(drop=True)
    if len(ordered) < count:
        raise ValueError(
            f"not enough {description}: need {count}, found {len(ordered)}"
        )
    positions = rng.choice(len(ordered), size=count, replace=False)
    return ordered.iloc[positions].reset_index(drop=True)


def _severity_variants(
    count: int, rng: np.random.Generator
) -> list[str]:
    """Return a seeded, balanced list containing both severity variants."""
    variants = ["boundary"] * (count // 2)
    variants.extend(["clear"] * (count - len(variants)))
    rng.shuffle(variants)
    return variants


def _append_truth(
    records: list[dict[str, str]],
    used_record_ids: set[str],
    issue_type: str,
    entity: str,
    record_id: str,
    rule_violated: str,
    expected_decision: str,
    severity: str,
) -> None:
    record_id = str(record_id)
    if record_id in used_record_ids:
        raise ValueError(f"anomaly record_id is duplicated: {record_id}")
    used_record_ids.add(record_id)
    records.append(
        {
            "anomaly_id": f"ANOM-{len(records) + 1:06d}",
            "issue_type": issue_type,
            "entity": entity,
            "record_id": record_id,
            "rule_violated": rule_violated,
            "expected_decision": expected_decision,
            "severity": severity,
        }
    )


def _counts_for_scale(
    n_students: int, rng: np.random.Generator
) -> dict[str, int]:
    if n_students <= 1_000:
        low, high = 6, 10
    else:
        low, high = 30, 50
    return {
        issue_type: int(rng.integers(low, high + 1))
        for issue_type in ISSUE_TYPES
    }


def inject_anomalies(
    baseline: dict[str, pd.DataFrame],
    seed: int = SEED,
) -> tuple[dict[str, pd.DataFrame], pd.DataFrame]:
    """Return anomaly-mutated table copies and separate ground truth.

    The baseline must include students, buses, routes, route_stops,
    assignments, stops, guardian_contacts, and notifications. Selection,
    counts, and severity variants all use ``default_rng(seed)``. Every
    ground-truth record ID is distinct and resolves in its named entity table.
    """
    missing_tables = _REQUIRED_TABLES - set(baseline)
    if missing_tables:
        raise ValueError(f"baseline is missing tables: {sorted(missing_tables)}")
    if any(not isinstance(frame, pd.DataFrame) for frame in baseline.values()):
        raise TypeError("all baseline table values must be pandas DataFrames")
    if any(
        set(GROUND_TRUTH_COLUMNS) & set(frame.columns)
        for frame in baseline.values()
    ):
        raise ValueError("baseline entity tables must not contain anomaly labels")

    tables = {name: frame.copy(deep=True) for name, frame in baseline.items()}
    required_columns = {
        "assignments": {"_id", "student_id", "route_id", "status"},
        "buses": {"_id", "capacity", "is_accessible", "status"},
        "guardian_contacts": {
            "_id", "contact_status", "is_valid",
        },
        "notifications": {"_id", "guardian_id", "sent_at"},
        "route_stops": {
            "_id", "route_id", "stop_id", "sequence",
            "travel_minutes_from_prev", "scheduled_time",
        },
        "routes": {"_id", "bus_id", "status"},
        "stops": {"_id", "zone_id", "is_approved", "status"},
        "students": {"_id", "zone_id", "accessibility_required"},
    }
    for name, columns in required_columns.items():
        _require_columns(tables, name, columns)

    rng = np.random.default_rng(seed)
    counts = _counts_for_scale(len(tables["students"]), rng)
    severities = {
        issue_type: _severity_variants(count, rng)
        for issue_type, count in counts.items()
    }
    records: list[dict[str, str]] = []
    used_record_ids: set[str] = set()

    active_assignments = tables["assignments"][
        tables["assignments"]["status"] == "active"
    ]
    routes = tables["routes"]
    buses = tables["buses"]
    route_bus = routes.set_index("_id")["bus_id"]
    bus_capacity = buses.set_index("_id")["capacity"]
    route_load = active_assignments.groupby("route_id").size()
    capacity_candidates = []
    for route_id, load in route_load.items():
        if route_id not in route_bus.index:
            continue
        bus_id = route_bus.loc[route_id]
        if bus_id not in bus_capacity.index or int(bus_capacity.loc[bus_id]) < int(load):
            continue
        if int(load) > 1:
            capacity_candidates.append(
                {"_id": str(route_id), "bus_id": str(bus_id), "load": int(load)}
            )
    capacity_candidates_df = pd.DataFrame(
        capacity_candidates, columns=["_id", "bus_id", "load"]
    )
    cap_count = counts["bus_capacity_exceeded"]
    clear_cap_count = severities["bus_capacity_exceeded"].count("clear")
    boundary_cap_count = cap_count - clear_cap_count
    clear_candidates = capacity_candidates_df[
        capacity_candidates_df["load"] >= 11
    ]
    if len(clear_candidates) < clear_cap_count:
        raise ValueError("not enough high-load routes for clear capacity cases")
    chosen_clear = _sample_rows(
        clear_candidates, clear_cap_count, rng, "clear capacity routes"
    )
    chosen_boundary = _sample_rows(
        capacity_candidates_df[
            ~capacity_candidates_df["_id"].isin(chosen_clear["_id"])
        ],
        boundary_cap_count,
        rng,
        "boundary capacity routes",
    )
    capacity_by_route: dict[str, int] = {}
    for selected_rows, severity in (
        (chosen_boundary, "boundary"),
        (chosen_clear, "clear"),
    ):
        for _, selected in selected_rows.iterrows():
            route_id = str(selected["_id"])
            bus_id = str(selected["bus_id"])
            load = int(selected["load"])
            excess = (
                1
                if severity == "boundary"
                else int(rng.integers(10, min(20, load - 1) + 1))
            )
            bus_row = tables["buses"].index[
                tables["buses"]["_id"] == bus_id
            ][0]
            tables["buses"].at[bus_row, "capacity"] = load - excess
            capacity_by_route[route_id] = load
            _append_truth(
                records,
                used_record_ids,
                "bus_capacity_exceeded",
                "routes",
                route_id,
                "Active assignment count on a route must not exceed its bus capacity.",
                "Reject or flag the route as over capacity; do not silently drop assignments.",
                severity,
            )

    # Assign accessible students to distinct non-accessible routes that serve
    # the student's zone. Routes are matched one-to-one to preserve route load.
    bus_accessibility = tables["buses"].set_index("_id")["is_accessible"]
    inaccessible_routes = routes[
        routes["status"].eq("active")
        & routes["bus_id"].map(bus_accessibility).fillna(False).eq(False)
    ]
    stop_zones = tables["stops"].set_index("_id")["zone_id"]
    route_zone_stops: dict[str, dict[str, list[str]]] = {}
    for _, route_stop in tables["route_stops"].iterrows():
        stop_id = str(route_stop["stop_id"])
        route_id = str(route_stop["route_id"])
        zone_id = stop_zones.get(stop_id)
        route_zone_stops.setdefault(route_id, {}).setdefault(
            str(zone_id), []
        ).append(stop_id)

    student_zones = tables["students"].set_index("_id")["zone_id"]
    accessible_students = set(
        tables["students"].loc[
            tables["students"]["accessibility_required"].astype(bool), "_id"
        ]
    )
    incompatible_count = counts["incompatible_accessibility_route"]
    route_options: dict[str, dict[str, str]] = {}
    for _, assignment in active_assignments.iterrows():
        student_id = str(assignment["student_id"])
        if student_id not in accessible_students:
            continue
        if str(assignment["route_id"]) in capacity_by_route:
            continue
        assignment_id = str(assignment["_id"])
        zone_id = str(student_zones.loc[student_id])
        options: dict[str, str] = {}
        for route_id in inaccessible_routes["_id"].astype(str):
            if route_id == str(assignment["route_id"]):
                continue
            matching_stops = route_zone_stops.get(route_id, {}).get(zone_id, [])
            if matching_stops:
                options[route_id] = matching_stops[0]
        if options:
            route_options[assignment_id] = options

    if len(route_options) < incompatible_count:
        raise ValueError(
            "not enough accessible student assignments with same-zone non-accessible routes"
        )

    assignment_order = list(route_options)
    rng.shuffle(assignment_order)
    assignment_order.sort(key=lambda item: len(route_options[item]))
    route_matching: dict[str, tuple[str, str]] = {}

    def match_route(assignment_id: str, seen_routes: set[str]) -> bool:
        options = list(route_options[assignment_id].items())
        rng.shuffle(options)
        for route_id, stop_id in options:
            if route_id in seen_routes:
                continue
            seen_routes.add(route_id)
            if route_id not in route_matching or match_route(
                route_matching[route_id][0], seen_routes
            ):
                route_matching[route_id] = (assignment_id, stop_id)
                return True
        return False

    for assignment_id in assignment_order:
        match_route(assignment_id, set())
    matched_pairs = list(route_matching.items())
    if len(matched_pairs) < incompatible_count:
        raise ValueError(
            "not enough distinct non-accessible routes serving accessible student zones"
        )
    rng.shuffle(matched_pairs)
    matched_pairs = matched_pairs[:incompatible_count]

    target_routes: set[str] = set()
    for row_pos, (target_route_id, (assignment_id, target_stop_id)) in enumerate(
        matched_pairs
    ):
        assignment_index = tables["assignments"].index[
            tables["assignments"]["_id"] == assignment_id
        ][0]
        tables["assignments"].at[assignment_index, "route_id"] = target_route_id
        tables["assignments"].at[assignment_index, "stop_id"] = target_stop_id
        target_routes.add(target_route_id)
        severity = severities["incompatible_accessibility_route"][row_pos]
        if severity == "clear":
            target_bus = route_bus.loc[target_route_id]
            bus_index = tables["buses"].index[
                tables["buses"]["_id"] == target_bus
            ][0]
            tables["buses"].at[bus_index, "status"] = "maintenance"
        _append_truth(
            records,
            used_record_ids,
            "incompatible_accessibility_route",
            "assignments",
            assignment_id,
            "A student requiring accessibility must be assigned to a route using an accessible bus.",
            "Reject the route assignment and retain the student's assignment record.",
            severity,
        )

    # Keep unlabelled target routes within capacity, then reapply exact labelled
    # capacity thresholds after all assignment edits.
    final_loads = (
        tables["assignments"]
        .loc[tables["assignments"]["status"].eq("active")]
        .groupby("route_id")
        .size()
        .to_dict()
    )
    for route_id in target_routes - set(capacity_by_route):
        bus_id = route_bus.loc[route_id]
        bus_index = tables["buses"].index[tables["buses"]["_id"] == bus_id][0]
        capacity = int(tables["buses"].at[bus_index, "capacity"])
        load = int(final_loads.get(route_id, 0))
        if load > capacity:
            tables["buses"].at[bus_index, "capacity"] = load

    for route_id, original_load in capacity_by_route.items():
        current_load = int(final_loads.get(route_id, 0))
        bus_id = route_bus.loc[route_id]
        bus_row = tables["buses"].index[tables["buses"]["_id"] == bus_id][0]
        severity = next(
            record["severity"]
            for record in records
            if record["issue_type"] == "bus_capacity_exceeded"
            and record["record_id"] == route_id
        )
        excess = 1 if severity == "boundary" else max(10, original_load - current_load)
        if severity == "clear":
            excess = min(excess, current_load - 1)
        tables["buses"].at[bus_row, "capacity"] = current_load - excess

    # Make arrival times impossible by equality (boundary) or by at least ten
    # minutes early (clear), preserving the validator's HH:MM string format.
    route_stops = tables["route_stops"].sort_values(
        ["route_id", "sequence"], kind="stable"
    )
    travel_candidates = []
    for _, group in route_stops.groupby("route_id", sort=True):
        ordered = group.sort_values("sequence", kind="stable")
        for prior, current in zip(
            ordered.iloc[:-1].to_dict("records"),
            ordered.iloc[1:].to_dict("records"),
        ):
            travel = current["travel_minutes_from_prev"]
            if pd.notna(travel) and int(travel) > 0:
                travel_candidates.append(
                    {
                        "_id": str(current["_id"]),
                        "route_id": str(current["route_id"]),
                        "prior_time": str(prior["scheduled_time"]),
                        "previous_stop_id": str(prior["_id"]),
                    }
                )
    travel_count = counts["impossible_sequential_travel_time"]
    chosen_travel = _sample_rows(
        pd.DataFrame(travel_candidates).drop_duplicates(
            "route_id", keep="first"
        ),
        travel_count,
        rng,
        "sequential route-stop pairs",
    )
    for row_pos, selected in chosen_travel.iterrows():
        stop_id = str(selected["_id"])
        stop_index = tables["route_stops"].index[
            tables["route_stops"]["_id"] == stop_id
        ][0]
        severity = severities["impossible_sequential_travel_time"][row_pos]
        prior_minutes = _minutes(str(selected["prior_time"]))
        bad_minutes = (
            prior_minutes
            if severity == "boundary"
            else prior_minutes - int(rng.integers(10, 31))
        )
        tables["route_stops"].at[stop_index, "scheduled_time"] = _hhmm(
            bad_minutes
        )
        _append_truth(
            records,
            used_record_ids,
            "impossible_sequential_travel_time",
            "route_stops",
            stop_id,
            "A stop arrival must be later than the previous stop arrival by at least travel_minutes_from_prev.",
            "Reject or flag the sequential stop schedule as impossible.",
            severity,
        )

    # Mark distinct contacts invalid after selecting one sent notification per
    # contact, so each ground-truth row represents one independent incident.
    notification_rows = tables["notifications"][
        tables["notifications"]["sent_at"].notna()
    ].sort_values("_id", kind="stable")
    valid_contacts = tables["guardian_contacts"][
        tables["guardian_contacts"]["contact_status"].eq("VALID")
        & tables["guardian_contacts"]["is_valid"].astype(bool)
    ]
    valid_contact_ids = set(valid_contacts["_id"])
    notification_candidates = notification_rows[
        notification_rows["guardian_id"].isin(valid_contact_ids)
    ]
    notification_count = counts["notification_to_invalid_contact"]
    chosen_notifications = _sample_rows(
        notification_candidates,
        notification_count,
        rng,
        "sent notifications to distinct valid contacts",
    )
    existing_guardian_ids = set(tables["guardian_contacts"]["_id"].astype(str))
    guardian_suffixes = [
        int(value[4:])
        for value in existing_guardian_ids
        if value.startswith("GRD-") and value[4:].isdigit()
    ]
    next_guardian_number = max(guardian_suffixes, default=0) + 1
    invalid_contact_rows = []
    for row_pos, selected in chosen_notifications.iterrows():
        notification_id = str(selected["_id"])
        guardian_id = selected["guardian_id"]
        contact_index = tables["guardian_contacts"].index[
            tables["guardian_contacts"]["_id"] == guardian_id
        ][0]
        severity = severities["notification_to_invalid_contact"][row_pos]
        invalid_contact_id = f"GRD-{next_guardian_number:06d}"
        next_guardian_number += 1
        existing_guardian_ids.add(invalid_contact_id)
        invalid_contact = tables["guardian_contacts"].loc[contact_index].copy()
        invalid_contact["_id"] = invalid_contact_id
        invalid_contact["contact_status"] = (
            "BOUNCED" if severity == "boundary" else "INVALID"
        )
        invalid_contact["is_valid"] = False
        invalid_contact_rows.append(invalid_contact)
        notification_index = tables["notifications"].index[
            tables["notifications"]["_id"] == notification_id
        ][0]
        tables["notifications"].at[
            notification_index, "guardian_id"
        ] = invalid_contact_id
        _append_truth(
            records,
            used_record_ids,
            "notification_to_invalid_contact",
            "notifications",
            notification_id,
            "A sent notification must target a contact with contact_status VALID and is_valid true.",
            "Flag the notification as sent to an invalid contact; do not treat it as a valid delivery.",
            severity,
        )
    if invalid_contact_rows:
        tables["guardian_contacts"] = pd.concat(
            [
                tables["guardian_contacts"],
                pd.DataFrame(invalid_contact_rows),
            ],
            ignore_index=True,
        )

    # Mark stops exposed by an active route as unapproved. The stop ID is the
    # ground-truth record ID, while the route-stop row proves its exposure.
    active_route_ids = set(routes.loc[routes["status"].eq("active"), "_id"])
    active_route_stops = tables["route_stops"][
        tables["route_stops"]["route_id"].isin(active_route_ids)
    ]
    exposed_stop_ids = set(active_route_stops["stop_id"])
    exposed_candidates = tables["stops"][
        tables["stops"]["_id"].isin(exposed_stop_ids)
        & tables["stops"]["is_approved"].astype(bool)
    ]
    used_travel_stop_ids = set(
        records_item["record_id"]
        for records_item in records
        if records_item["issue_type"] == "impossible_sequential_travel_time"
    )
    if used_travel_stop_ids:
        affected = set(
            tables["route_stops"].loc[
                tables["route_stops"]["_id"].isin(used_travel_stop_ids), "stop_id"
            ]
        )
        exposed_candidates = exposed_candidates[
            ~exposed_candidates["_id"].isin(affected)
        ]
    stop_count = counts["unapproved_stop_exposed"]
    chosen_stops = _sample_rows(
        exposed_candidates, stop_count, rng, "approved stops exposed by active routes"
    )
    for row_pos, selected in chosen_stops.iterrows():
        stop_id = str(selected["_id"])
        stop_index = tables["stops"].index[tables["stops"]["_id"] == stop_id][0]
        severity = severities["unapproved_stop_exposed"][row_pos]
        tables["stops"].at[stop_index, "is_approved"] = False
        if severity == "clear":
            tables["stops"].at[stop_index, "status"] = "retired"
        _append_truth(
            records,
            used_record_ids,
            "unapproved_stop_exposed",
            "stops",
            stop_id,
            "A route must not expose an address through a stop that is not approved.",
            "Remove the unapproved stop from route exposure pending approval.",
            severity,
        )

    ground_truth = pd.DataFrame(records, columns=GROUND_TRUTH_COLUMNS)
    return tables, ground_truth


def _minutes(value: str) -> int:
    hour, minute = map(int, value.split(":"))
    return hour * 60 + minute


def _hhmm(value: int) -> str:
    return f"{value // 60:02d}:{value % 60:02d}"


def write_ground_truth(
    ground_truth: pd.DataFrame, output_dir: str | Path
) -> tuple[Path, Path]:
    """Write ground truth to ``ground_truth.csv`` and ``ground_truth.json``."""
    missing = set(GROUND_TRUTH_COLUMNS) - set(ground_truth.columns)
    if missing:
        raise ValueError(f"ground truth is missing columns: {sorted(missing)}")

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    csv_path = output_path / "ground_truth.csv"
    json_path = output_path / "ground_truth.json"
    records = ground_truth[GROUND_TRUTH_COLUMNS]
    records.to_csv(csv_path, index=False, lineterminator="\n")
    records.to_json(json_path, orient="records", indent=2, force_ascii=True)
    return csv_path, json_path

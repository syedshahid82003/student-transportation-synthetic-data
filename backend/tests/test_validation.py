"""Tests for independent data-only validation at starter and full scale."""

from __future__ import annotations

import hashlib
import io
import json

import numpy as np
import pandas as pd
import pytest

from backend.app.core.config import SEED
from backend.app.generators.anomaly_injector import inject_anomalies
from backend.app.generators.attendance_generator import generate_attendance
from backend.app.generators.master_data import generate_master_data
from backend.app.generators.notification_generator import generate_notifications
from backend.app.generators.route_generator import generate_routes
from backend.app.services.assignment_service import assign_all_students
from backend.app.validation.validate_dataset import (
    ISSUE_TYPES,
    evaluate_datasets,
    validate_dataset,
    write_validation_summary,
)


def _build_baseline(scale: str) -> dict[str, pd.DataFrame]:
    master = generate_master_data(scale)
    routes, route_stops = generate_routes(
        master["buses"],
        master["drivers"],
        master["stops"],
        master["students"],
        np.random.default_rng(SEED),
    )
    assigned = assign_all_students(
        master, routes, route_stops, np.random.default_rng(SEED)
    )
    attendance, _ = generate_attendance(
        assigned["assignments"],
        master["students"],
        routes,
        master["buses"],
        scale=scale,
        rng=np.random.default_rng(SEED),
    )
    notifications, skipped = generate_notifications(
        attendance,
        master["students"],
        master["guardian_contacts"],
        rng=np.random.default_rng(SEED),
    )
    return {
        **master,
        "routes": routes,
        "route_stops": route_stops,
        "assignments": assigned["assignments"],
        "attendance_events": attendance,
        "notifications": notifications,
        "skipped": skipped,
    }


@pytest.fixture(scope="module")
def starter_baseline() -> dict[str, pd.DataFrame]:
    return _build_baseline("starter")


@pytest.fixture(scope="module")
def full_baseline() -> dict[str, pd.DataFrame]:
    return _build_baseline("full")


def _checksum(tables: dict[str, pd.DataFrame]) -> str:
    digest = hashlib.sha256()
    for name in sorted(tables):
        frame = tables[name]
        digest.update(name.encode("utf-8"))
        digest.update(repr(tuple(frame.columns)).encode("utf-8"))
        digest.update(repr(tuple(map(str, frame.dtypes))).encode("utf-8"))
        if frame.empty:
            chunks = [(0, frame)]
        else:
            chunks = (
                (start, frame.iloc[start:start + 10_000])
                for start in range(0, len(frame), 10_000)
            )
        for start, chunk in chunks:
            buffer = io.StringIO()
            chunk.to_csv(
                buffer,
                header=start == 0,
                index=True,
                lineterminator="\n",
                na_rep="<NA>",
                date_format="%Y-%m-%dT%H:%M:%S.%f",
            )
            digest.update(buffer.getvalue().encode("utf-8"))
    return digest.hexdigest()


def _make_hard_negatives(
    baseline: dict[str, pd.DataFrame],
) -> dict[str, pd.DataFrame]:
    tables = {name: frame.copy(deep=True) for name, frame in baseline.items()}

    active_routes = tables["routes"].loc[
        tables["routes"]["status"].eq("active")
    ]
    route_bus_counts = active_routes["bus_id"].value_counts()
    single_bus_routes = active_routes.loc[
        active_routes["bus_id"].map(route_bus_counts).eq(1)
    ]
    loaded_route = None
    for _, route in single_bus_routes.iterrows():
        load = int(
            (
                tables["assignments"]["route_id"].eq(route["_id"])
                & tables["assignments"]["status"].eq("active")
            ).sum()
        )
        if load > 0:
            loaded_route = (route, load)
            break
    assert loaded_route is not None, "baseline needs a loaded route"
    route, exact_load = loaded_route
    bus_index = tables["buses"].index[
        tables["buses"]["_id"].eq(route["bus_id"])
    ][0]
    tables["buses"].at[bus_index, "capacity"] = exact_load

    route_stops = tables["route_stops"]
    tight_pair = None
    for route_id, group in route_stops.groupby("route_id", sort=True):
        ordered = group.sort_values("sequence", kind="stable")
        if len(ordered) < 2:
            continue
        previous = ordered.iloc[-2]
        current = ordered.iloc[-1]
        if pd.isna(current["travel_minutes_from_prev"]):
            continue
        travel = int(current["travel_minutes_from_prev"])
        if travel > 0:
            tight_pair = (previous, current, travel)
            break
    assert tight_pair is not None, "baseline needs a positive final travel leg"
    previous, current, travel = tight_pair
    previous_hour, previous_minute = map(
        int, str(previous["scheduled_time"]).split(":")
    )
    arrival = previous_hour * 60 + previous_minute + travel
    assert arrival < 24 * 60, "selected tight travel pair must fit in one day"
    current_index = route_stops.index[
        route_stops["_id"].eq(current["_id"])
    ][0]
    route_stops.at[current_index, "scheduled_time"] = (
        f"{arrival // 60:02d}:{arrival % 60:02d}"
    )

    assignment = tables["assignments"].loc[
        tables["assignments"]["status"].eq("active")
    ].iloc[0]
    assigned_route = tables["routes"].loc[
        tables["routes"]["_id"].eq(assignment["route_id"])
    ].iloc[0]
    student_index = tables["students"].index[
        tables["students"]["_id"].eq(assignment["student_id"])
    ][0]
    assigned_bus_index = tables["buses"].index[
        tables["buses"]["_id"].eq(assigned_route["bus_id"])
    ][0]
    tables["students"].at[student_index, "accessibility_required"] = True
    tables["buses"].at[assigned_bus_index, "is_accessible"] = True
    return tables


@pytest.mark.parametrize(
    ("fixture_name", "scale"),
    [("starter_baseline", "starter"), ("full_baseline", "full")],
)
def test_baseline_and_hard_negatives_have_no_violations(
    request: pytest.FixtureRequest, fixture_name: str, scale: str
) -> None:
    baseline = request.getfixturevalue(fixture_name)
    assert validate_dataset(baseline).empty
    assert validate_dataset(_make_hard_negatives(baseline)).empty


def test_integrity_rules_report_violations(
    starter_baseline: dict[str, pd.DataFrame],
) -> None:
    tables = {
        name: frame.copy(deep=True)
        for name, frame in starter_baseline.items()
    }

    tables["students"].loc[tables["students"].index[1], "_id"] = tables[
        "students"
    ].iloc[0]["_id"]
    tables["stops"].loc[tables["stops"].index[0], "zone_id"] = "ZONE-9999"
    tables["buses"].loc[tables["buses"].index[0], "status"] = "unknown"

    route = tables["routes"].loc[
        tables["routes"]["status"].eq("active")
    ].iloc[0]
    route_index = tables["routes"].index[
        tables["routes"]["_id"].eq(route["_id"])
    ][0]
    tables["routes"].at[route_index, "effective_to"] = route["effective_from"]
    tables["routes"]["previous_status"] = None
    tables["routes"].at[route_index, "previous_status"] = "cancelled"
    tables["routes"].at[route_index, "assignment_count"] = 999

    route_stop_group = next(
        group
        for _, group in tables["route_stops"].groupby("route_id", sort=True)
        if len(group) >= 2
    )
    first, second = route_stop_group.index[:2]
    tables["route_stops"].at[
        second, "sequence"
    ] = tables["route_stops"].at[first, "sequence"]
    tables["notifications"] = tables["notifications"].iloc[1:].copy()

    violations = validate_dataset(tables)
    rules = set(violations["rule_id"])
    assert {
        "pk_unique",
        "fk_stops_zone_id",
        "enum_buses_status",
        "effective_date_order",
        "lifecycle_transition_routes",
        "unique_route_stops_route_id_sequence",
        "reconcile_route_load",
        "reconcile_notifications",
    }.issubset(rules)


@pytest.mark.parametrize(
    ("fixture_name", "scale"),
    [("starter_baseline", "starter"), ("full_baseline", "full")],
)
def test_injected_data_metrics_and_summary(
    request: pytest.FixtureRequest,
    fixture_name: str,
    scale: str,
    tmp_path,
) -> None:
    baseline = request.getfixturevalue(fixture_name)
    checksum_before = _checksum(baseline)
    mutated, ground_truth = inject_anomalies(baseline, seed=SEED)

    assert _checksum(baseline) == checksum_before
    assert ground_truth["record_id"].is_unique
    assert set(ground_truth["issue_type"]) == set(ISSUE_TYPES)
    for table in mutated.values():
        assert "issue_type" not in table.columns
        assert "anomaly_id" not in table.columns
    for _, truth in ground_truth.iterrows():
        assert truth["record_id"] in set(mutated[truth["entity"]]["_id"])

    summary = evaluate_datasets(baseline, mutated, ground_truth)
    summary["scale"] = scale
    summary["injection_counts"] = {
        issue_type: {
            severity: int(
                (
                    ground_truth["issue_type"].eq(issue_type)
                    & ground_truth["severity"].eq(severity)
                ).sum()
            )
            for severity in ("boundary", "clear")
        }
        for issue_type in ISSUE_TYPES
    }
    assert summary["baseline_violations"] == []
    assert summary["baseline_violation_count"] == 0
    assert set(summary["rule_issue_type_mapping"].values()) == set(ISSUE_TYPES)
    assert {
        row["issue_type"]
        for row in summary["rule_results"]
        if row["issue_type"] is not None
    } == set(ISSUE_TYPES)
    metrics = pd.DataFrame(summary["issue_type_metrics"]).set_index("issue_type")
    assert set(metrics.index) == set(ISSUE_TYPES)
    assert (metrics["true_positives"] + metrics["false_negatives"]).gt(0).all()

    expected_counts = ground_truth.groupby("issue_type").size()
    for issue_type in ISSUE_TYPES:
        assert (
            metrics.loc[issue_type, "true_positives"]
            + metrics.loc[issue_type, "false_negatives"]
            == expected_counts.loc[issue_type]
        )

    report_path = write_validation_summary(summary, tmp_path)
    assert report_path.name == "validation_summary.json"
    assert report_path.exists()
    report = json.loads(report_path.read_text(encoding="ascii"))
    assert report["scale"] == scale
    assert report["baseline_violation_count"] == 0
    assert len(report["issue_type_metrics"]) == len(ISSUE_TYPES)

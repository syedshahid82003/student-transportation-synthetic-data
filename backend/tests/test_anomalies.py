"""Tests for deterministic anomaly injection at starter and full scale."""

from __future__ import annotations

import hashlib
import io
import json

import numpy as np
import pandas as pd
import pytest

from backend.app.core.config import SEED
from backend.app.generators.anomaly_injector import (
    GROUND_TRUTH_COLUMNS,
    ISSUE_TYPES,
    VALIDATION_RULES,
    detect_violations,
    inject_anomalies,
    validation_summary,
    write_ground_truth,
)
from backend.app.generators.attendance_generator import generate_attendance
from backend.app.generators.master_data import generate_master_data
from backend.app.generators.notification_generator import generate_notifications
from backend.app.generators.route_generator import generate_routes
from backend.app.services.assignment_service import assign_all_students


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
    notifications, _ = generate_notifications(
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


def _time_minutes(value: str) -> int:
    hour, minute = map(int, value.split(":"))
    return hour * 60 + minute


def _assert_anomalies(
    baseline: dict[str, pd.DataFrame],
    injected: dict[str, pd.DataFrame],
    ground_truth: pd.DataFrame,
    scale: str,
) -> None:
    assert list(ground_truth.columns) == GROUND_TRUTH_COLUMNS
    assert ground_truth["anomaly_id"].is_unique
    assert ground_truth["record_id"].is_unique
    assert set(ground_truth["issue_type"]) == set(ISSUE_TYPES)
    assert set(ground_truth["severity"]) == {"boundary", "clear"}

    grouped = ground_truth.groupby("issue_type")
    low, high = (6, 10) if scale == "starter" else (30, 50)
    for issue_type in ISSUE_TYPES:
        rows = grouped.get_group(issue_type)
        assert low <= len(rows) <= high
        assert set(rows["severity"]) == {"boundary", "clear"}

    label_columns = set(GROUND_TRUTH_COLUMNS)
    for name, frame in baseline.items():
        assert label_columns.isdisjoint(frame.columns), name
    for name, frame in injected.items():
        assert label_columns.isdisjoint(frame.columns), name

    for _, truth in ground_truth.iterrows():
        entity = truth["entity"]
        assert entity in injected
        assert truth["record_id"] in set(injected[entity]["_id"])

    violations = detect_violations(injected)
    summary = validation_summary(ground_truth, violations)
    assert set(violations["issue_type"]) == set(ISSUE_TYPES)
    assert set(VALIDATION_RULES) == set(ISSUE_TYPES)
    for issue_type in ISSUE_TYPES:
        detected = violations[violations["issue_type"].eq(issue_type)]
        expected = ground_truth[ground_truth["issue_type"].eq(issue_type)]
        assert detected["record_id"].is_unique
        assert len(detected) == len(expected)
    assert (summary["true_positives"] > 0).all()
    assert summary["false_positives"].eq(0).all()
    assert summary["false_negatives"].eq(0).all()
    assert summary["precision"].eq(1.0).all()
    assert summary["recall"].eq(1.0).all()

    for _, truth in grouped.get_group("bus_capacity_exceeded").iterrows():
        route = injected["routes"].set_index("_id").loc[truth["record_id"]]
        load = int(
            (
                injected["assignments"]["route_id"].eq(truth["record_id"])
                & injected["assignments"]["status"].eq("active")
            ).sum()
        )
        capacity = int(
            injected["buses"].set_index("_id").loc[route["bus_id"], "capacity"]
        )
        excess = load - capacity
        if truth["severity"] == "boundary":
            assert excess == 1
        else:
            assert excess >= 10

    for _, truth in grouped.get_group(
        "incompatible_accessibility_route"
    ).iterrows():
        assignment = injected["assignments"].set_index("_id").loc[
            truth["record_id"]
        ]
        student = injected["students"].set_index("_id").loc[
            assignment["student_id"]
        ]
        route = injected["routes"].set_index("_id").loc[assignment["route_id"]]
        bus = injected["buses"].set_index("_id").loc[route["bus_id"]]
        assert bool(student["accessibility_required"])
        assert not bool(bus["is_accessible"])
        if truth["severity"] == "clear":
            assert bus["status"] == "maintenance"
        else:
            assert bus["status"] == "active"
        route_stops = injected["route_stops"]
        assert not route_stops[
            route_stops["route_id"].eq(assignment["route_id"])
            & route_stops["stop_id"].eq(assignment["stop_id"])
        ].empty

    for _, truth in grouped.get_group(
        "impossible_sequential_travel_time"
    ).iterrows():
        stop = injected["route_stops"].set_index("_id").loc[truth["record_id"]]
        previous = injected["route_stops"][
            injected["route_stops"]["route_id"].eq(stop["route_id"])
            & injected["route_stops"]["sequence"].eq(stop["sequence"] - 1)
        ].iloc[0]
        arrival = _time_minutes(stop["scheduled_time"])
        previous_arrival = _time_minutes(previous["scheduled_time"])
        assert int(stop["travel_minutes_from_prev"]) > 0
        if truth["severity"] == "boundary":
            assert arrival == previous_arrival
        else:
            assert arrival <= previous_arrival - 10

    for _, truth in grouped.get_group(
        "notification_to_invalid_contact"
    ).iterrows():
        notification = injected["notifications"].set_index("_id").loc[
            truth["record_id"]
        ]
        contact = injected["guardian_contacts"].set_index("_id").loc[
            notification["guardian_id"]
        ]
        assert pd.notna(notification["sent_at"])
        expected_status = (
            "BOUNCED" if truth["severity"] == "boundary" else "INVALID"
        )
        assert contact["contact_status"] == expected_status
        assert not bool(contact["is_valid"])

    active_route_ids = set(
        injected["routes"].loc[
            injected["routes"]["status"].eq("active"), "_id"
        ]
    )
    for _, truth in grouped.get_group("unapproved_stop_exposed").iterrows():
        stop = injected["stops"].set_index("_id").loc[truth["record_id"]]
        exposed = injected["route_stops"][
            injected["route_stops"]["stop_id"].eq(truth["record_id"])
            & injected["route_stops"]["route_id"].isin(active_route_ids)
        ]
        assert not bool(stop["is_approved"])
        assert not exposed.empty
        if truth["severity"] == "clear":
            assert stop["status"] == "retired"

    total_rows = sum(len(frame) for frame in baseline.values())
    assert len(ground_truth) / total_rows < 0.005


@pytest.mark.parametrize(
    ("fixture_name", "scale"),
    [("starter_baseline", "starter"), ("full_baseline", "full")],
)
def test_counts_resolve_severity_and_baseline_checksum(
    request: pytest.FixtureRequest, fixture_name: str, scale: str
) -> None:
    baseline = request.getfixturevalue(fixture_name)
    before = _checksum(baseline)
    baseline_violations = detect_violations(baseline)
    assert baseline_violations.empty
    empty_truth = pd.DataFrame(columns=GROUND_TRUTH_COLUMNS)
    baseline_summary = validation_summary(empty_truth, baseline_violations)
    assert baseline_summary["true_positives"].eq(0).all()
    assert baseline_summary["false_positives"].eq(0).all()
    assert baseline_summary["false_negatives"].eq(0).all()

    injected, ground_truth = inject_anomalies(baseline)

    assert _checksum(baseline) == before
    _assert_anomalies(baseline, injected, ground_truth, scale)


@pytest.mark.parametrize("scale", ["starter", "full"])
def test_same_seed_produces_identical_ground_truth(
    request: pytest.FixtureRequest, scale: str
) -> None:
    baseline = request.getfixturevalue(f"{scale}_baseline")
    checksum_before = _checksum(baseline)
    _, first = inject_anomalies(baseline, seed=SEED)
    _, second = inject_anomalies(baseline, seed=SEED)
    pd.testing.assert_frame_equal(first, second, check_exact=True)
    assert _checksum(baseline) == checksum_before


def test_ground_truth_files_include_severity(
    starter_baseline: dict[str, pd.DataFrame], tmp_path
) -> None:
    _, ground_truth = inject_anomalies(starter_baseline)
    csv_path, json_path = write_ground_truth(ground_truth, tmp_path)

    csv_truth = pd.read_csv(csv_path, dtype={"record_id": str})
    json_truth = pd.DataFrame(json.loads(json_path.read_text(encoding="utf-8")))
    assert csv_path.name == "ground_truth.csv"
    assert json_path.name == "ground_truth.json"
    assert list(csv_truth.columns) == GROUND_TRUTH_COLUMNS
    assert list(json_truth.columns) == GROUND_TRUTH_COLUMNS
    pd.testing.assert_frame_equal(
        csv_truth.astype(str), ground_truth.astype(str), check_exact=True
    )
    pd.testing.assert_frame_equal(
        json_truth.astype(str), ground_truth.astype(str), check_exact=True
    )

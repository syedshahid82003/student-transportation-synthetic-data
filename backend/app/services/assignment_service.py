"""
backend/app/services/assignment_service.py
-------------------------------------------
Assignment engine for the Student Transportation system.

Design rules
------------
* Fully deterministic: caller supplies the rng (numpy.random.default_rng).
* No global random state.
* Never overwrites existing assignments — reassignments go to audit_events.
* ground_truth directory is never read.
* Every validation check is an independent rule that returns a named error code.
* Students with no valid assignment get a traceable rejection record.
* Every successful assignment also writes an audit_event row.
"""

from __future__ import annotations

import datetime
import string
from typing import Any

import numpy as np
import pandas as pd

from backend.app.core.config import SCHOOL_YEAR
from backend.app.core.ids import assignment_id

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_NOW   = datetime.datetime(2025, 9, 1, 0, 0, 0)
_EFF   = datetime.date(2025, 9, 1)
ACTOR  = "assignment_engine"


# ---------------------------------------------------------------------------
# Error codes (one per validation rule)
# ---------------------------------------------------------------------------

class ErrorCode:
    BUS_CAPACITY_EXCEEDED        = "BUS_CAPACITY_EXCEEDED"
    ACCESSIBILITY_MISMATCH       = "ACCESSIBILITY_MISMATCH"
    UNAPPROVED_STOP              = "UNAPPROVED_STOP"
    ZONE_MISMATCH                = "ZONE_MISMATCH"
    INACTIVE_ROUTE               = "INACTIVE_ROUTE"
    STOP_NOT_ON_ROUTE            = "STOP_NOT_ON_ROUTE"
    PICKUP_WINDOW_VIOLATION      = "PICKUP_WINDOW_VIOLATION"
    ROUTE_INFEASIBLE             = "ROUTE_INFEASIBLE"
    EFFECTIVE_DATE_INVALID       = "EFFECTIVE_DATE_INVALID"
    STUDENT_INACTIVE             = "STUDENT_INACTIVE"
    ACCESSIBLE_ROUTE_UNAVAILABLE = "ACCESSIBLE_ROUTE_UNAVAILABLE"


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _hhmm_to_minutes(hhmm: str) -> int:
    h, m = map(int, hhmm.split(":"))
    return h * 60 + m


def _route_stop_key(route_id: str, stop_id: str) -> str:
    return f"{route_id}::{stop_id}"


# ---------------------------------------------------------------------------
# validate_assignment
# ---------------------------------------------------------------------------


def validate_assignment(
    student: dict[str, Any],
    route: dict[str, Any],
    stop: dict[str, Any],
    bus: dict[str, Any],
    route_stop: dict[str, Any],
    current_load: int,
) -> dict[str, Any]:
    """Validate a proposed (student, route, stop) assignment.

    Each check is an independent rule.  All failing rules are collected; the
    function does NOT short-circuit on the first failure.

    Parameters
    ----------
    student :
        Row dict from students DataFrame.
    route :
        Row dict from routes DataFrame.
    stop :
        Row dict from stops DataFrame.
    bus :
        Row dict from buses DataFrame.
    route_stop :
        Row dict from route_stops for (route._id, stop._id).
    current_load :
        Number of students already assigned to this route.

    Returns
    -------
    dict with keys:
        valid        bool  — True only when no error codes
        error_codes  list[str]
        messages     list[str]  — human-readable explanation per code
    """
    error_codes: list[str] = []
    messages:    list[str] = []

    def _add(code: str, msg: str) -> None:
        error_codes.append(code)
        messages.append(msg)

    # Rule 1: Student must be active
    if student.get("status") != "active":
        _add(
            ErrorCode.STUDENT_INACTIVE,
            f"Student {student.get('_id')} is not active (status={student.get('status')}).",
        )

    # Rule 2: Route must be active
    if route.get("status") != "active":
        _add(
            ErrorCode.INACTIVE_ROUTE,
            f"Route {route.get('_id')} is not active (status={route.get('status')}).",
        )

    # Rule 3: Route must be feasible
    if not route.get("is_feasible", True):
        _add(
            ErrorCode.ROUTE_INFEASIBLE,
            f"Route {route.get('_id')} is marked infeasible.",
        )

    # Rule 4: Stop must be approved
    if not stop.get("is_approved", False):
        _add(
            ErrorCode.UNAPPROVED_STOP,
            f"Stop {stop.get('_id')} is not approved.",
        )

    # Rule 5: Stop must be on the route
    if not route_stop:
        _add(
            ErrorCode.STOP_NOT_ON_ROUTE,
            f"Stop {stop.get('_id')} is not on route {route.get('_id')}.",
        )

    # Rule 6: Bus capacity must not be exceeded
    capacity = bus.get("capacity", 0)
    if current_load >= capacity:
        _add(
            ErrorCode.BUS_CAPACITY_EXCEEDED,
            f"Bus {bus.get('_id')} capacity {capacity} already reached "
            f"(current load: {current_load}).",
        )

    # Rule 7: Accessibility must match
    if student.get("accessibility_required", False) and not bus.get("is_accessible", False):
        _add(
            ErrorCode.ACCESSIBILITY_MISMATCH,
            f"Student {student.get('_id')} requires an accessible bus but "
            f"bus {bus.get('_id')} is not accessible.",
        )

    # Rule 8: Zone must match (student.zone_id must be in the route's served zones)
    # We approximate by checking student zone == stop zone.
    if student.get("zone_id") != stop.get("zone_id"):
        _add(
            ErrorCode.ZONE_MISMATCH,
            f"Student zone {student.get('zone_id')} does not match "
            f"stop zone {stop.get('zone_id')}.",
        )

    # Rule 9: Pickup window — student's stop scheduled_time must be within window
    if route_stop:
        sched = route_stop.get("scheduled_time", "")
        win_start = route.get("pickup_window_start", "00:00")
        win_end   = route.get("pickup_window_end",   "23:59")
        if sched and not (
            _hhmm_to_minutes(win_start)
            <= _hhmm_to_minutes(sched)
            <= _hhmm_to_minutes(win_end)
        ):
            _add(
                ErrorCode.PICKUP_WINDOW_VIOLATION,
                f"Stop scheduled time {sched} is outside pickup window "
                f"[{win_start}, {win_end}].",
            )

    # Rule 10: Effective date — route's effective_from must be ≤ today
    eff_from = route.get("effective_from")
    if eff_from is not None:
        eff_date = eff_from if isinstance(eff_from, datetime.date) else eff_from.date()
        if eff_date > _EFF:
            _add(
                ErrorCode.EFFECTIVE_DATE_INVALID,
                f"Route {route.get('_id')} effective_from {eff_date} is in the future.",
            )

    return {
        "valid":       len(error_codes) == 0,
        "error_codes": error_codes,
        "messages":    messages,
    }


# ---------------------------------------------------------------------------
# Audit event builder
# ---------------------------------------------------------------------------


def _make_audit_id(seq: int) -> str:
    ts  = _NOW.strftime("%Y%m%d%H%M%S")
    sfx = f"{seq:08X}"[:8]
    return f"AUD-{ts}-{sfx}"


def _build_audit_event(
    seq: int,
    document_id: str,
    collection: str,
    action: str,
    after_state: dict | None = None,
) -> dict[str, Any]:
    return {
        "_id":             _make_audit_id(seq),
        "collection_name": collection,
        "document_id":     document_id,
        "action":          action,
        "actor":           ACTOR,
        "timestamp":       _NOW,
        "before_state":    None,
        "after_state":     after_state,
        "changed_fields":  list(after_state.keys()) if after_state else [],
    }


# ---------------------------------------------------------------------------
# assign_all_students
# ---------------------------------------------------------------------------


def assign_all_students(
    master: dict[str, pd.DataFrame],
    routes_df: pd.DataFrame,
    route_stops_df: pd.DataFrame,
    rng: np.random.Generator,
) -> dict[str, pd.DataFrame]:
    """Assign every student to a route deterministically.

    Selection criteria (in priority order)
    ---------------------------------------
    1. Route is active and feasible.
    2. Bus is accessible if student.accessibility_required.
    3. At least one stop on the route is in the student's zone (approved).
    4. Among valid candidates, prefer the stop with fewest cumulative
       travel_minutes (shortest ride).
    5. Among equal-travel candidates, prefer the route with most spare capacity.

    Students with no valid option are recorded in a rejections table.

    Every successful assignment also generates an audit_event row.

    Parameters
    ----------
    master :
        Dict returned by generate_master_data().
    routes_df, route_stops_df :
        Outputs of generate_routes().
    rng :
        Caller-supplied seeded Generator (not used for logic, only for any
        future tie-breaking; kept for interface consistency).

    Returns
    -------
    dict with keys:
        "assignments"  : pd.DataFrame
        "rejections"   : pd.DataFrame
        "audit_events" : pd.DataFrame
    """
    students_df = master["students"]
    stops_df    = master["stops"]
    buses_df    = master["buses"]

    # ---- Index building ----
    bus_lookup:   dict[str, dict] = {r["_id"]: r for r in buses_df.to_dict("records")}
    stop_lookup:  dict[str, dict] = {r["_id"]: r for r in stops_df.to_dict("records")}

    # Approved stops indexed by zone
    approved_stops_by_zone: dict[str, list[dict]] = {}
    for s in stops_df[stops_df["is_approved"]].to_dict("records"):
        approved_stops_by_zone.setdefault(s["zone_id"], []).append(s)

    # Active feasible routes
    active_routes = routes_df[
        (routes_df["status"] == "active") & (routes_df["is_feasible"])
    ].to_dict("records")

    # route_stops indexed by (route_id, stop_id)
    rs_by_route_stop: dict[str, dict] = {}
    rs_by_route:      dict[str, list[dict]] = {}
    for rs in route_stops_df.to_dict("records"):
        key = _route_stop_key(rs["route_id"], rs["stop_id"])
        rs_by_route_stop[key] = rs
        rs_by_route.setdefault(rs["route_id"], []).append(rs)

    # Running load per route
    load: dict[str, int] = {r["_id"]: 0 for r in active_routes}

    assignment_rows: list[dict] = []
    rejection_rows:  list[dict] = []
    audit_rows:      list[dict] = []
    audit_seq = 1

    # Deterministic order: sort by student _id (lexicographic = numeric order)
    # Deterministic order: accessibility students first, then by _id
    ordered_students = (
        students_df
        .assign(_k=~students_df["accessibility_required"].astype(bool))
        .sort_values(["_k", "_id"])
        .drop(columns="_k")
        .to_dict("records")
    )


    for student in ordered_students:
        stu_id    = student["_id"]
        zone_id   = student["zone_id"]
        needs_acc = bool(student.get("accessibility_required", False))
        stu_status = student.get("status", "active")

        # Collect candidate (route, stop, route_stop) triples
        best: dict | None = None

        for route in active_routes:
            r_id   = route["_id"]
            bus_id = route["bus_id"]
            bus    = bus_lookup.get(bus_id, {})

            # Accessibility filter
            if needs_acc and not bus.get("is_accessible", False):
                continue

            # Capacity filter
            current_load = load.get(r_id, 0)
            cap = bus.get("capacity", 0)
            if current_load >= cap:
                continue

            # Find stops on this route in student's zone
            route_rs = rs_by_route.get(r_id, [])
            for rs in route_rs:
                s_id = rs["stop_id"]
                stop = stop_lookup.get(s_id, {})
                if stop.get("zone_id") != zone_id:
                    continue
                if not stop.get("is_approved", False):
                    continue

                travel = rs.get("travel_minutes_from_prev") or 0
                spare  = cap - current_load

                if best is None:
                    best = {"route": route, "stop": stop, "rs": rs,
                            "travel": travel, "spare": spare}
                else:
                    # Prefer fewer travel minutes, then more spare capacity
                    if travel < best["travel"] or (
                        travel == best["travel"] and spare > best["spare"]
                    ):
                        best = {"route": route, "stop": stop, "rs": rs,
                                "travel": travel, "spare": spare}

        if best is None:
            # No valid assignment — build rejection record
            if stu_status != "active":
                rej_codes  = [ErrorCode.STUDENT_INACTIVE]
                rej_reason = "Student is not active."
            elif needs_acc:
                rej_codes  = [ErrorCode.ACCESSIBLE_ROUTE_UNAVAILABLE]
                rej_reason = (
                    "No active feasible route on an accessible bus with an "
                    "approved stop in the student's zone has spare capacity. "
                    "This is a documented exception: the zone may not be "
                    "covered by an accessible route within the ride-time limit."
                )
            else:
                rej_codes  = ["NO_ELIGIBLE_ROUTE"]
                rej_reason = (
                    "No active feasible route with an approved stop in the "
                    "student's zone with spare capacity."
                )
            rejection_rows.append({
                "student_id":         stu_id,
                "attempted_route_id": None,
                "error_codes":        rej_codes,
                "reason":             rej_reason,
                "created_at":         _NOW,
            })
            continue

        # Build assignment
        route     = best["route"]
        stop      = best["stop"]
        rs        = best["rs"]
        r_id      = route["_id"]
        s_id      = stop["_id"]
        asn_id    = assignment_id(stu_id, SCHOOL_YEAR)

        asn_row: dict[str, Any] = {
            "_id":          asn_id,
            "student_id":   stu_id,
            "route_id":     r_id,
            "stop_id":      s_id,
            "status":       "active",
            "effective_from": _EFF,
            "effective_to":   None,
            "academic_year":  SCHOOL_YEAR,
            "created_at":   _NOW,
            "updated_at":   _NOW,
        }
        assignment_rows.append(asn_row)
        load[r_id] = load.get(r_id, 0) + 1

        # Audit event for the assignment insert
        audit_rows.append(
            _build_audit_event(
                audit_seq,
                asn_id,
                "assignments",
                "insert",
                after_state=asn_row,
            )
        )
        audit_seq += 1

    assignments_df = pd.DataFrame(assignment_rows) if assignment_rows else pd.DataFrame(
        columns=["_id", "student_id", "route_id", "stop_id", "status",
                 "effective_from", "effective_to", "academic_year",
                 "created_at", "updated_at"]
    )
    rejections_df  = pd.DataFrame(rejection_rows) if rejection_rows else pd.DataFrame(
        columns=["student_id", "attempted_route_id", "error_codes", "reason", "created_at"]
    )
    audit_df = pd.DataFrame(audit_rows) if audit_rows else pd.DataFrame(
        columns=["_id", "collection_name", "document_id", "action",
                 "actor", "timestamp", "before_state", "after_state", "changed_fields"]
    )

    return {
        "assignments":  assignments_df,
        "rejections":   rejections_df,
        "audit_events": audit_df,
    }

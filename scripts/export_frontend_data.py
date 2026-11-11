"""
scripts/export_frontend_data.py
---------------------------------
Export synthetic dataset for the frontend dashboard.

Run from repo root:
    python scripts/export_frontend_data.py

Writes JSON files into frontend/public/data/.
Uses DATA_SCALE=starter and seed 20261022.
Does not import ground_truth or anomaly code.
"""

from __future__ import annotations

import datetime
import json
import os
import pathlib
import sys

os.environ["DATA_SCALE"] = "starter"

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np

from backend.app.core.config import SEED, SCALES, get_school_days
from backend.app.generators.master_data import generate_master_data
from backend.app.generators.route_generator import generate_routes
from backend.app.services.assignment_service import assign_all_students
from backend.app.services.capacity_service import (
    build_capacity_history,
    compute_utilisation,
    _EFF_START,
)
from backend.app.generators.attendance_generator import generate_attendance
from backend.app.generators.notification_generator import generate_notifications

OUT_DIR = ROOT / "frontend" / "public" / "data"
OUT_DIR.mkdir(parents=True, exist_ok=True)

SCALE = "starter"


def _dt(v) -> str | None:
    if v is None:
        return None
    if hasattr(v, "isoformat"):
        return v.isoformat()
    return str(v)


def _mask_phone(phone: str) -> str:
    digits = "".join(c for c in str(phone) if c.isdigit())
    if len(digits) >= 4:
        return "***-***-" + digits[-4:]
    return "****"


def _mask_email(email: str) -> str:
    if isinstance(email, str) and "@" in email:
        _, domain = email.split("@", 1)
        return "***@" + domain
    return "***"


def _write(name: str, obj) -> None:
    path = OUT_DIR / name
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=2, default=str)
    print(f"  wrote {path.name}  ({path.stat().st_size:,} bytes)")


def _to_date(v):
    import pandas as pd
    if isinstance(v, datetime.datetime):
        return v.date()
    if isinstance(v, datetime.date):
        return v
    return pd.Timestamp(v).date()


print("Building starter dataset (seed 20261022)...")

master = generate_master_data(SCALE)
rng_routes = np.random.default_rng(SEED)
routes_df, route_stops_df = generate_routes(
    master["buses"], master["drivers"],
    master["stops"], master["students"], rng_routes,
)
rng_asn = np.random.default_rng(SEED)
assign_result = assign_all_students(master, routes_df, route_stops_df, rng_asn)
assignments_df = assign_result["assignments"]
rejections_df  = assign_result["rejections"]

cap_history = build_capacity_history(master["buses"])
utilisation  = compute_utilisation(routes_df, assignments_df, cap_history, _EFF_START)

rng_att = np.random.default_rng(SEED)
att_df, disr_df = generate_attendance(
    assignments_df, master["students"],
    routes_df, master["buses"],
    scale=SCALE, rng=rng_att,
)

rng_not = np.random.default_rng(SEED)
notif_df, skipped_df = generate_notifications(
    att_df, master["students"], master["guardian_contacts"], rng=rng_not,
)

n_days = SCALES[SCALE]["school_days"]
school_days = get_school_days(n_days=n_days)

print("Exporting JSON files...")

# routes.json
util_map = {r["route_id"]: r for r in utilisation.to_dict("records")}
bus_map  = {r["_id"]: r for r in master["buses"].to_dict("records")}

routes_out = []
for r in routes_df.to_dict("records"):
    rid  = r["_id"]
    bid  = r.get("bus_id", "")
    bus  = bus_map.get(bid, {})
    util = util_map.get(rid, {})
    routes_out.append({
        "id":                   rid,
        "name":                 r.get("name", rid),
        "bus_id":               bid,
        "bus_license_plate":    bus.get("license_plate", ""),
        "bus_is_accessible":    bool(bus.get("is_accessible", False)),
        "bus_capacity_initial": int(bus.get("capacity", 0)),
        "driver_id":            r.get("driver_id", ""),
        "direction":            r.get("direction", ""),
        "status":               r.get("status", ""),
        "pickup_window_start":  r.get("pickup_window_start", ""),
        "pickup_window_end":    r.get("pickup_window_end", ""),
        "is_feasible":          bool(r.get("is_feasible", True)),
        "total_travel_minutes": int(r.get("total_travel_minutes", 0)) if r.get("total_travel_minutes") else 0,
        "served_zone_ids":      list(r.get("served_zone_ids", [])),
        "effective_from":       _dt(r.get("effective_from")),
        "utilisation": {
            "capacity":          util.get("capacity", int(bus.get("capacity", 0))),
            "assigned_students": util.get("assigned_students", 0),
            "seats_available":   util.get("seats_available", 0),
            "utilisation_pct":   util.get("utilisation_pct", 0.0),
        },
    })
_write("routes.json", routes_out)

# route_stops.json
rs_out = []
for rs in route_stops_df.to_dict("records"):
    tmin = rs.get("travel_minutes_from_prev")
    rs_out.append({
        "id":                       rs["_id"],
        "route_id":                 rs["route_id"],
        "stop_id":                  rs["stop_id"],
        "sequence":                 int(rs["sequence"]),
        "travel_minutes_from_prev": None if tmin is None or (hasattr(tmin, "__class__") and str(type(tmin)) == "<class 'float'>" and tmin != tmin) else tmin,
        "scheduled_time":           rs.get("scheduled_time", ""),
    })
_write("route_stops.json", rs_out)

# assignments.json
asn_out = []
for a in assignments_df.to_dict("records"):
    asn_out.append({
        "id":            a["_id"],
        "student_id":    a["student_id"],
        "route_id":      a["route_id"],
        "stop_id":       a["stop_id"],
        "status":        a["status"],
        "effective_from": _dt(a.get("effective_from")),
        "effective_to":   _dt(a.get("effective_to")),
        "academic_year":  a.get("academic_year"),
    })
_write("assignments.json", asn_out)

# rejections.json
rej_out = []
for r in rejections_df.to_dict("records"):
    codes = r.get("error_codes", [])
    if not isinstance(codes, list):
        codes = [codes] if codes else []
    rej_out.append({
        "student_id":         r["student_id"],
        "attempted_route_id": r.get("attempted_route_id", ""),
        "error_codes":        codes,
        "reason":             r.get("reason", ""),
    })
_write("rejections.json", rej_out)

# attendance_summary.json
active_asn_count = int((assignments_df["status"] == "active").sum())
disr_by_day: dict[str, list[dict]] = {}
if not disr_df.empty:
    for d in disr_df.to_dict("records"):
        day_str = _to_date(d["date"]).isoformat()
        disr_by_day.setdefault(day_str, []).append(d)

WEEKDAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
att_summary = []
for day in school_days:
    day_str  = day.isoformat()
    day_att  = att_df[att_df["date"].apply(_to_date) == day]
    total    = len(day_att)
    boarded  = int((day_att["event_type"] == "boarded").sum())
    absent   = int((day_att["event_type"] == "absent").sum())
    no_show  = int((day_att["event_type"] == "no_show").sum())
    late_p   = int((day_att["event_type"] == "late_pickup").sum())
    att_rate = round(boarded / active_asn_count, 4) if active_asn_count else 0.0
    disrs    = disr_by_day.get(day_str, [])
    att_summary.append({
        "date":                  day_str,
        "weekday":               WEEKDAY_NAMES[day.weekday()],
        "total_events":          total,
        "boarded":               boarded,
        "absent":                absent,
        "no_show":               no_show,
        "late_pickup":           late_p,
        "attendance_rate":       att_rate,
        "disruptions_delay":     sum(1 for d in disrs if d.get("type") == "DELAY"),
        "disruptions_cancelled": sum(1 for d in disrs if d.get("type") == "CANCELLED"),
        "has_disruption":        len(disrs) > 0,
    })
_write("attendance_summary.json", att_summary)

# disruptions.json
disr_out = []
if not disr_df.empty:
    for d in disr_df.to_dict("records"):
        disr_out.append({
            "disruption_id": d["disruption_id"],
            "route_id":      d["route_id"],
            "date":          _to_date(d["date"]).isoformat(),
            "type":          d["type"],
            "reason":        d["reason"],
        })
_write("disruptions.json", disr_out)

# notifications.json
grd_map = {g["_id"]: g for g in master["guardian_contacts"].to_dict("records")}
notif_out = []
if not notif_df.empty:
    for n in notif_df.to_dict("records"):
        grd = grd_map.get(n["guardian_id"], {})
        notif_out.append({
            "id":                    n["_id"],
            "guardian_id":           n["guardian_id"],
            "guardian_masked_phone": _mask_phone(grd.get("phone_primary", "")),
            "guardian_masked_email": _mask_email(grd.get("email", "")),
            "guardian_prefs":        list(grd.get("notification_preferences", [])),
            "student_id":            n["student_id"],
            "event_id":              n["event_id"],
            "event_collection":      n["event_collection"],
            "channel":               n["channel"],
            "status":                n["status"],
            "sent_at":               _dt(n.get("sent_at")),
            "delivered_at":          _dt(n.get("delivered_at")),
            "failed_at":             _dt(n.get("failed_at")),
            "failure_reason":        n.get("failure_reason"),
            "template_id":           n.get("template_id"),
        })
skip_out = []
if not skipped_df.empty:
    for s in skipped_df.to_dict("records"):
        d_val = s.get("date")
        skip_out.append({
            "student_id": s["student_id"],
            "event_id":   s["event_id"],
            "event_type": s["event_type"],
            "date":       _to_date(d_val).isoformat() if d_val is not None else None,
            "reason":     s["reason"],
        })
_write("notifications.json", {"sent": notif_out, "skipped": skip_out})

# capacity_history.json
cap_out = []
for c in cap_history.to_dict("records"):
    cap_out.append({
        "id":            c["_id"],
        "bus_id":        c["bus_id"],
        "capacity":      int(c["capacity"]),
        "is_accessible": bool(c.get("is_accessible", False)),
        "reason":        c.get("reason", ""),
        "effective_from": _dt(c.get("effective_from")),
        "effective_to":   _dt(c.get("effective_to")),
        "changed_by":    c.get("changed_by", ""),
    })
_write("capacity_history.json", cap_out)

# student_index.json
asn_active = assignments_df[assignments_df["status"] == "active"]
asn_index = {}
for _, row in asn_active.iterrows():
    asn_index[row["student_id"]] = {
        "assignment_id": row["_id"],
        "route_id":      row["route_id"],
        "stop_id":       row["stop_id"],
        "status":        row["status"],
    }
_write("student_index.json", asn_index)

# attendance_by_student.json
stu_att: dict[str, list[dict]] = {}
for _, row in att_df.iterrows():
    sid = row["student_id"]
    if sid not in stu_att:
        stu_att[sid] = []
    stu_att[sid].append({
        "event_id":   row["_id"],
        "date":       _to_date(row["date"]).isoformat(),
        "event_type": row["event_type"],
        "route_id":   row["route_id"],
        "stop_id":    row["stop_id"],
        "notes":      row.get("notes"),
    })
_write("attendance_by_student.json", stu_att)

# notifications_by_student.json
notif_by_stu: dict[str, list[dict]] = {}
if not notif_df.empty:
    for _, row in notif_df.iterrows():
        sid = row["student_id"]
        if sid not in notif_by_stu:
            notif_by_stu[sid] = []
        notif_by_stu[sid].append({
            "notification_id": row["_id"],
            "event_id":        row["event_id"],
            "channel":         row["channel"],
            "status":          row["status"],
            "sent_at":         _dt(row.get("sent_at")),
        })
_write("notifications_by_student.json", notif_by_stu)

# metrics.json
n_students  = int(SCALES[SCALE]["students"])
n_assigned  = int((assignments_df["status"] == "active").sum())
n_rejected  = len(rejections_df)
n_inactive  = int((assignments_df["status"] != "active").sum())
n_routes    = int((routes_df["status"] == "active").sum())
n_buses     = int(len(master["buses"]))
n_stops     = int(len(master["stops"]))

total_events   = len(att_df)
total_boarded  = int((att_df["event_type"] == "boarded").sum())
total_absent   = int((att_df["event_type"] == "absent").sum())
total_no_show  = int((att_df["event_type"] == "no_show").sum())
total_late     = int((att_df["event_type"] == "late_pickup").sum())
overall_rate   = round(total_boarded / (active_asn_count * n_days), 4) if active_asn_count else 0.0

n_disrs        = len(disr_df) if not disr_df.empty else 0
n_disrs_cancel = int((disr_df["type"] == "CANCELLED").sum()) if not disr_df.empty else 0
n_disrs_delay  = int((disr_df["type"] == "DELAY").sum())    if not disr_df.empty else 0

n_notif_sent      = len(notif_df) if not notif_df.empty else 0
n_notif_delivered = int((notif_df["status"] == "delivered").sum()) if not notif_df.empty else 0
n_notif_failed    = int((notif_df["status"] == "failed").sum())    if not notif_df.empty else 0
n_notif_skipped   = len(skipped_df)

metrics = {
    "generated_at":       datetime.datetime.utcnow().isoformat() + "Z",
    "scale":              SCALE,
    "seed":               SEED,
    "school_days":        n_days,
    "students_total":     n_students,
    "students_assigned":  n_assigned,
    "students_rejected":  n_rejected,
    "students_inactive_assignment": n_inactive,
    "routes_active":      n_routes,
    "buses_total":        n_buses,
    "stops_total":        n_stops,
    "attendance": {
        "total_events": total_events,
        "boarded":      total_boarded,
        "absent":       total_absent,
        "no_show":      total_no_show,
        "late_pickup":  total_late,
        "overall_rate": overall_rate,
    },
    "disruptions": {
        "total":     n_disrs,
        "cancelled": n_disrs_cancel,
        "delay":     n_disrs_delay,
    },
    "notifications": {
        "sent":      n_notif_sent,
        "delivered": n_notif_delivered,
        "failed":    n_notif_failed,
        "skipped":   n_notif_skipped,
    },
}
_write("metrics.json", metrics)

gt_dir = OUT_DIR / "ground_truth"
gt_dir.mkdir(exist_ok=True)
gt_ph = gt_dir / "README.json"
if not gt_ph.exists():
    with open(gt_ph, "w") as fh:
        json.dump({"status": "empty", "note": "Ground-truth data not yet generated."}, fh, indent=2)

print("\nDone. All files written to frontend/public/data/")

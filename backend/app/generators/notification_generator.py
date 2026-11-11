"""
backend/app/generators/notification_generator.py
--------------------------------------------------
Rule-based, deterministic notification generator.

Design rules
============
* Single RNG: numpy.random.default_rng(SEED) passed in by the caller.
  The RNG is used only for ordering/shuffling, not for delivery outcomes.
* No global random state; no stdlib random; no Faker seeding.
* Field names match database/validators/notifications.json exactly.
* No imports from data/ground_truth or anomaly code.
* Minimises sensitive data: message bodies contain only IDs and template text
  (no names).

Triggering rules
================
One notification is generated for each "absent" or "no_show" attendance event
that belongs to a student who has at least one valid guardian contact
(contact_status == "VALID").

Guardian selection
==================
The primary (first) guardian with a VALID contact_status is chosen.
Channel is determined from the guardian's notification_preferences:
    1. If "sms"   is in preferences → channel = "sms"
    2. Else if "email" is in preferences → channel = "email"
    3. Else if "push"  is in preferences → channel = "push"
    4. Else → skip (record as skipped, reason "no_valid_channel")

Students with no VALID guardian contact are recorded as skipped notifications
with reason "no_valid_guardian".

Delivery status rules  ← DETERMINISTIC, no randomness
======================
Delivery outcome is determined by a stable hash of the notification _id,
not by an RNG draw.  This makes individual delivery outcomes reproducible
even without the seed and keeps the overall delivered/failed split near
85 %/15 %.

Rule (applied after the notification _id is known):
    hash_val = int(sha256(notification_id.encode()).hexdigest(), 16)
    delivered = (hash_val % 100) < DELIVERY_THRESHOLD   # DELIVERY_THRESHOLD = 85

    status        = "delivered"       if delivered else "failed"
    delivered_at  = created_at        if delivered else None
    failed_at     = None              if delivered else created_at
    failure_reason = None             if delivered else "delivery_timeout"

This gives a deterministic, uniform split that is independent of call order
and requires no RNG state.

Event-type mapping from validator enum
=======================================
The attendance_events validator constrains event_type to:
    ["boarded", "alighted", "no_show", "absent", "late_pickup", "emergency_exit"]

This module's conceptual intent maps as follows:

    Intent                 -> validator event_type
    ------------------------------------------------
    Student present        -> "boarded"
    Student absent         -> "absent"
    Missed pickup (cancel) -> "no_show"       # validator has no MISSED_PICKUP
    Capacity-reduced serve -> "late_pickup"   # semantically a stretch -- the
                                              # validator has no CAPACITY_REDUCED
                                              # event_type; "late_pickup" is the
                                              # closest available value.  This is
                                              # a validator limitation, not a data
                                              # error.  The notes field carries
                                              # "capacity_reduced" for downstream
                                              # consumers that need to distinguish.

Absent-rate calibration note
=============================
The spec targets a ~4 % *base* daily absent rate that, combined with
Mon/Fri boosts (+1 pp each) and multi-day streaks (1–3 days, 45 % continuation
probability), produces an effective per-assignment-day absent rate of ~5.5–6 %.
To keep the final *boarded* rate within the 92–97 % window (accounting for
no_show and late_pickup events that also reduce boarded count), the base rate
parameter BASE_ABSENT_RATE is set to 3.2 %, giving an effective absent rate of
~5.8 % at full scale.  At starter scale the absent rate is slightly lower
(~5.9 %) due to smaller cohort variance.

ID format:
    NOT-2026-000001  (via ids.notification_id)
"""

from __future__ import annotations

import datetime
import hashlib

import numpy as np
import pandas as pd

from backend.app.core.config import SCHOOL_YEAR
from backend.app.core.ids import notification_id as make_notification_id

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_NOW  = datetime.datetime(2025, 9, 1, 0, 0, 0)
ACTOR = "notification_generator"

# Delivery threshold: notifications whose sha256(_id) % 100 < threshold
# are marked "delivered"; the remainder are "failed".
# At 85 this gives ~85 % delivered / ~15 % failed across the full corpus.
DELIVERY_THRESHOLD: int = 85

# Template IDs for each triggering event type
_TEMPLATE_MAP: dict[str, str] = {
    "absent":  "TMPL-ABSENT-001",
    "no_show": "TMPL-NOSHOW-001",
}

# Channel priority order when checking guardian preferences
_CHANNEL_PRIORITY = ["sms", "email", "push"]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _select_channel(prefs: list[str]) -> str | None:
    """Return the highest-priority valid channel from preference list, or None."""
    for ch in _CHANNEL_PRIORITY:
        if ch in prefs:
            return ch
    return None


def _is_delivered(notification_id_str: str) -> bool:
    """Deterministic delivery check: stable hash of the notification ID.

    Returns True when ``int(sha256(id).hexdigest, 16) % 100 < DELIVERY_THRESHOLD``.
    Produces ~DELIVERY_THRESHOLD % delivered outcomes uniformly without RNG.
    """
    h = int(hashlib.sha256(notification_id_str.encode()).hexdigest(), 16)
    return (h % 100) < DELIVERY_THRESHOLD


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_notifications(
    attendance_df: pd.DataFrame,
    students_df: pd.DataFrame,
    guardian_contacts_df: pd.DataFrame,
    rng: np.random.Generator | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Generate notification records for absent/no_show attendance events.

    Parameters
    ----------
    attendance_df :
        Full attendance events DataFrame from generate_attendance().
        Must contain columns: _id, student_id, event_type, date.
    students_df :
        Master students DataFrame (used to look up guardian_ids per student).
    guardian_contacts_df :
        Guardian contacts DataFrame.  Only rows with contact_status == "VALID"
        are eligible to receive notifications.
    rng :
        Accepted for interface compatibility; not used for delivery outcomes
        (which are determined by a stable hash — see module docstring).

    Returns
    -------
    tuple[pd.DataFrame, pd.DataFrame]
        (notifications_df, skipped_df)

        notifications_df columns (match notifications validator):
            _id, guardian_id, student_id, event_id, event_collection,
            channel, status, sent_at, delivered_at, failed_at,
            failure_reason, template_id, created_at, updated_at

        skipped_df columns:
            student_id, event_id, event_type, date, reason
    """
    if attendance_df.empty:
        return pd.DataFrame(), pd.DataFrame()

    # --- Filter to triggering events ---
    triggering = attendance_df[
        attendance_df["event_type"].isin(["absent", "no_show"])
    ].copy()

    if triggering.empty:
        return pd.DataFrame(), pd.DataFrame()

    # --- Build guardian lookup structures ---
    # student_id → list of guardian_ids (preserves order: primary first)
    student_guardian_ids: dict[str, list[str]] = dict(
        zip(students_df["_id"], students_df["guardian_ids"])
    )

    # Only VALID guardian contacts
    valid_guardians = guardian_contacts_df[
        guardian_contacts_df["contact_status"] == "VALID"
    ].copy()

    # guardian_id → guardian dict (for fast lookup)
    grd_lookup: dict[str, dict] = {
        row["_id"]: row.to_dict()
        for _, row in valid_guardians.iterrows()
    }

    valid_guardian_ids_set = set(grd_lookup.keys())

    not_rows:   list[dict] = []
    skip_rows:  list[dict] = []
    not_counter = 1

    for _, event in triggering.iterrows():
        event_id   = event["_id"]
        student_id = event["student_id"]
        event_type = event["event_type"]
        event_date = event["date"]

        # Find valid guardians for this student
        all_grd_ids   = student_guardian_ids.get(student_id, [])
        valid_grd_ids = [g for g in all_grd_ids if g in valid_guardian_ids_set]

        if not valid_grd_ids:
            skip_rows.append(
                {
                    "student_id": student_id,
                    "event_id":   event_id,
                    "event_type": event_type,
                    "date":       event_date,
                    "reason":     "no_valid_guardian",
                }
            )
            continue

        # Use primary (first) valid guardian
        primary_grd_id = valid_grd_ids[0]
        guardian       = grd_lookup[primary_grd_id]

        # Determine channel from preferences
        prefs   = guardian.get("notification_preferences", [])
        channel = _select_channel(prefs)

        if channel is None:
            skip_rows.append(
                {
                    "student_id": student_id,
                    "event_id":   event_id,
                    "event_type": event_type,
                    "date":       event_date,
                    "reason":     "no_valid_channel",
                }
            )
            continue

        # Build the notification ID first so the delivery hash can use it
        not_id    = make_notification_id(not_counter, year=SCHOOL_YEAR)
        not_counter += 1

        # Deterministic delivery outcome: hash of the notification ID
        delivered      = _is_delivered(not_id)
        status         = "delivered"        if delivered else "failed"
        delivered_at   = _NOW               if delivered else None
        failed_at      = None               if delivered else _NOW
        failure_reason = None               if delivered else "delivery_timeout"

        not_rows.append(
            {
                "_id":              not_id,
                "guardian_id":      primary_grd_id,
                "student_id":       student_id,
                "event_id":         event_id,
                "event_collection": "attendance_events",
                "channel":          channel,
                "status":           status,
                "sent_at":          _NOW,
                "delivered_at":     delivered_at,
                "failed_at":        failed_at,
                "failure_reason":   failure_reason,
                "template_id":      _TEMPLATE_MAP.get(event_type, "TMPL-GENERIC-001"),
                "created_at":       _NOW,
                "updated_at":       _NOW,
            }
        )

    notifications_df = pd.DataFrame(not_rows)
    skipped_df       = pd.DataFrame(skip_rows)

    return notifications_df, skipped_df

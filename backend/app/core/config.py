"""
backend/app/core/config.py
---------------------------
Central configuration for the Student Transportation system.

All random generators must seed from SEED to guarantee deterministic output.
"""

from __future__ import annotations

import datetime
import os
import pathlib

from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------

_ENV_FILE = pathlib.Path(__file__).resolve().parents[3] / "backend" / ".env"
load_dotenv(dotenv_path=_ENV_FILE)

# ---------------------------------------------------------------------------
# Core constants
# ---------------------------------------------------------------------------

#: Global RNG seed – must be passed to every random generator call.
SEED: int = 20261022

#: MongoDB connection URI (override via MONGO_URI env var or .env).
MONGO_URI: str = os.environ.get("MONGO_URI", "mongodb://localhost:27017")

#: Target database name.
DB_NAME: str = os.environ.get("DB_NAME", "transport")

#: Academic year embedded in ROUTE-YYYY-… and ASN-…-YYYY IDs.
SCHOOL_YEAR: int = 2026

#: First day of the school calendar (Monday of opening week).
SCHOOL_CALENDAR_START: datetime.date = datetime.date(2025, 9, 1)

# ---------------------------------------------------------------------------
# Dataset scales
# ---------------------------------------------------------------------------

#: Scale presets.  Select via DATA_SCALE env var ("starter" or "full").
SCALES: dict[str, dict[str, int]] = {
    "starter": {
        "students":    500,
        "buses":        20,
        "drivers":      20,   # one driver per bus
        "stops":        40,
        "zones":        30,
        "school_days": 20,
    },
    "full": {
        "students":   5_000,
        "buses":        100,
        "drivers":      100,  # one driver per bus
        "stops":        300,
        "zones":         30,
        "school_days":  200,
    },
}

#: Active scale – set DATA_SCALE=full in .env or environment to use full.
DATA_SCALE: str = os.environ.get("DATA_SCALE", "starter")
if DATA_SCALE not in SCALES:
    raise ValueError(
        f"DATA_SCALE must be 'starter' or 'full', got '{DATA_SCALE}'"
    )

SCALE: dict[str, int] = SCALES[DATA_SCALE]

# ---------------------------------------------------------------------------
# School-day calendar
# ---------------------------------------------------------------------------


def get_school_days(
    start: datetime.date = SCHOOL_CALENDAR_START,
    n_days: int | None = None,
    school_year: int = SCHOOL_YEAR,
) -> list[datetime.date]:
    """Return a deterministic list of school days (weekdays only).

    Parameters
    ----------
    start:
        First calendar date to consider.  Defaults to SCHOOL_CALENDAR_START.
    n_days:
        Number of school days to generate.  Defaults to the active scale's
        ``school_days`` value.
    school_year:
        Caps the calendar to dates whose year equals *school_year* or
        *school_year - 1* (academic years span two calendar years).

    Returns
    -------
    list[datetime.date]
        Sorted list of exactly *n_days* weekday dates starting from *start*.
    """
    if n_days is None:
        n_days = SCALE["school_days"]

    days: list[datetime.date] = []
    current = start
    while len(days) < n_days:
        # 0 = Monday … 4 = Friday
        if current.weekday() < 5:
            days.append(current)
        current += datetime.timedelta(days=1)

    return days

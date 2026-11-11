"""
backend/app/core/ids.py
------------------------
Deterministic, immutable business-ID generators and validators.

All formats must match the patterns in database/validators/*.json exactly.

Patterns (copied from validators for single-source-of-truth verification):
    Student      STU-000001          ^STU-[0-9]{6}$
    Stop         STOP-000001         ^STOP-[0-9]{6}$
    Bus          BUS-000001          ^BUS-[0-9]{6}$
    Driver       DRV-000001          ^DRV-[0-9]{6}$
    Zone         ZONE-0001           ^ZONE-[0-9]{4}$
    Guardian     GRD-000001          ^GRD-[0-9]{6}$
    Route        ROUTE-2026-000001   ^ROUTE-[0-9]{4}-[0-9]{6}$
    Assignment   ASN-STU-000001-2026 ^ASN-STU-[0-9]{6}-[0-9]{4}$
    Notification NOT-2026-000001     ^NOT-[0-9]{4}-[0-9]{6}$
"""

from __future__ import annotations

import re
from typing import NamedTuple

from backend.app.core.config import SCHOOL_YEAR

# ---------------------------------------------------------------------------
# Compiled regex patterns (single source of truth — must match validators)
# ---------------------------------------------------------------------------

_PATTERNS: dict[str, re.Pattern[str]] = {
    "student":      re.compile(r"^STU-(?P<n>[0-9]{6})$"),
    "stop":         re.compile(r"^STOP-(?P<n>[0-9]{6})$"),
    "bus":          re.compile(r"^BUS-(?P<n>[0-9]{6})$"),
    "driver":       re.compile(r"^DRV-(?P<n>[0-9]{6})$"),
    "zone":         re.compile(r"^ZONE-(?P<n>[0-9]{4})$"),
    "guardian":     re.compile(r"^GRD-(?P<n>[0-9]{6})$"),
    "route":        re.compile(r"^ROUTE-(?P<year>[0-9]{4})-(?P<n>[0-9]{6})$"),
    "assignment":   re.compile(r"^ASN-STU-(?P<n>[0-9]{6})-(?P<year>[0-9]{4})$"),
    "notification": re.compile(r"^NOT-(?P<year>[0-9]{4})-(?P<n>[0-9]{6})$"),
}

# ---------------------------------------------------------------------------
# Generators
# ---------------------------------------------------------------------------


def student_id(n: int) -> str:
    """Return ``STU-000001`` for n=1.  n must be 1–999999."""
    _check_range(n, 999_999, "student")
    return f"STU-{n:06d}"


def stop_id(n: int) -> str:
    """Return ``STOP-000001`` for n=1.  n must be 1–999999."""
    _check_range(n, 999_999, "stop")
    return f"STOP-{n:06d}"


def bus_id(n: int) -> str:
    """Return ``BUS-000001`` for n=1.  n must be 1–999999."""
    _check_range(n, 999_999, "bus")
    return f"BUS-{n:06d}"


def driver_id(n: int) -> str:
    """Return ``DRV-000001`` for n=1.  n must be 1–999999."""
    _check_range(n, 999_999, "driver")
    return f"DRV-{n:06d}"


def zone_id(n: int) -> str:
    """Return ``ZONE-0001`` for n=1.  n must be 1–9999."""
    _check_range(n, 9_999, "zone")
    return f"ZONE-{n:04d}"


def guardian_id(n: int) -> str:
    """Return ``GRD-000001`` for n=1.  n must be 1–999999."""
    _check_range(n, 999_999, "guardian")
    return f"GRD-{n:06d}"


def route_id(n: int, year: int = SCHOOL_YEAR) -> str:
    """Return ``ROUTE-2026-000001`` for n=1.  n must be 1–999999."""
    _check_range(n, 999_999, "route")
    _check_year(year)
    return f"ROUTE-{year}-{n:06d}"


def assignment_id(stu_id: str, year: int = SCHOOL_YEAR) -> str:
    """Return ``ASN-STU-000001-2026`` from a student ID string.

    Parameters
    ----------
    stu_id:
        A valid student ID such as ``STU-000001``.
    year:
        Academic year.  Defaults to SCHOOL_YEAR.

    Raises
    ------
    ValueError
        If *stu_id* does not match the student ID pattern.
    """
    _check_year(year)
    m = _PATTERNS["student"].match(stu_id)
    if not m:
        raise ValueError(
            f"assignment_id: invalid student_id '{stu_id}'. "
            f"Expected pattern STU-NNNNNN."
        )
    return f"ASN-{stu_id}-{year}"


def notification_id(n: int, year: int = SCHOOL_YEAR) -> str:
    """Return ``NOT-2026-000001`` for n=1.  n must be 1–999999."""
    _check_range(n, 999_999, "notification")
    _check_year(year)
    return f"NOT-{year}-{n:06d}"


# ---------------------------------------------------------------------------
# Parse / validate helpers
# ---------------------------------------------------------------------------


class ParsedId(NamedTuple):
    """Structured result of a parsed business ID."""
    kind: str
    n: int
    year: int | None  # present for route, assignment, notification


def parse_id(id_str: str) -> ParsedId:
    """Parse *id_str* and return a :class:`ParsedId`.

    Raises
    ------
    ValueError
        If *id_str* does not match any known pattern.
    """
    for kind, pattern in _PATTERNS.items():
        m = pattern.match(id_str)
        if m:
            groups = m.groupdict()
            n    = int(groups["n"])
            year = int(groups["year"]) if "year" in groups else None
            return ParsedId(kind=kind, n=n, year=year)
    raise ValueError(
        f"parse_id: '{id_str}' does not match any known ID pattern. "
        f"Known prefixes: STU-, STOP-, BUS-, DRV-, ZONE-, GRD-, "
        f"ROUTE-<year>-, ASN-STU-…-<year>, NOT-<year>-"
    )


def validate_id(id_str: str, kind: str) -> bool:
    """Return True if *id_str* matches the pattern for *kind*, else False.

    Parameters
    ----------
    id_str:
        The ID string to check.
    kind:
        One of: student, stop, bus, driver, zone, guardian, route,
        assignment, notification.
    """
    if kind not in _PATTERNS:
        raise ValueError(
            f"validate_id: unknown kind '{kind}'. "
            f"Valid kinds: {list(_PATTERNS)}"
        )
    return bool(_PATTERNS[kind].match(id_str))


def assert_valid_id(id_str: str, kind: str) -> None:
    """Like :func:`validate_id` but raises :exc:`ValueError` on failure."""
    if not validate_id(id_str, kind):
        raise ValueError(
            f"assert_valid_id: '{id_str}' is not a valid {kind} ID."
        )


# ---------------------------------------------------------------------------
# Internal guards
# ---------------------------------------------------------------------------


def _check_range(n: int, max_val: int, label: str) -> None:
    if not isinstance(n, int) or isinstance(n, bool):
        raise ValueError(f"{label}_id: n must be an int, got {type(n).__name__}")
    if n < 1 or n > max_val:
        raise ValueError(
            f"{label}_id: n must be between 1 and {max_val}, got {n}"
        )


def _check_year(year: int) -> None:
    if not isinstance(year, int) or isinstance(year, bool):
        raise ValueError(f"year must be an int, got {type(year).__name__}")
    if year < 2000 or year > 2100:
        raise ValueError(f"year must be between 2000 and 2100, got {year}")

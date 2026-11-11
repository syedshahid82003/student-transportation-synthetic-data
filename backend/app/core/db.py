"""
backend/app/core/db.py
-----------------------
PyMongo database accessor.

Set USE_MOCK=1 in environment (or .env) to swap the real MongoDB client for
a mongomock client — no live server required for unit tests.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from dotenv import load_dotenv
import pathlib

_ENV_FILE = pathlib.Path(__file__).resolve().parents[3] / "backend" / ".env"
load_dotenv(dotenv_path=_ENV_FILE)

from backend.app.core.config import DB_NAME, MONGO_URI  # noqa: E402

if TYPE_CHECKING:
    from pymongo.database import Database

# ---------------------------------------------------------------------------
# Module-level singleton (one client per process)
# ---------------------------------------------------------------------------

_client = None
_db = None


def _build_client():
    """Instantiate and return the appropriate MongoClient."""
    use_mock = os.environ.get("USE_MOCK", "0").strip() in ("1", "true", "True", "yes")
    if use_mock:
        import mongomock
        return mongomock.MongoClient()
    else:
        from pymongo import MongoClient
        return MongoClient(MONGO_URI, serverSelectionTimeoutMS=5_000)


def get_db() -> "Database":
    """Return the shared PyMongo (or mongomock) Database instance.

    The client is created lazily on first call and reused thereafter.
    In tests, set ``USE_MOCK=1`` before importing this module, or call
    :func:`reset_db` between tests that need a clean slate.
    """
    global _client, _db
    if _db is None:
        _client = _build_client()
        _db = _client[DB_NAME]
    return _db


def reset_db() -> None:
    """Drop the cached client and database.  Use in test teardown."""
    global _client, _db
    if _client is not None:
        try:
            _client.close()
        except Exception:  # noqa: BLE001
            pass
    _client = None
    _db = None

"""Application configuration, deliberately minimal.

Only the hub API key is database-managed (the ``CENTRALE_API_KEY`` row of
``dbo.app_config``); the ``CENTRALE_API_KEY`` env var is the fallback.
Browser-facing URLs are NOT read from the database: the client uses the
single ``PUBLIC_HUB_URL`` env option and the hub wizard returns via the
``HUB_CLIENT_URL`` env option.

Reading is done through the existing user_store SQL connection; when SQL
Server is not configured or the table is missing, ``load()`` returns an
empty mapping and callers keep their hardcoded default.
"""
from __future__ import annotations

import os

CENTRALE_API_KEY = "CENTRALE_API_KEY"

_CACHE: dict[str, str] | None = None


def load() -> dict[str, str]:
    """``fieldName`` → ``value`` rows from dbo.app_config (allowing empty cache)."""
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    from app import user_store

    rows: dict[str, str] = {}
    try:
        if user_store.database_url():
            cursor = user_store._sql_connect().cursor()
            cursor.execute(
                """
                SELECT fieldName, value
                FROM dbo.app_config
                WHERE fieldName IS NOT NULL AND value IS NOT NULL
                  AND LTRIM(RTRIM(value)) <> N''
                """
            )
            for name, value in cursor.fetchall():
                rows[str(name).strip()] = str(value).strip()
    except Exception:  # noqa: BLE001
        rows = {}
    _CACHE = rows
    return rows


def get(field_name: str, default: str = "") -> str:
    value = load().get(field_name)
    return value if value else default


def reset_cache() -> None:
    global _CACHE
    _CACHE = None


def centrale_api_key() -> str:
    """Hub API key: the non-empty ``CENTRALE_API_KEY`` row, else the env var
    ``CENTRALE_API_KEY``.

    ``load()`` filters out blank rows, so leaving the row at ``''`` keeps
    whatever the environment provides; a non-empty row overrides it. This lets
    the key be managed in the database without touching ``hub.env``.
    """
    return get(CENTRALE_API_KEY) or os.environ.get("CENTRALE_API_KEY", "").strip()
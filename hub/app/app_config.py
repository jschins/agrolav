"""Application configuration from ``dbo.app_config``.

Live rows replace the hardcoded env fallbacks. Reading is done through the
existing user_store SQL connection; when SQL Server is not configured or the
table is missing, ``load()`` returns an empty mapping and callers keep their
hardcoded default.

The Enable Banking callback address is read directly from the single fieldName
``LOCAL_ENABLEBANKING_REDIRECT_URL`` (falling back to PRODUCTION only when
that row is missing).
"""
from __future__ import annotations

import os

PRODUCTION_ENABLEBANKING_REDIRECT_URL = "PRODUCTION_ENABLEBANKING_REDIRECT_URL"
LOCAL_ENABLEBANKING_REDIRECT_URL = "LOCAL_ENABLEBANKING_REDIRECT_URL"
_ENABLEBANKING_REDIRECT_URL_ENV = "ENABLEBANKING_REDIRECT_URL"

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


def environment() -> str:
    """``production`` or ``local``: explicit ``HUB_ENV`` wins, else ``local``.

    Used only when no request ``Host`` is bound (CLI / tests).
    """
    raw = os.environ.get("HUB_ENV", "").strip().lower()
    if raw in ("production", "prod"):
        return "production"
    return "local"


def enablebanking_redirect_url() -> str:
    """Enable Banking callback: the ``LOCAL_ENABLEBANKING_REDIRECT_URL`` row.

    The value is read straight from ``dbo.app_config`` under that fieldName.
    Falls back to the PRODUCTION row only when the LOCAL row is missing.
    """
    rows = load()
    return (
        rows.get(LOCAL_ENABLEBANKING_REDIRECT_URL)
        or rows.get(PRODUCTION_ENABLEBANKING_REDIRECT_URL)
        or ""
    )
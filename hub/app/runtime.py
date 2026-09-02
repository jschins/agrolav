"""Runtime state + bound identity for the always-on hub (SQL Server only).

Person identity is ``country`` / ``center`` / ``person`` / ``year`` / ``account``
from SQL (``apply_scope`` / ``bind_scope``).
"""
from __future__ import annotations

import os
import sys
import threading
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from shared.user_access import ACCESS_CENTER, ACCESS_COUNTRY

_active_center: str | None = None
_active_country: str | None = None

# Login / CSV country names, mapped to the canonical dbo.country key.
_NL_KEYS = frozenset({"nederland", "netherlands", "the_netherlands", "nl"})
_UK_KEYS = frozenset(
    {"uk", "united_kingdom", "united kingdom", "great_britain", "great britain", "gb"}
)

_cv_request_country: ContextVar[str | None] = ContextVar("request_country", default=None)
_cv_request_host: ContextVar[str | None] = ContextVar("request_host", default=None)

# Serialize all person binds / recalculate (uvicorn runs sync routes in a threadpool).
CALC_LOCK = threading.RLock()


def country_folder(name: str | None) -> str:
    """Map a login/CSV country name to the canonical ``dbo.country`` key.

    ``uk`` / ``united_kingdom`` are one country (canonical ``united_kingdom``);
    ``nl`` / ``netherlands`` map to ``nederland``. Nothing is read from disk.
    """
    raw = str(name or "").strip()
    if not raw:
        return ""
    key = raw.lower().replace("-", "_").replace(" ", "_")
    if key in _UK_KEYS:
        return "united_kingdom"
    if key in _NL_KEYS:
        return "nederland"
    return raw


def set_request_host(host: str | None) -> Token[str | None]:
    """Bind the incoming request ``Host`` header for app_config row selection."""
    text = str(host or "").strip().lower()
    return _cv_request_host.set(text or None)


def reset_request_host(token: Token[str | None]) -> None:
    _cv_request_host.reset(token)


def request_host() -> str | None:
    return _cv_request_host.get()


def is_frozen() -> bool:
    return getattr(sys, "frozen", False)


def project_root() -> Path:
    """``server/hub`` (source) or exe parent when frozen."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def data_root() -> Path:
    """Disk root for the on-disk flat JSON scratch files, when SQL is not configured.

    ``downloaded_transactions.json`` and ``categorized_transactions.json`` would
    be written flat at the ``AGROLAV_SQL_DISK`` mount root (else the process cwd).
    With SQL configured the disk no longer stores these scratch files — the
    database is authoritative.
    """
    env = os.environ.get("AGROLAV_SQL_DISK", "").strip()
    if env:
        return Path(env).resolve()
    return Path.cwd().resolve()


def set_request_country(country: str | None) -> Token[str | None]:
    folder = country_folder(country) or None
    return _cv_request_country.set(folder)


def reset_request_country(token: Token[str | None]) -> None:
    _cv_request_country.reset(token)


def request_country() -> str | None:
    return _cv_request_country.get()


def list_country_folders() -> list[str]:
    """Country login names from ``dbo.country`` (SQL required; no folder scan)."""
    from app.sql_catalog import list_country_usernames

    return list_country_usernames()


def resolve_country_for_center(center: str) -> str | None:
    """Country for ``center``: SQL first, then request/active country."""
    name = (center or "").strip()
    if not name:
        return None
    from app.sql_catalog import country_for_center

    sql_country = country_for_center(name)
    if sql_country:
        return country_folder(sql_country) or sql_country
    preferred = request_country() or _active_country
    if preferred:
        return country_folder(preferred)
    return None


def set_active_center(center: str | None, *, country: str | None = None) -> None:
    """Bind the active center (+ country) used for the SQL calc scope."""
    global _active_center, _active_country
    _active_center = (center or "").strip() or None
    explicit = country_folder(country) or None
    if explicit:
        _active_country = explicit
    elif _active_center:
        _active_country = resolve_country_for_center(_active_center)
    else:
        _active_country = None


def active_center() -> str | None:
    return _active_center


def active_country() -> str | None:
    return _active_country


def country_root() -> Path:
    """Virtual active country path (``categories.json`` beside the centers)."""
    root = data_root()
    if _active_country:
        return (root / _active_country).resolve()
    return root


def app_root() -> Path:
    """Virtual active center path for diagnostic logs; never created on disk."""
    root = data_root()
    if _active_country and _active_center:
        return (root / _active_country / _active_center).resolve()
    if _active_center:
        country = resolve_country_for_center(_active_center)
        if country:
            return (root / country / _active_center).resolve()
        return (root / _active_center).resolve()
    if _active_country:
        return (root / _active_country).resolve()
    return root


def is_central_admin() -> bool:
    """Hub always runs calc against center data (secrets optional)."""
    return True


@dataclass(frozen=True)
class PersonScope:
    """SQL identity for one person in a center.

    ``account`` is ``dbo.account.iban`` when the view is one account;
    ``None`` means every account (consolidated).
    """

    country: str
    center: str
    person: str
    year: str
    account: str | None = None

    @property
    def person_name(self) -> str:
        return self.person

    @property
    def has_pem(self) -> bool:
        """True when Enable Banking credentials are present in SQL."""
        from app.enable_sql import person_has_pem

        return person_has_pem(self.person)


BOUND_COUNTRY: str = ""
BOUND_CENTER: str = ""
BOUND_PERSON: str = ""
BOUND_YEAR: int | None = None
BOUND_ACCOUNT: str | None = None


def shared_categories_path(root: Path | None = None) -> Path:
    """``categories.json`` beside the centers (``data_root/<country>/``)."""
    if root is not None:
        here = (root / "categories.json").resolve()
        parent_cat = (root.parent / "categories.json").resolve()
        if parent_cat.is_file() and not here.is_file():
            return parent_cat
        if here.is_file():
            return here
        return parent_cat if (root.parent / "categories.json").exists() else here
    country = _active_country
    if country:
        return (country_root() / "categories.json").resolve()
    # Center folder is app_root(); catalog lives one level up.
    center = app_root()
    sibling = center / "categories.json"
    if sibling.is_file():
        return sibling.resolve()
    parent_cat = center.parent / "categories.json"
    if parent_cat.is_file():
        return parent_cat.resolve()
    return (data_root() / "categories.json").resolve()


def app_id_from_profile_data(data: dict[str, Any]) -> str:
    """Application id from ``connections[]`` (preferred) or legacy top-level ``app_id``."""
    connections = data.get("connections")
    if isinstance(connections, list):
        for conn in connections:
            if not isinstance(conn, dict):
                continue
            app_id = str(conn.get("app_id") or "").strip()
            if app_id:
                return app_id
    return str(data.get("app_id") or "").strip()


def apply_scope(scope: PersonScope) -> None:
    """Bind SQL identity for categorize / replica / Enable Banking."""
    global BOUND_COUNTRY, BOUND_CENTER, BOUND_PERSON, BOUND_YEAR, BOUND_ACCOUNT

    BOUND_COUNTRY = str(scope.country or "").strip()
    BOUND_CENTER = str(scope.center or "").strip()
    BOUND_PERSON = scope.person
    try:
        BOUND_YEAR = int(scope.year)
    except (TypeError, ValueError):
        BOUND_YEAR = None
    BOUND_ACCOUNT = str(scope.account or "").strip() or None


@contextmanager
def bind_scope(scope: PersonScope) -> Iterator[PersonScope]:
    """Temporarily bind identity globals to ``scope``, then restore them."""
    global BOUND_COUNTRY, BOUND_CENTER, BOUND_PERSON, BOUND_YEAR, BOUND_ACCOUNT

    with CALC_LOCK:
        snapshot = {
            "BOUND_COUNTRY": BOUND_COUNTRY,
            "BOUND_CENTER": BOUND_CENTER,
            "BOUND_PERSON": BOUND_PERSON,
            "BOUND_YEAR": BOUND_YEAR,
            "BOUND_ACCOUNT": BOUND_ACCOUNT,
        }
        apply_scope(scope)
        try:
            yield scope
        finally:
            BOUND_COUNTRY = snapshot["BOUND_COUNTRY"]
            BOUND_CENTER = snapshot["BOUND_CENTER"]
            BOUND_PERSON = snapshot["BOUND_PERSON"]
            BOUND_YEAR = snapshot["BOUND_YEAR"]
            BOUND_ACCOUNT = snapshot["BOUND_ACCOUNT"]


def configure() -> list[PersonScope]:
    """Discover person scopes for the active center (SQL; empty center is allowed)."""
    from app.people import list_people

    people = list_people()
    if people:
        apply_scope(people[0])
    return people
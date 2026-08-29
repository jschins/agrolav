"""Runtime state + bound identity for the always-on hub (SQL Server only).

No on-disk country/center/person folders exist. ``data_root()`` points at the
only on-disk files (the two flat JSON scratch files under ``AGROLAV_SQL_DISK``).
Person identity is bound as plain state (``apply_person``/``bind_person``) so
the SQL replica knows which person/year(/bank) is active.
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

from app.yearpath import current_year, is_year_name

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
    """Disk root for the only on-disk files: the two always-overwritten flat JSON scratch files.

    ``downloaded_transactions.json`` and ``categorized_transactions.json`` are
    written flat at the ``AGROLAV_SQL_DISK`` mount root (else the process cwd).
    No ``data/``, ``workspaces/`` or per-person folder is used.
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
    """Virtual active center path (person packs) for calc; never created on disk."""
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
class PersonPack:
    person_name: str
    folder: Path
    data_dir: Path
    secret_dir: Path
    profile_path: Path
    private_key_path: Path
    year: str
    country: str = ""
    center: str = ""

    @property
    def consent_path(self) -> Path:
        return self.secret_dir / "consent.json"

    @property
    def personal_categories_path(self) -> Path:
        return self.secret_dir / "personal_categories.json"

    @property
    def categorized_path(self) -> Path:
        return self.data_dir / "categorized_transactions.json"

    @property
    def totals_path(self) -> Path:
        return self.data_dir / "category_totals.json"

    @property
    def has_secret_folder(self) -> bool:
        """True when Enable Banking credentials are present (SQL PEM, else a .pem file)."""
        from app.enable_sql import person_has_pem

        if person_has_pem(self.person_name):
            return True
        return self.secret_dir.is_dir() and any(self.secret_dir.glob("*.pem"))


DATA_DIR: Path = Path(current_year())
PERSON_NAME: str = ""
BOUND_COUNTRY: str = ""
BOUND_PERSON: str = ""
BOUND_YEAR: int | None = None
BOUND_BANK: str | None = None
PROFILE_PATH: Path = Path("profile.json")
PRIVATE_KEY_PATH: Path = Path("key.pem")
CONSENT_PATH: Path = Path("secret") / "consent.json"
CATEGORIES_PATH: Path = Path("categories.json")
PERSONAL_CATEGORIES_PATH: Path = Path("secret") / "personal_categories.json"
CATEGORIZED_TRANSACTIONS_PATH: Path = DATA_DIR / "categorized_transactions.json"
RAW_TRANSACTIONS_PATH: Path = DATA_DIR / "downloaded_transactions.json"
CATEGORY_TOTALS_PATH: Path = DATA_DIR / "category_totals.json"


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


def _set_bound_identity(pack: PersonPack) -> None:
    global BOUND_COUNTRY, BOUND_PERSON, BOUND_YEAR, BOUND_BANK

    country = str(pack.country or "").strip()
    if not country:
        try:
            country = pack.folder.parent.parent.name
        except Exception:
            country = ""
    BOUND_COUNTRY = country
    BOUND_PERSON = pack.person_name
    try:
        BOUND_YEAR = int(pack.year)
    except (TypeError, ValueError):
        BOUND_YEAR = None
    BOUND_BANK = None
    if not is_year_name(pack.data_dir.name) and is_year_name(pack.data_dir.parent.name):
        BOUND_BANK = pack.data_dir.name


def apply_person(pack: PersonPack) -> None:
    """Bind module-level paths at one person pack (used by categorize/single_client)."""
    global DATA_DIR, PERSON_NAME, PROFILE_PATH, PRIVATE_KEY_PATH, CONSENT_PATH
    global CATEGORIES_PATH, PERSONAL_CATEGORIES_PATH, CATEGORIZED_TRANSACTIONS_PATH
    global RAW_TRANSACTIONS_PATH, CATEGORY_TOTALS_PATH

    DATA_DIR = pack.data_dir
    PERSON_NAME = pack.person_name
    PROFILE_PATH = pack.profile_path
    PRIVATE_KEY_PATH = pack.private_key_path
    CONSENT_PATH = pack.consent_path
    CATEGORIES_PATH = shared_categories_path()
    PERSONAL_CATEGORIES_PATH = pack.personal_categories_path
    CATEGORIZED_TRANSACTIONS_PATH = pack.categorized_path
    RAW_TRANSACTIONS_PATH = pack.data_dir / "downloaded_transactions.json"
    CATEGORY_TOTALS_PATH = pack.totals_path
    _set_bound_identity(pack)


@contextmanager
def bind_person(pack: PersonPack) -> Iterator[PersonPack]:
    """Temporarily bind path globals to ``pack``, then restore previous values."""
    global DATA_DIR, PERSON_NAME, PROFILE_PATH, PRIVATE_KEY_PATH, CONSENT_PATH
    global CATEGORIES_PATH, PERSONAL_CATEGORIES_PATH, CATEGORIZED_TRANSACTIONS_PATH
    global RAW_TRANSACTIONS_PATH, CATEGORY_TOTALS_PATH
    global BOUND_COUNTRY, BOUND_PERSON, BOUND_YEAR, BOUND_BANK

    with CALC_LOCK:
        snapshot = {
            "DATA_DIR": DATA_DIR,
            "PERSON_NAME": PERSON_NAME,
            "PROFILE_PATH": PROFILE_PATH,
            "PRIVATE_KEY_PATH": PRIVATE_KEY_PATH,
            "CONSENT_PATH": CONSENT_PATH,
            "CATEGORIES_PATH": CATEGORIES_PATH,
            "PERSONAL_CATEGORIES_PATH": PERSONAL_CATEGORIES_PATH,
            "CATEGORIZED_TRANSACTIONS_PATH": CATEGORIZED_TRANSACTIONS_PATH,
            "RAW_TRANSACTIONS_PATH": RAW_TRANSACTIONS_PATH,
            "CATEGORY_TOTALS_PATH": CATEGORY_TOTALS_PATH,
            "BOUND_COUNTRY": BOUND_COUNTRY,
            "BOUND_PERSON": BOUND_PERSON,
            "BOUND_YEAR": BOUND_YEAR,
            "BOUND_BANK": BOUND_BANK,
        }
        apply_person(pack)
        try:
            yield pack
        finally:
            DATA_DIR = snapshot["DATA_DIR"]
            PERSON_NAME = snapshot["PERSON_NAME"]
            PROFILE_PATH = snapshot["PROFILE_PATH"]
            PRIVATE_KEY_PATH = snapshot["PRIVATE_KEY_PATH"]
            CONSENT_PATH = snapshot["CONSENT_PATH"]
            CATEGORIES_PATH = snapshot["CATEGORIES_PATH"]
            PERSONAL_CATEGORIES_PATH = snapshot["PERSONAL_CATEGORIES_PATH"]
            CATEGORIZED_TRANSACTIONS_PATH = snapshot["CATEGORIZED_TRANSACTIONS_PATH"]
            RAW_TRANSACTIONS_PATH = snapshot["RAW_TRANSACTIONS_PATH"]
            CATEGORY_TOTALS_PATH = snapshot["CATEGORY_TOTALS_PATH"]
            BOUND_COUNTRY = snapshot["BOUND_COUNTRY"]
            BOUND_PERSON = snapshot["BOUND_PERSON"]
            BOUND_YEAR = snapshot["BOUND_YEAR"]
            BOUND_BANK = snapshot["BOUND_BANK"]


def configure() -> list[PersonPack]:
    """Discover person packs for the active center (SQL; empty center is allowed)."""
    from app.people import list_people

    people = list_people()
    if people:
        apply_person(people[0])
    return people
"""Discover person packs under the active center folder (hub)."""
from __future__ import annotations

from pathlib import Path

from app.paths import PersonPack, _resolve_private_key
from app.runtime import app_root
from app.yearpath import has_person_layout, parse_year, year_dir

_IGNORE_DIRS = frozenset(
    {
        "app",
        "frontend",
        "dist",
        "build",
        ".venv",
        "venv",
        "scripts",
        "node_modules",
        "__pycache__",
        ".git",
    }
)

_MISSING = Path(".")


def _sql_packs(*, center: str, country: str, year: str | None) -> list[PersonPack]:
    from app.runtime import data_root
    from app.sql_catalog import people_in_center, years_by_person_in_center
    from app.yearpath import current_year, parse_year

    root = data_root()
    packs: list[PersonPack] = []
    requested = parse_year(year) if year else None
    years_map = years_by_person_in_center(center)
    for username in people_in_center(center):
        years = years_map.get(username) or []
        if requested:
            y = requested
        elif years:
            y = years[-1]
        else:
            y = current_year()
        folder = root / country / center / username
        secret = folder / "secret"
        packs.append(
            PersonPack(
                short=username,
                folder=folder,
                folder_name=username,
                data_dir=folder / y,
                secret_dir=secret,
                profile_path=_MISSING,
                private_key_path=_MISSING,
                year=y,
                country=country,
                center=center,
            )
        )
    packs.sort(key=lambda p: p.folder_name.lower())
    return packs


def list_people(root: Path | None = None, *, year: str | None = None) -> list[PersonPack]:
    """Person packs from SQL when configured, else ``secret/`` and/or ``YYYY/`` folders."""
    from app import user_store
    from app.runtime import active_center, active_country, country_folder
    from app.sql_catalog import country_for_center

    if user_store.database_url():
        center = (root.name if root is not None else active_center()) or ""
        country = country_folder(active_country() or "") or country_for_center(center) or ""
        if center:
            return _sql_packs(center=center, country=country, year=year)

    base = root if root is not None else app_root()
    y = parse_year(year)
    require_year_folder = year is not None
    packs: list[PersonPack] = []
    if not base.is_dir():
        return packs

    for child in sorted(base.iterdir(), key=lambda p: p.name.lower()):
        if not child.is_dir() or child.name in _IGNORE_DIRS or child.name.startswith("."):
            continue
        if require_year_folder:
            # When a year is explicitly selected, only include persons that
            # actually have that year folder.
            if not year_dir(child, y).is_dir():
                continue
        else:
            if not has_person_layout(child):
                continue

        data = year_dir(child, y)
        secret = child / "secret"
        profile = secret / "profile.json"
        private_key = _MISSING
        profile_path = profile.resolve() if profile.is_file() else _MISSING
        secret_dir = secret if secret.is_dir() else (child / "secret")

        if secret.is_dir():
            try:
                private_key = _resolve_private_key(secret, profile if profile.is_file() else None)
            except (OSError, FileNotFoundError, ValueError):
                private_key = _MISSING

        packs.append(
            PersonPack(
                short=child.name,
                folder=child.resolve(),
                folder_name=child.name,
                data_dir=data.resolve(),
                secret_dir=secret_dir.resolve() if secret.is_dir() else secret_dir,
                profile_path=profile_path,
                private_key_path=private_key,
                year=y,
                country=child.parent.parent.name,
                center=child.parent.name,
            )
        )
    packs.sort(key=lambda p: p.folder_name.lower())
    return packs


def get_person(short: str, root: Path | None = None, *, year: str | None = None) -> PersonPack:
    needle = short.strip().lower()
    for pack in list_people(root, year=year):
        if pack.folder_name.lower() == needle:
            return pack
    raise KeyError(f"Unknown person: {short!r}")

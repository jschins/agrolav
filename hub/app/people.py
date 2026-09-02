"""Person packs from ``dbo.person`` (SQL required). No on-disk folders."""
from __future__ import annotations

from pathlib import Path

from app.runtime import PersonPack
from app.runtime import active_center, active_country, country_folder
from app.sql_catalog import country_for_center, people_in_center, years_by_person_in_center
from app.yearpath import current_year, parse_year

_MISSING = Path(".")


def _sql_packs(*, center: str, country: str, year: str | None) -> list[PersonPack]:
    """One pack per ``dbo.person`` row in ``center`` (folder paths stay virtual)."""
    from app.runtime import data_root

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
                person_name=username,
                folder=folder,
                data_dir=folder / y,
                secret_dir=secret,
                profile_path=_MISSING,
                private_key_path=_MISSING,
                year=y,
                country=country,
                center=center,
            )
        )
    packs.sort(key=lambda p: p.person_name.lower())
    return packs


def list_people(root: Path | None = None, *, year: str | None = None) -> list[PersonPack]:
    """Person packs from dbo.person. SQL Server is required; no folder scan."""
    center = (root.name if root is not None else active_center()) or ""
    if not center:
        return []
    country = country_folder(active_country() or "") or country_for_center(center) or ""
    return _sql_packs(center=center, country=country, year=year)


def get_person(person_name: str, root: Path | None = None, *, year: str | None = None) -> PersonPack:
    needle = person_name.strip().lower()
    for pack in list_people(root, year=year):
        if pack.person_name.lower() == needle:
            return pack
    raise KeyError(f"Unknown person: {person_name!r}")

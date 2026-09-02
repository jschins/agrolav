"""Person scopes from ``dbo.person`` (SQL required). No on-disk folders."""
from __future__ import annotations

from app.runtime import PersonScope
from app.runtime import active_center, active_country, country_folder
from app.sql_catalog import country_for_center, people_in_center, years_by_person_in_center
from app.yearpath import current_year, parse_year


def _sql_scopes(*, center: str, country: str, year: str | None) -> list[PersonScope]:
    """One scope per ``dbo.person`` row in ``center``."""
    scopes: list[PersonScope] = []
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
        scopes.append(
            PersonScope(
                country=country,
                center=center,
                person=username,
                year=y,
                account=None,
            )
        )
    scopes.sort(key=lambda item: item.person.lower())
    return scopes


def list_people(*, year: str | None = None) -> list[PersonScope]:
    """Person scopes from dbo.person. SQL Server is required; no folder scan."""
    center = active_center() or ""
    if not center:
        return []
    country = country_folder(active_country() or "") or country_for_center(center) or ""
    return _sql_scopes(center=center, country=country, year=year)


def get_person(person_name: str, *, year: str | None = None) -> PersonScope:
    needle = person_name.strip().lower()
    for scope in list_people(year=year):
        if scope.person.lower() == needle:
            return scope
    raise KeyError(f"Unknown person: {person_name!r}")

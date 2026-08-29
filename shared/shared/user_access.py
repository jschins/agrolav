"""Derive login access mode from user-store fields (person + center + country)."""
from __future__ import annotations

from typing import Any

ACCESS_PERSON = "personal"
ACCESS_CENTER = "local"
ACCESS_COUNTRY = "country"


def parse_centers(raw: str | None) -> list[str]:
    """Split ``center`` field: ``dkg,jl`` → ``['dkg', 'jl']``.

    ``NULL``, missing, and empty string all yield ``[]``.
    """
    if raw is None:
        return []
    return [part.strip() for part in str(raw).split(",") if part.strip()]


def deduce_access(*, person: str, center: str = "", country: str = "") -> str:
    """Access follows the SQL login assignment fields (empty string = NULL).

    - person set → personal
    - person empty, center set → local (that center)
    - person empty, center empty, country set → country (all folders in that country)
    - person empty, center empty, country empty → local (incomplete row)
    """
    if str(person or "").strip():
        return ACCESS_PERSON
    if str(center or "").strip():
        return ACCESS_CENTER
    if str(country or "").strip():
        return ACCESS_COUNTRY
    return ACCESS_CENTER


def enrich_user_record(user: dict[str, Any]) -> dict[str, Any]:
    """Add derived ``access`` and parsed ``centers`` list to a user dict.

    ``center`` / ``centers`` are the API names for the center folder(s).
    There is no all-countries login.
    """
    person = str(user.get("person") or "").strip()
    center = str(user.get("center") or "").strip()
    country = str(user.get("country") or "").strip()
    centers = parse_centers(center)
    access = deduce_access(person=person, center=center, country=country)
    return {
        "username": str(user.get("username") or "").strip(),
        "title": str(user.get("title") or "").strip(),
        "access": access,
        "country": country,
        "center": center,
        "centers": centers,
        "person": person,
        "format": str(user.get("format") or "").strip(),
        "number_of_accounts": user.get("number_of_accounts"),
    }

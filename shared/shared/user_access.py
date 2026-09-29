"""Derive login access mode from user-store fields (person + center + country)."""
from __future__ import annotations

from typing import Any

ACCESS_PERSON = "personal"
ACCESS_CENTER = "local"
ACCESS_COUNTRY = "country"
ACCESS_UNIT = "unit"


def parse_centers(raw: str | None) -> list[str]:
    """Split ``center`` field: ``dkg,jl`` → ``['dkg', 'jl']``.

    ``NULL``, missing, and empty string all yield ``[]``.
    """
    if raw is None:
        return []
    return [part.strip() for part in str(raw).split(",") if part.strip()]


def deduce_access(
    *, person: str, center: str = "", country: str = "", unit: str = ""
) -> str:
    """Access follows the SQL login assignment fields (empty string = NULL).

    - unit set → unit (one account)
    - person set → personal
    - person empty, center set → local (that center)
    - person empty, center empty, country set → country (all folders in that country)
    - person empty, center empty, country empty → local (incomplete row)
    """
    if str(unit or "").strip():
        return ACCESS_UNIT
    if str(person or "").strip():
        return ACCESS_PERSON
    if str(center or "").strip():
        return ACCESS_CENTER
    if str(country or "").strip():
        return ACCESS_COUNTRY
    return ACCESS_CENTER


def can_edit_general_terms(access: str) -> bool:
    """Only a country login may add, change, or delete G-terms.

    Unit, person, and center logins may see G-terms. They may change P-terms only.
    """
    return str(access or "").strip().lower() == ACCESS_COUNTRY


def _compact_account(value: object) -> str:
    return "".join(str(value or "").split()).upper()


def unit_may_edit_account(
    *,
    access: str,
    login_account: str,
    account_key: str,
    groups: list[dict[str, Any]] | None = None,
) -> bool:
    """A unit login may change P-terms only on its own account.

    Person, center, and country are not limited here. Their write scope is the
    set of accounts already visible to that login.
    """
    if str(access or "").strip().lower() != ACCESS_UNIT:
        return True
    key = str(account_key or "").strip()
    wanted = _compact_account(login_account)
    if not key or not wanted:
        return False
    if _compact_account(key) == wanted:
        return True
    for group in groups or []:
        if not isinstance(group, dict):
            continue
        if str(group.get("account_key") or "").strip() != key:
            continue
        if _compact_account(group.get("iban")) == wanted:
            return True
    return False


def enrich_user_record(user: dict[str, Any]) -> dict[str, Any]:
    """Add derived ``access`` and parsed ``centers`` list to a user dict.

    ``center`` / ``centers`` are the API names for the center folder(s).
    There is no all-countries login.
    """
    person = str(user.get("person") or "").strip()
    center = str(user.get("center") or "").strip()
    country = str(user.get("country") or "").strip()
    unit = str(user.get("unit") or "").strip()
    account = str(user.get("account") or "").strip()
    centers = parse_centers(center)
    access = deduce_access(person=person, center=center, country=country, unit=unit)
    return {
        "username": str(user.get("username") or "").strip(),
        "title": str(user.get("title") or "").strip(),
        "access": access,
        "country": country,
        "center": center,
        "centers": centers,
        "person": person,
        "unit": unit,
        "account": account,
        "format": str(user.get("format") or "").strip(),
    }

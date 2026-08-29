"""Year helpers for hub (SQL required). No on-disk year folders are created."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

SECRET_DIRNAME = "secret"
YEAR_MIN = 1990
YEAR_MAX = 2100


def current_year() -> str:
    return str(datetime.now().year)


def default_upload_year() -> str:
    """Current year, except in January when uploads typically belong to the previous year."""
    now = datetime.now()
    return str(now.year - 1 if now.month == 1 else now.year)


def is_year_name(name: str) -> bool:
    return name.isdigit() and len(name) == 4 and YEAR_MIN <= int(name) <= YEAR_MAX


def parse_year(raw: str | None) -> str:
    text = str(raw or "").strip()
    if not text:
        return current_year()
    if not is_year_name(text):
        raise ValueError(f"Invalid year: {raw!r}")
    return text


def list_year_names(person_folder: Path) -> list[str]:
    """Person's years from SQL (``person_folder.name`` is the login username)."""
    from app.sql_catalog import years_for_person

    return years_for_person(person_folder.name)


def has_person_layout(person_folder: Path) -> bool:
    if not person_folder.is_dir():
        return False
    if (person_folder / SECRET_DIRNAME).is_dir():
        return True
    return bool(list_year_names(person_folder))
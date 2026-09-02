"""Admin app settings — people are listed from SQL for the active center."""
from __future__ import annotations

from app.runtime import PersonScope, configure as configure_paths
from app.people import list_people

_people: list[PersonScope] | None = None


def init_app() -> list[PersonScope]:
    global _people
    _people = configure_paths()
    return _people


def get_people() -> list[PersonScope]:
    if _people is None:
        return list_people()
    return list(_people)


def refresh_people() -> list[PersonScope]:
    global _people
    _people = list_people()
    return list(_people)

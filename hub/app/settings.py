"""Admin app settings — people are listed from SQL for the active center."""
from __future__ import annotations

import threading

from app.runtime import PersonScope, configure as configure_paths
from app.people import list_people

# Per thread, like the calc scope. A background rescore must not replace the
# people list a request thread is reading.
_people_tls = threading.local()


def init_app() -> list[PersonScope]:
    people = configure_paths()
    _people_tls.people = people
    return people


def get_people() -> list[PersonScope]:
    people = getattr(_people_tls, "people", None)
    if people is None:
        return list_people()
    return list(people)


def refresh_people() -> list[PersonScope]:
    people = list_people()
    _people_tls.people = people
    return list(people)

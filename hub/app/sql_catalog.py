"""SQL Server catalog: countries, centers, people, years, categories.

Used when workspace folders are absent. Bookings stay in ``sql_replica``.
"""
from __future__ import annotations

import time
from typing import Any

from app.yearpath import is_year_name

_CAT_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_CAT_TTL_SEC = 3.0


def _sql_ready() -> bool:
    from app import user_store

    if not user_store.database_url():
        return False
    user_store.init_user_store()
    return user_store._SQL is not None


def _cursor():
    from app import user_store

    return user_store._sql_connect().cursor()


def _sql_retry(fn):
    """Run a SQL callable; reconnect once on a dead connection."""
    from app import user_store

    try:
        return fn()
    except Exception:
        user_store.reset_sql_connection()
        user_store.init_user_store()
        return fn()


def list_country_usernames() -> list[str]:
    if not _sql_ready():
        return []

    def _run() -> list[str]:
        cursor = _cursor()
        cursor.execute("SELECT username FROM dbo.country ORDER BY username")
        return [str(row[0]).strip() for row in cursor.fetchall() if str(row[0] or "").strip()]

    try:
        return _sql_retry(_run)
    except Exception:  # noqa: BLE001
        return []


def list_center_usernames(country: str) -> list[str]:
    name = (country or "").strip()
    if not name or not _sql_ready():
        return []

    def _run() -> list[str]:
        cursor = _cursor()
        cursor.execute(
            """
            SELECT n.username
            FROM dbo.center n
            JOIN dbo.country c ON c.country_id = n.country_id
            WHERE c.username = ? COLLATE Latin1_General_CI_AI
            ORDER BY n.username
            """,
            (name,),
        )
        return [str(row[0]).strip() for row in cursor.fetchall() if str(row[0] or "").strip()]

    try:
        return _sql_retry(_run)
    except Exception:  # noqa: BLE001
        return []


def country_for_center(center: str) -> str | None:
    name = (center or "").strip()
    if not name or not _sql_ready():
        return None

    def _run() -> str | None:
        cursor = _cursor()
        cursor.execute(
            """
            SELECT c.username
            FROM dbo.center n
            JOIN dbo.country c ON c.country_id = n.country_id
            WHERE n.username = ? COLLATE Latin1_General_CI_AI
            """,
            (name,),
        )
        row = cursor.fetchone()
        if row and str(row[0] or "").strip():
            return str(row[0]).strip()
        return None

    try:
        return _sql_retry(_run)
    except Exception:  # noqa: BLE001
        return None


def center_exists(center: str) -> bool:
    name = (center or "").strip()
    if not name or not _sql_ready():
        return False

    def _run() -> bool:
        cursor = _cursor()
        cursor.execute(
            "SELECT 1 FROM dbo.center WHERE username = ? COLLATE Latin1_General_CI_AI",
            (name,),
        )
        return cursor.fetchone() is not None

    return bool(_sql_retry(_run))


def coerce_center(name: str) -> str:
    """If ``name`` is a country username, return that country's first center."""
    raw = (name or "").strip()
    if not raw:
        return raw
    if center_exists(raw):
        return raw
    from app.runtime import country_folder

    folder = country_folder(raw) or raw
    centers = list_center_usernames(folder)
    return centers[0] if centers else raw


def people_in_center(center: str) -> list[str]:
    name = (center or "").strip()
    if not name or not _sql_ready():
        return []

    def _run() -> list[str]:
        cursor = _cursor()
        cursor.execute(
            """
            SELECT p.username
            FROM dbo.person p
            JOIN dbo.center n ON n.center_id = p.center_id
            WHERE n.username = ? COLLATE Latin1_General_CI_AI
            ORDER BY p.username
            """,
            (name,),
        )
        return [str(row[0]).strip() for row in cursor.fetchall() if str(row[0] or "").strip()]

    try:
        return _sql_retry(_run)
    except Exception:  # noqa: BLE001
        return []


def person_country_center(username: str) -> tuple[str, str] | None:
    name = (username or "").strip()
    if not name or not _sql_ready():
        return None

    def _run() -> tuple[str, str] | None:
        cursor = _cursor()
        cursor.execute(
            """
            SELECT c.username, n.username
            FROM dbo.person p
            JOIN dbo.country c ON c.country_id = p.country_id
            JOIN dbo.center n ON n.center_id = p.center_id
            WHERE p.username = ? COLLATE Latin1_General_CI_AI
            """,
            (name,),
        )
        row = cursor.fetchone()
        if row and str(row[0] or "").strip() and str(row[1] or "").strip():
            return str(row[0]).strip(), str(row[1]).strip()
        return None

    try:
        return _sql_retry(_run)
    except Exception:  # noqa: BLE001
        return None


def _years_from_table(cursor, table: str, where_sql: str, param: str) -> list[str]:
    cursor.execute(
        f"SELECT DISTINCT t.year FROM {table} t {where_sql} ORDER BY t.year",
        (param,),
    )
    out: list[str] = []
    for row in cursor.fetchall():
        text = str(int(row[0])) if row[0] is not None else ""
        if is_year_name(text):
            out.append(text)
    return out


def years_for_person(username: str) -> list[str]:
    name = (username or "").strip()
    layout = person_country_center(name)
    if not layout:
        return []
    country, _center = layout
    from app.sql_replica import _transaction_table

    table = _transaction_table(country)
    if not table:
        return []

    def _run() -> list[str]:
        cursor = _cursor()
        cursor.execute(f"SELECT OBJECT_ID(N'{table}', N'U')")
        if cursor.fetchone()[0] is None:
            return []
        return _years_from_table(
            cursor,
            table,
            "JOIN dbo.person p ON p.id = t.person_id "
            "WHERE p.username = ? COLLATE Latin1_General_CI_AI",
            name,
        )

    try:
        return _sql_retry(_run)
    except Exception:  # noqa: BLE001
        return []


def years_for_center(center: str) -> list[str]:
    name = (center or "").strip()
    if not name:
        return []
    name = coerce_center(name)
    country = country_for_center(name)
    if not country:
        return []
    from app.sql_replica import _transaction_table

    table = _transaction_table(country)
    if not table:
        return []

    def _run() -> list[str]:
        cursor = _cursor()
        cursor.execute(f"SELECT OBJECT_ID(N'{table}', N'U')")
        if cursor.fetchone()[0] is None:
            return []
        return _years_from_table(
            cursor,
            table,
            "JOIN dbo.person p ON p.id = t.person_id "
            "JOIN dbo.center n ON n.center_id = p.center_id "
            "WHERE n.username = ? COLLATE Latin1_General_CI_AI",
            name,
        )

    try:
        return _sql_retry(_run)
    except Exception:  # noqa: BLE001
        return []


def years_by_person_in_center(center: str) -> dict[str, list[str]]:
    """Person username → booking years for everyone in this center."""
    name = (center or "").strip()
    if not name:
        return {}
    name = coerce_center(name)
    country = country_for_center(name)
    if not country:
        return {}
    from app.sql_replica import _transaction_table

    table = _transaction_table(country)
    if not table:
        return {}

    def _run() -> dict[str, list[str]]:
        cursor = _cursor()
        cursor.execute(f"SELECT OBJECT_ID(N'{table}', N'U')")
        if cursor.fetchone()[0] is None:
            return {}
        cursor.execute(
            f"""
            SELECT p.username, t.year
            FROM {table} t
            JOIN dbo.person p ON p.id = t.person_id
            JOIN dbo.center n ON n.center_id = p.center_id
            WHERE n.username = ? COLLATE Latin1_General_CI_AI
            GROUP BY p.username, t.year
            ORDER BY p.username, t.year
            """,
            (name,),
        )
        out: dict[str, list[str]] = {}
        for username, year in cursor.fetchall():
            person = str(username or "").strip()
            text = str(int(year)) if year is not None else ""
            if person and is_year_name(text):
                years = out.setdefault(person, [])
                if text not in years:
                    years.append(text)
        return out

    try:
        return _sql_retry(_run)
    except Exception:  # noqa: BLE001
        return {}


def categories_payload(country: str) -> dict[str, Any]:
    """``categories.json``-shaped dict from ``dim_category`` / terms / headers."""
    name = (country or "").strip()
    empty: dict[str, Any] = {"categories": {}, "table_header_terms": {}, "typerules": []}
    if not name or not _sql_ready():
        return empty
    now = time.monotonic()
    hit = _CAT_CACHE.get(name)
    if hit and now - hit[0] < _CAT_TTL_SEC:
        return hit[1]

    def _run() -> dict[str, Any]:
        cursor = _cursor()
        cursor.execute(
            """
            SELECT country_id FROM dbo.country
            WHERE username = ? COLLATE Latin1_General_CI_AI
            """,
            (name,),
        )
        row = cursor.fetchone()
        if row is None:
            return empty
        country_id = int(row[0])

        cursor.execute(
            """
            SELECT category_id, local_code, label, matrix_role
            FROM dbo.dim_category
            WHERE country_id = ?
            ORDER BY local_code, label
            """,
            (country_id,),
        )
        categories: dict[str, list[str]] = {}
        id_to_label: dict[int, str] = {}
        for category_id, _code, label, _role in cursor.fetchall():
            text = str(label or "").strip()
            if not text:
                continue
            categories[text] = []
            id_to_label[int(category_id)] = text

        cursor.execute(
            """
            SELECT category_id, term
            FROM dbo.category_term
            WHERE person_id IS NULL
            ORDER BY category_id, sort_order, term_id
            """,
        )
        for category_id, term in cursor.fetchall():
            label = id_to_label.get(int(category_id))
            if not label:
                continue
            text = str(term or "").strip()
            if text:
                categories[label].append(text)

        cursor.execute(
            """
            SELECT term_key, label FROM dbo.table_header_term
            WHERE country_id = ?
            """,
            (country_id,),
        )
        headers: dict[str, str] = {}
        for key, label in cursor.fetchall():
            k = str(key or "").strip()
            v = str(label or "").strip()
            if k and v:
                headers[k] = v

        cursor.execute(
            """
            SELECT r.bank_type, d.label
            FROM dbo.type_rule r
            JOIN dbo.dim_category d ON d.category_id = r.category_id
            WHERE r.country_id = ?
            """,
            (country_id,),
        )
        typerules = []
        for bank_type, label in cursor.fetchall():
            t = str(bank_type or "").strip()
            cat = str(label or "").strip()
            if t and cat:
                typerules.append({"type": t, "category": cat})

        return {
            "categories": categories,
            "table_header_terms": headers,
            "typerules": typerules,
        }

    try:
        payload = _sql_retry(_run)
        _CAT_CACHE[name] = (time.monotonic(), payload)
        return payload
    except Exception:  # noqa: BLE001
        return empty


def personal_categories_payload(username: str) -> dict[str, list[str]]:
    """Category label → personal keyword terms for one person."""
    name = (username or "").strip()
    if not name or not _sql_ready():
        return {}

    def _run() -> dict[str, list[str]]:
        cursor = _cursor()
        cursor.execute(
            """
            SELECT d.label, t.term
            FROM dbo.category_term t
            JOIN dbo.person p ON p.id = t.person_id
            JOIN dbo.dim_category d ON d.category_id = t.category_id
            WHERE p.username = ? COLLATE Latin1_General_CI_AI
            ORDER BY d.local_code, t.sort_order, t.term_id
            """,
            (name,),
        )
        out: dict[str, list[str]] = {}
        for label, term in cursor.fetchall():
            key = str(label or "").strip()
            text = str(term or "").strip()
            if key and text:
                out.setdefault(key, []).append(text)
        return out

    try:
        return _sql_retry(_run)
    except Exception:  # noqa: BLE001
        return {}

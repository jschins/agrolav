"""SQL Server catalog: countries, centers, people, years, categories.

Used when workspace folders are absent. Bookings stay in ``sql_replica``.
"""
from __future__ import annotations

from typing import Any

from app.yearpath import is_year_name


def _sql_ready() -> bool:
    from app import user_store

    if not user_store.database_url():
        return False
    user_store.init_user_store()
    return user_store._SQL is not None


def _cursor():
    from app import user_store

    return user_store._sql_connect().cursor()


def list_country_usernames() -> list[str]:
    if not _sql_ready():
        return []
    try:
        cursor = _cursor()
        cursor.execute("SELECT username FROM dbo.country ORDER BY username")
        return [str(row[0]).strip() for row in cursor.fetchall() if str(row[0] or "").strip()]
    except Exception:  # noqa: BLE001
        return []


def list_center_usernames(country: str) -> list[str]:
    name = (country or "").strip()
    if not name or not _sql_ready():
        return []
    try:
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
    except Exception:  # noqa: BLE001
        return []


def country_for_center(center: str) -> str | None:
    name = (center or "").strip()
    if not name or not _sql_ready():
        return None
    try:
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
    except Exception:  # noqa: BLE001
        return None
    return None


def center_exists(center: str) -> bool:
    name = (center or "").strip()
    if not name or not _sql_ready():
        return False
    try:
        cursor = _cursor()
        cursor.execute(
            "SELECT 1 FROM dbo.center WHERE username = ? COLLATE Latin1_General_CI_AI",
            (name,),
        )
        return cursor.fetchone() is not None
    except Exception:  # noqa: BLE001
        return False


def people_in_center(center: str) -> list[str]:
    name = (center or "").strip()
    if not name or not _sql_ready():
        return []
    try:
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
    except Exception:  # noqa: BLE001
        return []


def person_country_center(username: str) -> tuple[str, str] | None:
    name = (username or "").strip()
    if not name or not _sql_ready():
        return None
    try:
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
    except Exception:  # noqa: BLE001
        return None
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
    try:
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
    except Exception:  # noqa: BLE001
        return []


def years_for_center(center: str) -> list[str]:
    name = (center or "").strip()
    country = country_for_center(name)
    if not country:
        return []
    from app.sql_replica import _transaction_table

    table = _transaction_table(country)
    if not table:
        return []
    try:
        cursor = _cursor()
        cursor.execute(f"SELECT OBJECT_ID(N'{table}', N'U')")
        if cursor.fetchone()[0] is None:
            return []
        years = _years_from_table(
            cursor,
            table,
            "JOIN dbo.person p ON p.id = t.person_id "
            "JOIN dbo.center n ON n.center_id = p.center_id "
            "WHERE n.username = ? COLLATE Latin1_General_CI_AI",
            name,
        )
        return years
    except Exception:  # noqa: BLE001
        return []


def categories_payload(country: str) -> dict[str, Any]:
    """``categories.json``-shaped dict from ``dim_category`` / terms / headers."""
    name = (country or "").strip()
    empty: dict[str, Any] = {"categories": {}, "table_header_terms": {}, "typerules": []}
    if not name or not _sql_ready():
        return empty
    try:
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
    except Exception:  # noqa: BLE001
        return empty

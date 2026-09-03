"""SQL Server catalog: countries, centers, people, years, categories.

Used when on-disk center folders are absent. Bookings stay in ``sql_replica``.
"""
from __future__ import annotations

import re
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


def category_id_bounds(country_id: int) -> tuple[int, int]:
    """Inclusive ``(lo, hi)`` category_id range for a country's local codes.

    Category codes are uniformly four digits, ``local_code`` 1..9999, and
    ``category_id = country_id * 10000 + local_code``.
    """
    base = int(country_id) * 10000
    return base, base + 9999


_CK_GE = re.compile(r"category_id\s*>=\s*(\d+)", re.I)
_CK_LE = re.compile(r"category_id\s*<=\s*(\d+)", re.I)
_CK_LT = re.compile(r"category_id\s*<\s*(\d+)", re.I)


def _parse_txn_cat_check(definition: str) -> tuple[int, int] | None:
    """Inclusive bounds from ``ck_txn_*_cat`` (BETWEEN / >= / <)."""
    text = (
        str(definition or "")
        .replace("[", "")
        .replace("]", "")
        .replace("(", "")
        .replace(")", "")
    )
    ge = _CK_GE.search(text)
    if not ge:
        return None
    lo = int(ge.group(1))
    le = _CK_LE.search(text)
    if le:
        return lo, int(le.group(1))
    lt = _CK_LT.search(text)
    if lt:
        return lo, int(lt.group(1)) - 1
    return None


def _txn_cat_check_bounds(cursor, table: str) -> tuple[int, int] | None:
    if not table:
        return None
    ident = table.split(".")[-1]
    cursor.execute(
        """
        SELECT cc.definition
        FROM sys.check_constraints cc
        INNER JOIN sys.tables t ON t.object_id = cc.parent_object_id
        INNER JOIN sys.schemas s ON s.schema_id = t.schema_id
        WHERE s.name = N'dbo' AND t.name = ? AND cc.name LIKE N'ck_txn_%_cat'
        """,
        (ident,),
    )
    row = cursor.fetchone()
    if row is None:
        return None
    return _parse_txn_cat_check(str(row[0] or ""))


def _alloc_category_id_bounds(
    cursor,
    table: str,
    country_id: int,
    used_ids: set[int],
) -> tuple[int, int]:
    """Range a new ``category_id`` may use (must satisfy the booking-table CHECK)."""
    checked = _txn_cat_check_bounds(cursor, table)
    if checked:
        return checked
    if used_ids:
        return min(used_ids), max(used_ids)
    return category_id_bounds(country_id)


def _new_booking_category_id(used: set[int], local_code: int, lo: int, hi: int) -> int:
    """Prefer ``local_code`` when that id is free and inside the table CHECK."""
    code = int(local_code)
    if lo <= code <= hi and code not in used:
        return code
    return _next_booking_category_id(used, lo, hi)


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


def list_uploaded_files(username: str) -> list[dict[str, str]]:
    """Uploaded filenames recorded on ``dbo.uploaded_files`` for this person."""
    name = (username or "").strip()
    if not name or not _sql_ready():
        return []

    def _run() -> list[dict[str, str]]:
        cursor = _cursor()
        cursor.execute(
            """
            SELECT f.file_name, f.format
            FROM dbo.uploaded_files f
            JOIN dbo.account a ON a.account_id = f.account_id
            JOIN dbo.person p ON p.id = a.person_id
            WHERE p.username = ? COLLATE Latin1_General_CI_AI
            ORDER BY f.uploaded_file_id
            """,
            (name,),
        )
        out: list[dict[str, str]] = []
        for file_name, fmt in cursor.fetchall():
            stored = str(file_name or "").strip()
            if stored:
                out.append({"file_name": stored, "format": str(fmt or "").strip()})
        return out

    try:
        return _sql_retry(_run)
    except Exception:  # noqa: BLE001
        return []


def record_uploaded_file(username: str, file_name: str, fmt: str | None) -> None:
    """INSERT one upload filename for the person's first account (skip duplicates)."""
    name = (username or "").strip()
    stored = str(file_name or "").strip()[:256]
    if not name or not stored or not _sql_ready():
        return

    def _run() -> None:
        from app import user_store

        cursor = _cursor()
        cursor.execute(
            "SELECT id FROM dbo.person WHERE username = ? COLLATE Latin1_General_CI_AI",
            (name,),
        )
        row = cursor.fetchone()
        if row is None:
            return
        person_id = int(row[0])
        cursor.execute(
            """
            SELECT TOP 1 account_id FROM dbo.account
            WHERE person_id = ?
            ORDER BY account_id
            """,
            (person_id,),
        )
        acc = cursor.fetchone()
        if acc is None:
            return
        account_id = int(acc[0])
        cursor.execute(
            """
            SELECT 1 FROM dbo.uploaded_files
            WHERE account_id = ? AND file_name = ?
            """,
            (account_id, stored),
        )
        if cursor.fetchone():
            return
        cursor.execute(
            """
            INSERT INTO dbo.uploaded_files (account_id, file_name, format)
            VALUES (?, ?, ?)
            """,
            (account_id, stored, (str(fmt or "").strip()[:64] or None)),
        )
        user_store._sql_connect().commit()

    try:
        _sql_retry(_run)
    except Exception as exc:  # noqa: BLE001
        print(f"sql catalog: could not record upload file: {exc}")


def wipe_country_year(country: str, year: str) -> dict[str, Any]:
    """Delete one year's bookings for every person in ``country``.

    Removes rows from ``dbo.transaction_{country}`` and ``dbo.category_total``
    for that year, then all ``dbo.uploaded_files`` for accounts in the country
    (that table has no year column). Recomputes ``dbo.account.last_booked``.
    """
    from app import user_store
    from app.sql_replica import _transaction_table
    from app.yearpath import parse_year

    name = (country or "").strip()
    y = int(parse_year(year))
    table = _transaction_table(name)
    if not name or not table:
        raise ValueError(f"Unknown country {country!r}")
    if not _sql_ready():
        raise RuntimeError("SQL is not configured")

    def _run() -> dict[str, Any]:
        cursor = _cursor()
        cursor.execute(f"SELECT OBJECT_ID(N'{table}', N'U')")
        if cursor.fetchone()[0] is None:
            raise ValueError(f"Missing transaction table {table}")
        cursor.execute(
            """
            SELECT country_id FROM dbo.country
            WHERE username = ? COLLATE Latin1_General_CI_AI
            """,
            (name,),
        )
        row = cursor.fetchone()
        if row is None:
            raise ValueError(f"Unknown country {country!r}")
        country_id = int(row[0])

        cursor.execute(
            f"""
            SELECT COUNT(*) FROM {table}
            WHERE year = ?
              AND person_id IN (SELECT id FROM dbo.person WHERE country_id = ?)
            """,
            (y, country_id),
        )
        tx_count = int(cursor.fetchone()[0])
        cursor.execute(
            f"""
            DELETE FROM {table}
            WHERE year = ?
              AND person_id IN (SELECT id FROM dbo.person WHERE country_id = ?)
            """,
            (y, country_id),
        )
        cursor.execute(
            """
            DELETE FROM dbo.category_total
            WHERE year = ?
              AND person_id IN (SELECT id FROM dbo.person WHERE country_id = ?)
            """,
            (y, country_id),
        )
        cursor.execute(
            """
            SELECT COUNT(*) FROM dbo.uploaded_files
            WHERE account_id IN (
                SELECT a.account_id
                FROM dbo.account a
                JOIN dbo.person p ON p.id = a.person_id
                WHERE p.country_id = ?
            )
            """,
            (country_id,),
        )
        file_count = int(cursor.fetchone()[0])
        cursor.execute(
            """
            DELETE FROM dbo.uploaded_files
            WHERE account_id IN (
                SELECT a.account_id
                FROM dbo.account a
                JOIN dbo.person p ON p.id = a.person_id
                WHERE p.country_id = ?
            )
            """,
            (country_id,),
        )
        cursor.execute(
            f"""
            UPDATE a
            SET last_booked = x.mx
            FROM dbo.account a
            INNER JOIN dbo.person p ON p.id = a.person_id
            LEFT JOIN (
                SELECT account_id, MAX(booked_on) AS mx
                FROM {table}
                GROUP BY account_id
            ) x ON x.account_id = a.account_id
            WHERE p.country_id = ?
            """,
            (country_id,),
        )
        user_store._sql_connect().commit()
        return {
            "country": name,
            "year": str(y),
            "transactions": tx_count,
            "files": file_count,
        }

    return _sql_retry(_run)


list_account_balance_files = list_uploaded_files
record_account_balance_file = record_uploaded_file


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


def category_codes_for_country(country: str) -> frozenset[int]:
    """Category ``local_code`` values registered for ``country``."""
    name = (country or "").strip()
    if not name or not _sql_ready():
        return frozenset()
    cursor = _cursor()
    cursor.execute(
        """
        SELECT d.local_code
        FROM dbo.dim_category d
        JOIN dbo.country c ON c.country_id = d.country_id
        WHERE c.username = ? COLLATE Latin1_General_CI_AI
        ORDER BY d.local_code
        """,
        (name,),
    )
    return frozenset(int(row[0]) for row in cursor.fetchall())


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
        for category_id, code, label, role in cursor.fetchall():
            text = str(label or "").strip()
            if not text:
                continue
            if str(role or "").strip():
                cat_name = text
            elif code is not None:
                cat_name = f"{int(code):04d} {text}"
            else:
                continue
            categories[cat_name] = []
            id_to_label[int(category_id)] = cat_name

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
            SELECT r.bank_type, d.local_code, d.label
            FROM dbo.type_rule r
            JOIN dbo.dim_category d ON d.category_id = r.category_id
            WHERE r.country_id = ?
            """,
            (country_id,),
        )
        typerules = []
        for bank_type, local_code, label in cursor.fetchall():
            t = str(bank_type or "").strip()
            plain = str(label or "").strip()
            if t and plain:
                rule_cat = f"{int(local_code):04d} {plain}"
                typerules.append({"type": t, "category": rule_cat})

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


def clear_catalog_cache() -> None:
    _CAT_CACHE.clear()


def save_category_terms(
    category_name: str,
    terms: list[str],
    *,
    person: str | None = None,
) -> None:
    """Replace general (person_id NULL) or personal keyword rows in ``dbo.category_term``."""
    label = (category_name or "").strip()
    if not label or not _sql_ready():
        return
    cleaned = [str(item).strip().lower() for item in terms if str(item or "").strip()]
    person_name = (person or "").strip() or None
    country = ""
    if person_name:
        layout = person_country_center(person_name)
        country = layout[0] if layout else ""
    if not country:
        from app.runtime import active_center, active_country

        country = (active_country() or country_for_center(active_center() or "") or "").strip()
    if not country:
        raise ValueError(f"Cannot save terms for {label!r}: no country")
    try:
        code = int(label[:4])
    except ValueError:
        code = None

    def _run() -> None:
        from app import user_store

        conn = user_store._sql_connect()
        cursor = conn.cursor()
        was = conn.autocommit
        try:
            conn.autocommit = False
            cursor.execute(
                """
                SELECT d.category_id
                FROM dbo.dim_category d
                JOIN dbo.country c ON c.country_id = d.country_id
                WHERE c.username = ? COLLATE Latin1_General_CI_AI
                  AND (d.label = ? OR d.local_code = ?)
                """,
                (country, label, code),
            )
            row = cursor.fetchone()
            if row is None:
                raise ValueError(f"Unknown category {label!r} for {country!r}")
            category_id = int(row[0])
            person_id: int | None = None
            if person_name:
                cursor.execute(
                    "SELECT id FROM dbo.person WHERE username = ? COLLATE Latin1_General_CI_AI",
                    (person_name,),
                )
                prow = cursor.fetchone()
                if prow is None:
                    raise ValueError(f"Unknown person {person_name!r}")
                person_id = int(prow[0])
                cursor.execute(
                    "DELETE FROM dbo.category_term WHERE category_id = ? AND person_id = ?",
                    (category_id, person_id),
                )
            else:
                cursor.execute(
                    "DELETE FROM dbo.category_term WHERE category_id = ? AND person_id IS NULL",
                    (category_id,),
                )
            if cleaned:
                cursor.fast_executemany = False
                cursor.executemany(
                    """
                    INSERT INTO dbo.category_term (category_id, person_id, term, sort_order)
                    VALUES (?, ?, ?, ?)
                    """,
                    [(category_id, person_id, term, index) for index, term in enumerate(cleaned)],
                )
            conn.commit()
            _CAT_CACHE.clear()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            raise
        finally:
            try:
                conn.autocommit = was
            except Exception:
                pass

    _sql_retry(_run)


def _country_id_for(cursor, country: str) -> int | None:
    cursor.execute(
        """
        SELECT country_id FROM dbo.country
        WHERE username = ? COLLATE Latin1_General_CI_AI
        """,
        (country,),
    )
    row = cursor.fetchone()
    return int(row[0]) if row else None


def display_digits(rows: list[dict[str, Any]]) -> int:
    """Frontend code-padding width for a country's local codes.

    Uniform backend storage is four digits; only ``beheer`` actually uses
    codes >= 100. This lets the frontend pad to 2 for everyone else.
    """
    codes = [int(row.get("local_code") or 0) for row in rows]
    return 4 if any(code >= 100 for code in codes) else 2


def booking_categories_payload(country: str) -> dict[str, Any]:
    """Booking rows in ``dbo.dim_category`` (excludes Balance / Updated footers)."""
    name = (country or "").strip()
    empty: dict[str, Any] = {
        "country": name,
        "country_id": None,
        "remainder_id": None,
        "digits": 2,
        "categories": [],
    }
    if not name or not _sql_ready():
        return empty

    def _run() -> dict[str, Any]:
        cursor = _cursor()
        country_id = _country_id_for(cursor, name)
        if country_id is None:
            return empty
        cursor.execute(
            """
            SELECT category_id, local_code, label, is_remainder, matrix_role
            FROM dbo.dim_category
            WHERE country_id = ?
            ORDER BY local_code, label
            """,
            (country_id,),
        )
        rows: list[dict[str, Any]] = []
        remainder_id: int | None = None
        for category_id, local_code, label, is_remainder, role in cursor.fetchall():
            if str(role or "").strip():
                continue
            cid = int(category_id)
            remainder = bool(int(is_remainder or 0))
            if remainder:
                remainder_id = cid
            rows.append(
                {
                    "category_id": cid,
                    "local_code": int(local_code),
                    "label": str(label or "").strip(),
                    "is_remainder": remainder,
                }
            )
        return {
            "country": name,
            "country_id": country_id,
            "remainder_id": remainder_id,
            "digits": display_digits(rows),
            "categories": rows,
        }

    try:
        return _sql_retry(_run)
    except Exception:  # noqa: BLE001
        return empty


def save_booking_categories(country: str, items: list[dict[str, Any]]) -> dict[str, Any]:
    """Replace the country's booking catalog. Deleted ids remap to unclassified."""
    name = (country or "").strip()
    if not name or not _sql_ready():
        raise ValueError("SQL Server is not configured")
    parsed = _parse_catalog_items(items)

    def _run() -> dict[str, Any]:
        from app import user_store
        from app.sql_replica import _transaction_table

        conn = user_store._sql_connect()
        cursor = conn.cursor()
        was = conn.autocommit
        try:
            conn.autocommit = False
            country_id = _country_id_for(cursor, name)
            if country_id is None:
                raise ValueError(f"Unknown country: {name}")
            table = _transaction_table(name)
            if table is None:
                raise ValueError(f"Cannot derive transaction table for {name!r}")
            cursor.execute(
                """
                SELECT category_id, local_code, label, is_remainder, matrix_role
                FROM dbo.dim_category
                WHERE country_id = ?
                """,
                (country_id,),
            )
            existing: dict[int, dict[str, Any]] = {}
            footer_ids: set[int] = set()
            for category_id, local_code, label, is_remainder, role in cursor.fetchall():
                cid = int(category_id)
                if str(role or "").strip():
                    footer_ids.add(cid)
                    continue
                existing[cid] = {
                    "local_code": int(local_code),
                    "label": str(label or "").strip(),
                    "is_remainder": bool(int(is_remainder or 0)),
                }
            used_ids = set(existing) | footer_ids
            lo, hi = _alloc_category_id_bounds(cursor, table, country_id, used_ids)
            allocated: list[dict[str, Any]] = []
            for item in parsed:
                cid = item["category_id"]
                if cid is None:
                    cid = _new_booking_category_id(
                        used_ids, int(item["local_code"]), lo, hi
                    )
                    used_ids.add(cid)
                    item = {**item, "category_id": cid, "is_new": True}
                else:
                    if cid in footer_ids:
                        raise ValueError(f"Cannot edit footer category_id {cid}")
                    if cid not in existing:
                        raise ValueError(f"Unknown category_id {cid}")
                    item = {**item, "is_new": False}
                allocated.append(item)
            keep_ids = {int(item["category_id"]) for item in allocated}
            deleted_ids = sorted(existing.keys() - keep_ids)
            remainder_id = next(
                int(item["category_id"]) for item in allocated if item["is_remainder"]
            )
            remainder_item = next(item for item in allocated if item["is_remainder"])
            if remainder_item["is_new"]:
                _insert_dim_category(
                    cursor,
                    country_id,
                    {
                        **remainder_item,
                        "local_code": -int(remainder_item["category_id"]),
                        "label": f"__tmp__{int(remainder_item['category_id'])}",
                    },
                )

            if deleted_ids:
                _remap_category_fks(
                    cursor,
                    table=table,
                    deleted_ids=deleted_ids,
                    remainder_id=remainder_id,
                )
                _delete_dim_categories(cursor, deleted_ids)

            for item in allocated:
                if item["is_new"]:
                    continue
                cid = int(item["category_id"])
                cursor.execute(
                    """
                    UPDATE dbo.dim_category
                    SET local_code = ?, label = ?
                    WHERE category_id = ?
                    """,
                    -cid,
                    f"__tmp__{cid}",
                    cid,
                )
            remainder_new_id = (
                int(remainder_item["category_id"]) if remainder_item["is_new"] else None
            )
            for item in allocated:
                if not item["is_new"]:
                    continue
                if remainder_new_id is not None and int(item["category_id"]) == remainder_new_id:
                    continue
                cid = int(item["category_id"])
                _insert_dim_category(
                    cursor,
                    country_id,
                    {
                        **item,
                        "local_code": -cid,
                        "label": f"__tmp__{cid}",
                    },
                )
            for item in allocated:
                cid = int(item["category_id"])
                cursor.execute(
                    """
                    UPDATE dbo.dim_category
                    SET local_code = ?, label = ?, is_remainder = ?
                    WHERE category_id = ?
                    """,
                    int(item["local_code"]),
                    str(item["label"]),
                    1 if item["is_remainder"] else 0,
                    cid,
                )
            conn.commit()
            _CAT_CACHE.clear()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            raise
        finally:
            try:
                conn.autocommit = was
            except Exception:
                pass
        return booking_categories_payload(name)

    return _sql_retry(_run)


def _parse_catalog_items(
    items: list[dict[str, Any]], digits: int = 4
) -> list[dict[str, Any]]:
    if not isinstance(items, list) or not items:
        raise ValueError("At least one category is required")
    width = max(1, int(digits or 4))
    max_code = 10**width - 1
    parsed: list[dict[str, Any]] = []
    codes: set[int] = set()
    labels: set[str] = set()
    remainders = 0
    for raw in items:
        if not isinstance(raw, dict):
            raise ValueError("Each category must be an object")
        cid_raw = raw.get("category_id")
        cid = None if cid_raw in (None, "", 0) else int(cid_raw)
        try:
            code = int(raw.get("local_code"))
        except (TypeError, ValueError) as exc:
            raise ValueError("Each category needs a numeric code") from exc
        if code < 1 or code > max_code or code in (98, 99):
            raise ValueError(f"Category code must be 1–{max_code} (98/99 are system), not {code}")
        label = str(raw.get("label") or "").strip()
        if not label:
            raise ValueError("Each category needs a label")
        if code in codes:
            raise ValueError(f"Duplicate category code {code:0{width}d}")
        key = label.casefold()
        if key in labels:
            raise ValueError(f"Duplicate category label {label!r}")
        codes.add(code)
        labels.add(key)
        remainder = bool(raw.get("is_remainder"))
        if remainder:
            remainders += 1
        parsed.append(
            {
                "category_id": cid,
                "local_code": code,
                "label": label,
                "is_remainder": remainder,
            }
        )
    if remainders != 1:
        raise ValueError("Mark exactly one category as unclassified")
    return parsed


def _next_booking_category_id(used: set[int], lo: int, hi: int) -> int:
    for cid in range(lo + 3, hi + 1):
        if cid not in used:
            return cid
    raise ValueError("No free category_id left in this country's range")


def _sql_in(ids: list[int]) -> tuple[str, list[int]]:
    placeholders = ", ".join("?" for _ in ids)
    return placeholders, [int(i) for i in ids]


def _remap_category_fks(
    cursor,
    *,
    table: str,
    deleted_ids: list[int],
    remainder_id: int,
) -> None:
    placeholders, values = _sql_in(deleted_ids)
    params = [remainder_id, *values]
    cursor.execute(
        f"UPDATE {table} SET category_id = ? WHERE category_id IN ({placeholders})",
        params,
    )
    cursor.execute("SELECT OBJECT_ID(N'dbo.type_rule', N'U')")
    if cursor.fetchone()[0]:
        cursor.execute(
            f"""
            UPDATE dbo.type_rule SET category_id = ?
            WHERE category_id IN ({placeholders})
            """,
            params,
        )
    cursor.execute(
        f"DELETE FROM dbo.category_term WHERE category_id IN ({placeholders})",
        values,
    )
    cursor.execute("SELECT OBJECT_ID(N'dbo.category_total', N'U')")
    if cursor.fetchone()[0]:
        cursor.execute(
            f"DELETE FROM dbo.category_total WHERE category_id IN ({placeholders})",
            values,
        )


def _insert_dim_category(cursor, country_id: int, item: dict[str, Any]) -> None:
    cursor.execute(
        """
        INSERT INTO dbo.dim_category
            (category_id, country_id, local_code, label, is_remainder, matrix_role)
        VALUES (?, ?, ?, ?, ?, NULL)
        """,
        int(item["category_id"]),
        country_id,
        int(item["local_code"]),
        str(item["label"]),
        1 if item["is_remainder"] else 0,
    )


def _delete_dim_categories(cursor, deleted_ids: list[int]) -> None:
    placeholders, values = _sql_in(deleted_ids)
    cursor.execute(
        f"DELETE FROM dbo.dim_category WHERE category_id IN ({placeholders})",
        values,
    )

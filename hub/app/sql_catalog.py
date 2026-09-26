"""SQL Server catalog: countries, centers, people, years, categories.

Used when on-disk center folders are absent. Bookings stay in ``sql_replica``.
"""
from __future__ import annotations

import re
import threading
import time
from decimal import Decimal
from typing import Any

from app.yearpath import is_year_name

_CAT_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_CAT_TTL_SEC = 3.0
_term_write_lock = threading.Lock()
_TERM_LANG_COL = re.compile(r"^term_lang([1-9]\d*)$")


def _language_id(language_id: object) -> int:
    try:
        lid = int(language_id)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        lid = 1
    return lid if lid >= 1 else 1


def _language_target_column(cursor: Any, table: str, language_id: object) -> str | None:
    """``term_lang{id}`` on ``dbo.language`` or ``dbo.language_long``.

    A ``language_id`` with no matching column uses ``term_lang1``.
    """
    lid = _language_id(language_id)
    cursor.execute(
        """
        SELECT COLUMN_NAME
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = N'dbo' AND TABLE_NAME = ?
        """,
        (table,),
    )
    by_id: dict[int, str] = {}
    for (name,) in cursor.fetchall():
        match = _TERM_LANG_COL.match(str(name or ""))
        if match:
            by_id[int(match.group(1))] = match.group(0)
    if 1 not in by_id:
        return None
    return by_id.get(lid, by_id[1])


def _language_header_terms(cursor: Any, language_id: object) -> dict[str, str]:
    """English ``term_lang1`` → label for ``dbo.country.language_id``.

    Only fallback: a ``language_id`` with no ``term_lang{id}`` column uses
    ``term_lang1``. Does not read ``table_header_term`` or JSON.
    """
    target = _language_target_column(cursor, "language", language_id)
    if target is None:
        raise RuntimeError("dbo.language.term_lang1 is required")
    cursor.execute(f"SELECT term_lang1, {target} FROM dbo.language")
    headers: dict[str, str] = {}
    for key, label in cursor.fetchall():
        k = str(key or "").strip()
        v = str(label or "").strip()
        if k and v:
            headers[k] = v
    return headers


def _language_long_terms(cursor: Any, language_id: object) -> dict[str, str]:
    """English ``term_key`` → long label from ``dbo.language_long``.

    Missing table yields an empty map so settings still load.
    """
    cursor.execute("SELECT OBJECT_ID(N'dbo.language_long', N'U')")
    row = cursor.fetchone()
    if row is None or not row[0]:
        return {}
    target = _language_target_column(cursor, "language_long", language_id)
    if target is None:
        return {}
    cursor.execute(f"SELECT term_key, {target} FROM dbo.language_long")
    texts: dict[str, str] = {}
    for key, label in cursor.fetchall():
        k = str(key or "").strip()
        v = str(label or "").strip()
        if k and v:
            texts[k] = v
    return texts


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


def country_username_for_scope(center: str) -> str:
    """Country login name for a center path, or the name itself when it is a country."""
    found = country_for_center(center)
    if found:
        return found
    name = (center or "").strip()
    if not name or not _sql_ready():
        return ""

    def _run() -> str:
        cursor = _cursor()
        cursor.execute(
            """
            SELECT username FROM dbo.country
            WHERE username = ? COLLATE Latin1_General_CI_AI
            """,
            (name,),
        )
        row = cursor.fetchone()
        if row and str(row[0] or "").strip():
            return str(row[0]).strip()
        return ""

    try:
        return _sql_retry(_run)
    except Exception:  # noqa: BLE001
        return ""


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


def wipe_country_year(
    country: str,
    year: str,
    *,
    center: str | None = None,
    person: str | None = None,
    account: str | None = None,
) -> dict[str, Any]:
    """Delete one year's bookings in ``country``, optionally narrowed.

    ``account`` (IBAN) → that account; ``person`` → that person; ``center`` →
    every person in the center; otherwise every person in the country.
    Also drops ``dbo.uploaded_files`` for the affected accounts (no year
    column) and recomputes ``dbo.account.last_booked``.
    """
    from app import user_store
    from app.sql_replica import _transaction_table
    from app.yearpath import parse_year

    name = (country or "").strip()
    center_name = (center or "").strip() or None
    person_name = (person or "").strip() or None
    account_key = (account or "").strip() or None
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

        person_ids: list[int] = []
        account_ids: list[int] = []
        if account_key:
            iban = account_key.replace(" ", "").upper()
            cursor.execute(
                """
                SELECT a.account_id, a.person_id
                FROM dbo.account a
                JOIN dbo.person p ON p.id = a.person_id
                JOIN dbo.center n ON n.center_id = p.center_id
                WHERE n.country_id = ?
                  AND REPLACE(UPPER(ISNULL(a.iban, N'')), N' ', N'') = ?
                  AND (
                    ? IS NULL
                    OR p.username = ? COLLATE Latin1_General_CI_AI
                  )
                  AND (
                    ? IS NULL
                    OR n.username = ? COLLATE Latin1_General_CI_AI
                  )
                """,
                (
                    country_id,
                    iban,
                    person_name,
                    person_name,
                    center_name,
                    center_name,
                ),
            )
            found = cursor.fetchall()
            if not found:
                raise ValueError(f"Unknown account {account_key!r}")
            account_ids = [int(r[0]) for r in found if r[0] is not None]
            person_ids = [int(r[1]) for r in found if r[1] is not None]
        elif person_name:
            cursor.execute(
                """
                SELECT p.id
                FROM dbo.person p
                JOIN dbo.center n ON n.center_id = p.center_id
                WHERE n.country_id = ?
                  AND p.username = ? COLLATE Latin1_General_CI_AI
                  AND (
                    ? IS NULL
                    OR n.username = ? COLLATE Latin1_General_CI_AI
                  )
                """,
                (country_id, person_name, center_name, center_name),
            )
            found = cursor.fetchall()
            if not found:
                raise ValueError(f"Unknown person {person_name!r}")
            person_ids = [int(r[0]) for r in found if r[0] is not None]
            cursor.execute(
                f"""
                SELECT account_id FROM dbo.account
                WHERE person_id IN ({",".join("?" * len(person_ids))})
                """,
                tuple(person_ids),
            )
            account_ids = [int(r[0]) for r in cursor.fetchall() if r[0] is not None]
        elif center_name:
            cursor.execute(
                """
                SELECT p.id
                FROM dbo.person p
                JOIN dbo.center n ON n.center_id = p.center_id
                WHERE n.country_id = ?
                  AND n.username = ? COLLATE Latin1_General_CI_AI
                """,
                (country_id, center_name),
            )
            person_ids = [int(r[0]) for r in cursor.fetchall() if r[0] is not None]
            if person_ids:
                cursor.execute(
                    f"""
                    SELECT account_id FROM dbo.account
                    WHERE person_id IN ({",".join("?" * len(person_ids))})
                    """,
                    tuple(person_ids),
                )
                account_ids = [int(r[0]) for r in cursor.fetchall() if r[0] is not None]
        else:
            cursor.execute(
                "SELECT id FROM dbo.person WHERE country_id = ?",
                (country_id,),
            )
            person_ids = [int(r[0]) for r in cursor.fetchall() if r[0] is not None]
            if person_ids:
                cursor.execute(
                    f"""
                    SELECT account_id FROM dbo.account
                    WHERE person_id IN ({",".join("?" * len(person_ids))})
                    """,
                    tuple(person_ids),
                )
                account_ids = [int(r[0]) for r in cursor.fetchall() if r[0] is not None]

        if not person_ids and not account_ids:
            return {
                "country": name,
                "year": str(y),
                "transactions": 0,
                "files": 0,
            }

        if account_key and account_ids:
            acc_ph = ",".join("?" * len(account_ids))
            tx_where = f"year = ? AND account_id IN ({acc_ph})"
            tx_params: tuple[object, ...] = (y, *account_ids)
            tot_where = ""
            tot_params: tuple[object, ...] = ()
        else:
            per_ph = ",".join("?" * len(person_ids))
            tx_where = f"year = ? AND person_id IN ({per_ph})"
            tx_params = (y, *person_ids)
            tot_where = f"year = ? AND person_id IN ({per_ph})"
            tot_params = (y, *person_ids)

        cursor.execute(f"SELECT COUNT(*) FROM {table} WHERE {tx_where}", tx_params)
        tx_count = int(cursor.fetchone()[0])
        cursor.execute(f"DELETE FROM {table} WHERE {tx_where}", tx_params)
        if tot_where:
            cursor.execute(
                f"DELETE FROM dbo.category_total WHERE {tot_where}",
                tot_params,
            )

        file_count = 0
        if account_ids:
            acc_ph = ",".join("?" * len(account_ids))
            cursor.execute(
                f"SELECT COUNT(*) FROM dbo.uploaded_files WHERE account_id IN ({acc_ph})",
                tuple(account_ids),
            )
            file_count = int(cursor.fetchone()[0])
            cursor.execute(
                f"DELETE FROM dbo.uploaded_files WHERE account_id IN ({acc_ph})",
                tuple(account_ids),
            )
            cursor.execute(
                f"""
                UPDATE a
                SET last_booked = x.mx
                FROM dbo.account a
                LEFT JOIN (
                    SELECT account_id, MAX(booked_on) AS mx
                    FROM {table}
                    GROUP BY account_id
                ) x ON x.account_id = a.account_id
                WHERE a.account_id IN ({acc_ph})
                """,
                tuple(account_ids),
            )
        user_store._sql_connect().commit()
        return {
            "country": name,
            "year": str(y),
            "transactions": tx_count,
            "files": file_count,
        }

    return _sql_retry(_run)


def clear_bookings(
    country: str,
    *,
    center: str | None = None,
    person: str | None = None,
    account: str | None = None,
    whole_country: bool = False,
    statements: bool = False,
    categorizations: bool = False,
    journal: bool = False,
    afschrijvingen: bool = False,
) -> dict[str, Any]:
    """Drop bank statements, reset categories, and/or clear journal tables.

    ``whole_country`` updates every row of ``dbo.transaction_{country}``.
    Otherwise the rows are limited to ``account``, ``person``, or ``center``.
    Terms (``dbo.category_term``) are not touched. Category reset sets
    ``modification = -1`` and ``category_id`` to ``category_role = remainder``,
    as two updates. ``journal`` deletes every ``dbo.journal`` row for this
    country. ``afschrijvingen`` deletes every ``dbo.afschrijvingen`` row for
    this country. Those tables are country-wide, not person or account.
    """
    from app import user_store
    from app.sql_replica import _transaction_table
    from shared.balance_values import require_remainder_row, spaar_source_exclude_clause

    name = (country or "").strip()
    table = _transaction_table(name)
    if not name or not table:
        raise ValueError(f"Unknown country {country!r}")
    if not statements and not categorizations and not journal and not afschrijvingen:
        raise ValueError("Choose at least one wipe action")
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
        where_sql, where_params, person_ids, account_ids = _wipe_scope(
            cursor,
            country_id,
            center=None if whole_country else center,
            person=None if whole_country else person,
            account=None if whole_country else account,
            whole_country=whole_country,
        )
        tx_count = 0
        if categorizations:
            remainder_id, _remainder_code = require_remainder_row(country_id, cursor)
            cursor.execute(
                f"UPDATE {table} SET modification = -1{where_sql}",
                where_params,
            )
            cursor.execute(
                f"UPDATE {table} SET category_id = ?{where_sql}",
                (remainder_id, *where_params),
            )
        if statements:
            cursor.execute(f"SELECT COUNT(*) FROM {table}{where_sql}", where_params)
            tx_count = int(cursor.fetchone()[0])
            cursor.execute(f"DELETE FROM {table}{where_sql}", where_params)
            if account_ids:
                acc_ph = ",".join("?" * len(account_ids))
                cursor.execute(
                    f"DELETE FROM dbo.uploaded_files WHERE account_id IN ({acc_ph})",
                    tuple(account_ids),
                )
                cursor.execute(
                    f"""
                    UPDATE a
                    SET last_booked = x.mx
                    FROM dbo.account a
                    LEFT JOIN (
                        SELECT account_id, MAX(booked_on) AS mx
                        FROM {table}
                        GROUP BY account_id
                    ) x ON x.account_id = a.account_id
                    WHERE a.account_id IN ({acc_ph})
                    """,
                    tuple(account_ids),
                )
        if journal:
            cursor.execute(
                "DELETE j FROM dbo.journal j "
                "JOIN dbo.dim_category d ON d.category_id = j.category_from "
                "WHERE d.country_id = ?",
                (int(country_id),),
            )
        if afschrijvingen:
            cursor.execute("SELECT OBJECT_ID(N'dbo.afschrijvingen', N'U')")
            if cursor.fetchone()[0] is None:
                raise ValueError("dbo.afschrijvingen is missing")
            cursor.execute(
                "DELETE a FROM dbo.afschrijvingen a "
                "JOIN dbo.dim_category d ON d.category_id = a.category_id_van "
                "WHERE d.country_id = ?",
                (int(country_id),),
            )
        if person_ids and (statements or categorizations):
            _rebuild_category_totals(cursor, table, country_id, person_ids, spaar_source_exclude_clause)
        user_store._sql_connect().commit()
        return {
            "country": name,
            "transactions": tx_count,
            "statements": bool(statements),
            "categorizations": bool(categorizations),
            "journal": bool(journal),
            "afschrijvingen": bool(afschrijvingen),
        }

    return _sql_retry(_run)


def assign_small_expenses(
    country: str,
    maximum: Decimal,
    category_id: int,
    *,
    center: str | None = None,
    person: str | None = None,
    account: str | None = None,
    whole_country: bool = False,
    income: bool = False,
) -> dict[str, Any]:
    """Set remainder bookings to ``category_id`` when the amount is below ``maximum``.

    An expense is a negative amount (``ABS(amount) < maximum``). An income is
    a positive amount (``amount < maximum``). Either write sets
    ``modification`` to 1. The remainder row is ``category_role = remainder``,
    not a fixed id.
    """
    from app import user_store
    from app.sql_replica import _transaction_table
    from shared.balance_values import require_remainder_row, spaar_source_exclude_clause

    name = (country or "").strip()
    table = _transaction_table(name)
    if not name or not table:
        raise ValueError(f"Unknown country {country!r}")
    cap = Decimal(str(maximum))
    if cap <= 0:
        raise ValueError("Maximum amount must be greater than zero")
    target = int(category_id)
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
        remainder_id, _remainder_code = require_remainder_row(country_id, cursor)
        if target == int(remainder_id):
            raise ValueError("Choose a category other than remainder")
        cursor.execute(
            """
            SELECT category_id FROM dbo.dim_category
            WHERE country_id = ? AND category_id = ?
            """,
            (country_id, target),
        )
        if cursor.fetchone() is None:
            raise ValueError(f"Unknown category {target}")
        where_sql, where_params, person_ids, _account_ids = _wipe_scope(
            cursor,
            country_id,
            center=None if whole_country else center,
            person=None if whole_country else person,
            account=None if whole_country else account,
            whole_country=whole_country,
        )
        joiner = " AND " if where_sql else " WHERE "
        if income:
            amount_sql = "AND amount > 0 AND amount < ?"
        else:
            amount_sql = "AND amount < 0 AND -amount < ?"
        cursor.execute(
            f"""
            UPDATE {table}
            SET category_id = ?, modification = 1
            {where_sql}{joiner}category_id = ?
              {amount_sql}
            """,
            (target, *where_params, int(remainder_id), cap),
        )
        updated = int(cursor.rowcount or 0)
        if updated and person_ids:
            _rebuild_category_totals(cursor, table, country_id, person_ids, spaar_source_exclude_clause)
        user_store._sql_connect().commit()
        return {"country": name, "updated": updated, "category_id": target}

    return _sql_retry(_run)


def _wipe_scope(
    cursor: Any,
    country_id: int,
    *,
    center: str | None,
    person: str | None,
    account: str | None,
    whole_country: bool,
) -> tuple[str, tuple[Any, ...], list[int], list[int]]:
    """``(where_sql, params, person_ids, account_ids)``. ``where_sql`` includes WHERE or is empty."""
    if whole_country:
        cursor.execute(
            """
            SELECT p.id
            FROM dbo.person p
            JOIN dbo.center n ON n.center_id = p.center_id
            WHERE n.country_id = ?
            """,
            (country_id,),
        )
        person_ids = [int(r[0]) for r in cursor.fetchall() if r[0] is not None]
        account_ids: list[int] = []
        if person_ids:
            cursor.execute(
                f"SELECT account_id FROM dbo.account WHERE person_id IN ({','.join('?' * len(person_ids))})",
                tuple(person_ids),
            )
            account_ids = [int(r[0]) for r in cursor.fetchall() if r[0] is not None]
        return "", (), person_ids, account_ids
    center_name = (center or "").strip() or None
    person_name = (person or "").strip() or None
    account_key = (account or "").strip() or None
    if account_key:
        iban = account_key.replace(" ", "").upper()
        cursor.execute(
            """
            SELECT a.account_id, a.person_id
            FROM dbo.account a
            JOIN dbo.person p ON p.id = a.person_id
            JOIN dbo.center n ON n.center_id = p.center_id
            WHERE n.country_id = ?
              AND REPLACE(UPPER(ISNULL(a.iban, N'')), N' ', N'') = ?
            """,
            (country_id, iban),
        )
        found = cursor.fetchall()
        if not found:
            raise ValueError(f"Unknown account {account_key!r}")
        account_ids = [int(r[0]) for r in found if r[0] is not None]
        person_ids = list({int(r[1]) for r in found if r[1] is not None})
        marks = ",".join("?" * len(account_ids))
        return f" WHERE account_id IN ({marks})", tuple(account_ids), person_ids, account_ids
    if person_name:
        cursor.execute(
            """
            SELECT p.id
            FROM dbo.person p
            JOIN dbo.center n ON n.center_id = p.center_id
            WHERE n.country_id = ?
              AND p.username = ? COLLATE Latin1_General_CI_AI
              AND (? IS NULL OR n.username = ? COLLATE Latin1_General_CI_AI)
            """,
            (country_id, person_name, center_name, center_name),
        )
        found = cursor.fetchall()
        if not found:
            raise ValueError(f"Unknown person {person_name!r}")
        person_ids = [int(r[0]) for r in found if r[0] is not None]
        cursor.execute(
            f"SELECT account_id FROM dbo.account WHERE person_id IN ({','.join('?' * len(person_ids))})",
            tuple(person_ids),
        )
        account_ids = [int(r[0]) for r in cursor.fetchall() if r[0] is not None]
        marks = ",".join("?" * len(person_ids))
        return f" WHERE person_id IN ({marks})", tuple(person_ids), person_ids, account_ids
    if center_name:
        cursor.execute(
            """
            SELECT p.id
            FROM dbo.person p
            JOIN dbo.center n ON n.center_id = p.center_id
            WHERE n.country_id = ? AND n.username = ? COLLATE Latin1_General_CI_AI
            """,
            (country_id, center_name),
        )
        person_ids = [int(r[0]) for r in cursor.fetchall() if r[0] is not None]
        account_ids = []
        if person_ids:
            cursor.execute(
                f"SELECT account_id FROM dbo.account WHERE person_id IN ({','.join('?' * len(person_ids))})",
                tuple(person_ids),
            )
            account_ids = [int(r[0]) for r in cursor.fetchall() if r[0] is not None]
            marks = ",".join("?" * len(person_ids))
            return f" WHERE person_id IN ({marks})", tuple(person_ids), person_ids, account_ids
        return " WHERE 1 = 0", (), [], []
    raise ValueError("Wipe scope is missing")


def _rebuild_category_totals(cursor: Any, table: str, country_id: int, person_ids: list[int], exclude_clause: Any) -> None:
    exclude_sql, exclude_params = exclude_clause(country_id, cursor=cursor)
    marks = ",".join("?" * len(person_ids))
    cursor.execute(
        f"SELECT DISTINCT person_id, year FROM {table} WHERE person_id IN ({marks})",
        tuple(person_ids),
    )
    pairs = [(int(p), int(y)) for p, y in cursor.fetchall() if p is not None and y is not None]
    cursor.execute(
        f"DELETE FROM dbo.category_total WHERE person_id IN ({marks}) AND bank_id IS NULL",
        tuple(person_ids),
    )
    for person_id, year in pairs:
        cursor.execute(
            f"""
            INSERT INTO dbo.category_total (person_id, year, bank_id, category_id, amount)
            SELECT t.person_id, ?, NULL, t.category_id, SUM(CAST(t.amount AS decimal(19,2)))
            FROM {table} t
            WHERE t.person_id = ? AND t.year = ?{exclude_sql}
            GROUP BY t.person_id, t.category_id
            """,
            (year, person_id, year, *exclude_params),
        )


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
        SELECT d.local_code, d.category_role
        FROM dbo.dim_category d
        JOIN dbo.country c ON c.country_id = d.country_id
        WHERE c.username = ? COLLATE Latin1_General_CI_AI
        ORDER BY d.local_code
        """,
        (name,),
    )
    from shared.balance_values import is_hit_forbidden_code

    return frozenset(
        int(row[0])
        for row in cursor.fetchall()
        if not is_hit_forbidden_code(int(row[0]), row[1])
    )


def categories_payload(country: str) -> dict[str, Any]:
    """``categories.json``-shaped dict from ``dim_category`` / terms / headers."""
    name = (country or "").strip()
    empty: dict[str, Any] = {
        "categories": {},
        "table_header_terms": {},
        "language_long": {},
        "category_roles": {},
    }
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
            SELECT country_id, language_id FROM dbo.country
            WHERE username = ? COLLATE Latin1_General_CI_AI
            """,
            (name,),
        )
        row = cursor.fetchone()
        if row is None:
            return empty
        country_id = int(row[0])
        language_id = row[1]

        categories: dict[str, list[str]] = {}
        category_roles: dict[str, str] = {}
        id_to_label: dict[int, str] = {}
        from shared.balance_values import (
            category_display_name,
            ensure_category_role_booking_rules,
        )

        ensure_category_role_booking_rules(cursor)
        cursor.execute(
            """
            SELECT category_id, local_code, label, category_role
            FROM dbo.dim_category
            WHERE country_id = ?
            ORDER BY local_code, label
            """,
            (country_id,),
        )
        for category_id, code, label, role in cursor.fetchall():
            cat_name = category_display_name(label, code, role)
            if not cat_name:
                continue
            categories[cat_name] = []
            id_to_label[int(category_id)] = cat_name
            role_text = str(role or "").strip()
            if role_text:
                category_roles[cat_name] = role_text

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

        headers = _language_header_terms(cursor, language_id)
        long_texts = _language_long_terms(cursor, language_id)

        return {
            "categories": categories,
            "table_header_terms": headers,
            "language_long": long_texts,
            "category_roles": category_roles,
        }

    payload = _sql_retry(_run)
    _CAT_CACHE[name] = (time.monotonic(), payload)
    return payload


def personal_categories_payload(username: str) -> dict[str, list[str]]:
    """Category name → personal keyword terms for one person.

    Keys use the same ``{local_code:04d} {label}`` naming as the general map
    (bare label only for footer roles ``balance`` / ``last_booked``).
    """
    name = (username or "").strip()
    if not name or not _sql_ready():
        return {}

    def _run() -> dict[str, list[str]]:
        cursor = _cursor()
        cursor.execute(
            """
            SELECT d.label, d.local_code, d.category_role, t.term
            FROM dbo.category_term t
            JOIN dbo.person p ON p.id = t.person_id
            JOIN dbo.dim_category d ON d.category_id = t.category_id
            WHERE p.username = ? COLLATE Latin1_General_CI_AI
            ORDER BY d.local_code, t.sort_order, t.term_id
            """,
            (name,),
        )
        from shared.balance_values import category_display_name

        out: dict[str, list[str]] = {}
        for label, code, role, term in cursor.fetchall():
            key = category_display_name(label, code, role)
            if not key:
                continue
            value = str(term or "").strip()
            if value:
                out.setdefault(key, []).append(value)
        return out

    try:
        return _sql_retry(_run)
    except Exception:  # noqa: BLE001
        return {}


def personal_category_maps(username: str) -> dict[str | None, dict[str, list[str]]]:
    """Personal keyword terms, keyed by account uid (``None`` = unbound).

    For person-modality countries a person's terms are unbound and collapse
    into the ``None`` map. For account-modality (balance) countries the same
    terms are scoped per account uid, and ``None`` holds any unbound leftovers.
    """
    name = (username or "").strip()
    if not name or not _sql_ready():
        return {}
    out: dict[str | None, dict[str, list[str]]] = {}

    def _run() -> dict[str, list[str]]:
        cursor = _cursor()
        cursor.execute(
            """
            SELECT d.label, d.local_code, d.category_role, t.term, t.term_id, a.uid
            FROM dbo.category_term t
            JOIN dbo.person p ON p.id = t.person_id
            JOIN dbo.dim_category d ON d.category_id = t.category_id
            LEFT JOIN dbo.account a ON a.account_id = t.account_id
            WHERE p.username = ? COLLATE Latin1_General_CI_AI
            ORDER BY d.local_code, t.sort_order, t.term_id
            """,
            (name,),
        )
        result: dict[str | None, dict[str, list[str]]] = {}
        from shared.balance_values import category_display_name

        for label, code, role, term, _term_id, uid in cursor.fetchall():
            key = category_display_name(label, code, role)
            if not key:
                continue
            value = str(term or "").strip()
            if not value:
                continue
            account_key = str(uid or "").strip() or None
            result.setdefault(account_key, {}).setdefault(key, []).append(value)
        return result

    try:
        grouped = _sql_retry(_run)
        for account_key, bucket in grouped.items():
            out[account_key] = bucket
        return out
    except Exception:  # noqa: BLE001
        return {}


def account_groups(country: str, username: str) -> list[dict[str, str]]:
    """Accounts of one person as client term-group entries (account modality)."""
    cname = (country or "").strip()
    name = (username or "").strip()
    if not cname or not name or not _sql_ready():
        return []

    def _run() -> list[dict[str, str]]:
        cursor = _cursor()
        cursor.execute(
            """
            SELECT a.uid, a.account_name, a.iban, n.username
            FROM dbo.account a
            JOIN dbo.person p ON p.id = a.person_id
            JOIN dbo.country c ON c.country_id = p.country_id
            JOIN dbo.center n ON n.center_id = p.center_id
            WHERE c.username = ? COLLATE Latin1_General_CI_AI
              AND p.username = ? COLLATE Latin1_General_CI_AI
            ORDER BY n.username, a.account_name, a.account_id
            """,
            (cname, name),
        )
        groups: list[dict[str, str]] = []
        for uid, account_name, iban, center_name in cursor.fetchall():
            key = str(uid or "").strip()
            if not key:
                continue
            groups.append(
                {
                    "account_key": key,
                    "account_name": str(account_name or "").strip(),
                    "iban": str(iban or "").strip(),
                    "center": str(center_name or "").strip(),
                }
            )
        return groups

    try:
        return _sql_retry(_run)
    except Exception:  # noqa: BLE001
        return []


def clear_catalog_cache() -> None:
    _CAT_CACHE.clear()


def term_change_table(cursor) -> bool:
    cursor.execute("SELECT OBJECT_ID(N'dbo.term_change', N'U')")
    row = cursor.fetchone()
    return bool(row and row[0])


def note_term_change(
    cursor,
    *,
    category_id: int,
    person_id: int | None,
    account_id: int | None,
    term: str,
    added: bool,
) -> None:
    """Record one net term edit. The opposite pending row cancels it."""
    if not term_change_table(cursor):
        return
    text = str(term or "").strip().lower()
    if not text:
        return
    cursor.execute(
        """
        DELETE FROM dbo.term_change
        WHERE category_id = ? AND term = ? AND added = ?
          AND ((? IS NULL AND person_id IS NULL) OR person_id = ?)
          AND ((? IS NULL AND account_id IS NULL) OR account_id = ?)
        """,
        (
            category_id,
            text,
            0 if added else 1,
            person_id,
            person_id,
            account_id,
            account_id,
        ),
    )
    if cursor.rowcount:
        return
    cursor.execute(
        """
        SELECT 1 FROM dbo.term_change
        WHERE category_id = ? AND term = ? AND added = ?
          AND ((? IS NULL AND person_id IS NULL) OR person_id = ?)
          AND ((? IS NULL AND account_id IS NULL) OR account_id = ?)
        """,
        (
            category_id,
            text,
            1 if added else 0,
            person_id,
            person_id,
            account_id,
            account_id,
        ),
    )
    if cursor.fetchone():
        return
    cursor.execute(
        """
        INSERT INTO dbo.term_change (category_id, person_id, account_id, term, added)
        VALUES (?, ?, ?, ?, ?)
        """,
        (category_id, person_id, account_id, text, 1 if added else 0),
    )


def load_term_changes(country: str) -> list[dict[str, Any]]:
    """Pending term edits for one country. Empty when the log table is absent."""
    name = (country or "").strip()
    if not name or not _sql_ready():
        return []

    def _run() -> list[dict[str, Any]]:
        cursor = _cursor()
        if not term_change_table(cursor):
            return []
        cursor.execute(
            """
            SELECT tc.term_change_id, tc.term, tc.added,
                   p.username, a.uid, n.username
            FROM dbo.term_change tc
            JOIN dbo.dim_category d ON d.category_id = tc.category_id
            JOIN dbo.country c ON c.country_id = d.country_id
            LEFT JOIN dbo.person p ON p.id = tc.person_id
            LEFT JOIN dbo.account a ON a.account_id = tc.account_id
            LEFT JOIN dbo.center n ON n.center_id = p.center_id
            WHERE c.username = ? COLLATE Latin1_General_CI_AI
            ORDER BY tc.term_change_id
            """,
            (name,),
        )
        out: list[dict[str, Any]] = []
        for change_id, term, added, person, uid, center in cursor.fetchall():
            out.append(
                {
                    "id": int(change_id),
                    "term": str(term or ""),
                    "added": bool(added),
                    "person": str(person or "").strip() or None,
                    "account": str(uid or "").strip() or None,
                    "center": str(center or "").strip() or None,
                }
            )
        return out

    try:
        return _sql_retry(_run)
    except Exception as exc:  # noqa: BLE001
        print(f"sql catalog: failed to load term changes: {exc}")
        return []


def term_change_count(country: str) -> int:
    """Pending term edits for one country. ``0`` when the log table is absent."""
    name = (country or "").strip()
    if not name or not _sql_ready():
        return 0

    def _run() -> int:
        cursor = _cursor()
        if not term_change_table(cursor):
            return 0
        cursor.execute(
            """
            SELECT COUNT(*)
            FROM dbo.term_change tc
            JOIN dbo.dim_category d ON d.category_id = tc.category_id
            JOIN dbo.country c ON c.country_id = d.country_id
            WHERE c.username = ? COLLATE Latin1_General_CI_AI
            """,
            (name,),
        )
        row = cursor.fetchone()
        return int(row[0]) if row and row[0] is not None else 0

    try:
        return _sql_retry(_run)
    except Exception as exc:  # noqa: BLE001
        print(f"sql catalog: failed to count term changes: {exc}")
        return 0


def clear_country_term_changes(country: str) -> None:
    """Drop every pending term edit for a country after a from-scratch rescore."""
    name = (country or "").strip()
    if not name or not _sql_ready():
        return

    def _run() -> None:
        from app import user_store

        conn = user_store._sql_connect()
        cursor = conn.cursor()
        if not term_change_table(cursor):
            return
        cursor.execute(
            """
            DELETE tc
            FROM dbo.term_change tc
            JOIN dbo.dim_category d ON d.category_id = tc.category_id
            JOIN dbo.country c ON c.country_id = d.country_id
            WHERE c.username = ? COLLATE Latin1_General_CI_AI
            """,
            (name,),
        )
        conn.commit()

    try:
        _sql_retry(_run)
    except Exception as exc:  # noqa: BLE001
        print(f"sql catalog: failed to clear term changes: {exc}")


def discard_term_changes(country: str) -> int:
    """Undo pending term edits and clear them. Returns the number of edits undone."""
    name = (country or "").strip()
    if not name or not _sql_ready():
        return 0

    def _run() -> int:
        from app import user_store

        conn = user_store._sql_connect()
        cursor = conn.cursor()
        was = conn.autocommit
        try:
            conn.autocommit = False
            if not term_change_table(cursor):
                return 0
            cursor.execute(
                """
                SELECT tc.term_change_id, tc.category_id, tc.person_id,
                       tc.account_id, tc.term, tc.added
                FROM dbo.term_change tc
                JOIN dbo.dim_category d ON d.category_id = tc.category_id
                JOIN dbo.country c ON c.country_id = d.country_id
                WHERE c.username = ? COLLATE Latin1_General_CI_AI
                ORDER BY tc.term_change_id DESC
                """,
                (name,),
            )
            rows = list(cursor.fetchall())
            for _change_id, category_id, person_id, account_id, term, added in rows:
                scope = (
                    int(category_id),
                    str(term or "").strip().lower(),
                    person_id,
                    person_id,
                    account_id,
                    account_id,
                )
                match = (
                    "category_id = ? AND term = ? "
                    "AND ((? IS NULL AND person_id IS NULL) OR person_id = ?) "
                    "AND ((? IS NULL AND account_id IS NULL) OR account_id = ?)"
                )
                if added:
                    cursor.execute(f"DELETE FROM dbo.category_term WHERE {match}", scope)
                    continue
                cursor.execute(f"SELECT 1 FROM dbo.category_term WHERE {match}", scope)
                if cursor.fetchone():
                    continue
                cursor.execute(
                    """
                    INSERT INTO dbo.category_term
                        (category_id, person_id, account_id, term, sort_order)
                    VALUES (?, ?, ?, ?, 0)
                    """,
                    (int(category_id), person_id, account_id, str(term or "").strip().lower()),
                )
            if rows:
                marks = ",".join("?" for _ in rows)
                cursor.execute(
                    f"DELETE FROM dbo.term_change WHERE term_change_id IN ({marks})",
                    [int(row[0]) for row in rows],
                )
            conn.commit()
            _CAT_CACHE.clear()
            return len(rows)
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

    return _sql_retry(_run)


def clear_term_changes(change_ids: list[int]) -> None:
    ids = [int(item) for item in change_ids]
    if not ids or not _sql_ready():
        return

    def _run() -> None:
        from app import user_store

        conn = user_store._sql_connect()
        cursor = conn.cursor()
        if not term_change_table(cursor):
            return
        marks = ",".join("?" for _ in ids)
        cursor.execute(f"DELETE FROM dbo.term_change WHERE term_change_id IN ({marks})", ids)
        conn.commit()

    _sql_retry(_run)


def clear_personal_term_changes(center: str, person: str | None = None) -> None:
    """Drop personal log rows for the people a from-scratch pass just scored."""
    ws = (center or "").strip()
    who = (person or "").strip()
    if not ws or not _sql_ready():
        return

    def _run() -> None:
        from app import user_store

        conn = user_store._sql_connect()
        cursor = conn.cursor()
        if not term_change_table(cursor):
            return
        if who:
            cursor.execute(
                """
                DELETE tc
                FROM dbo.term_change tc
                JOIN dbo.person p ON p.id = tc.person_id
                JOIN dbo.center n ON n.center_id = p.center_id
                WHERE n.username = ? COLLATE Latin1_General_CI_AI
                  AND p.username = ? COLLATE Latin1_General_CI_AI
                """,
                (ws, who),
            )
        else:
            cursor.execute(
                """
                DELETE tc
                FROM dbo.term_change tc
                JOIN dbo.person p ON p.id = tc.person_id
                JOIN dbo.center n ON n.center_id = p.center_id
                WHERE n.username = ? COLLATE Latin1_General_CI_AI
                """,
                (ws,),
            )
        conn.commit()

    try:
        _sql_retry(_run)
    except Exception as exc:  # noqa: BLE001
        print(f"sql catalog: failed to clear term changes: {exc}")


def save_category_terms(
    category_name: str,
    terms: list[str],
    *,
    person: str | None = None,
    account: str | None = None,
    country: str | None = None,
) -> None:
    """Replace general (person_id NULL) or personal keyword rows in ``dbo.category_term``.

    ``account`` (an account uid) scopes a personal bucket to one account
    (account-modality / balance countries); the scope lives in
    ``dbo.category_term.account_id``.
    """
    label = (category_name or "").strip()
    if not label or not _sql_ready():
        return
    cleaned = [str(item).strip().lower() for item in terms if str(item or "").strip()]
    person_name = (person or "").strip() or None
    account_key = (account or "").strip() or None
    resolved = (country or "").strip()
    if person_name and not resolved:
        layout = person_country_center(person_name)
        resolved = layout[0] if layout else ""
    if not resolved:
        from app.runtime import active_center, active_country

        resolved = (active_country() or country_for_center(active_center() or "") or "").strip()
    country = resolved
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
            account_id: int | None = None
            if person_name:
                cursor.execute(
                    "SELECT id FROM dbo.person WHERE username = ? COLLATE Latin1_General_CI_AI",
                    (person_name,),
                )
                prow = cursor.fetchone()
                if prow is None:
                    raise ValueError(f"Unknown person {person_name!r}")
                person_id = int(prow[0])
                if account_key:
                    cursor.execute(
                        "SELECT account_id FROM dbo.account WHERE person_id = ? AND uid = ?",
                        (person_id, account_key),
                    )
                    arow = cursor.fetchone()
                    if arow is None:
                        raise ValueError(f"Unknown account {account_key!r} for {person_name!r}")
                    account_id = int(arow[0])
            if person_id is None:
                scope_sql = "category_id = ? AND person_id IS NULL"
                scope_params: tuple[Any, ...] = (category_id,)
            elif account_id is not None:
                scope_sql = "category_id = ? AND person_id = ? AND account_id = ?"
                scope_params = (category_id, person_id, account_id)
            else:
                scope_sql = "category_id = ? AND person_id = ?"
                scope_params = (category_id, person_id)
            cursor.execute(
                f"SELECT account_id, term FROM dbo.category_term WHERE {scope_sql}",
                scope_params,
            )
            before = {
                (None if row_account is None else int(row_account), str(row_term or "").strip().lower())
                for row_account, row_term in cursor.fetchall()
                if str(row_term or "").strip()
            }
            if person_id is not None and account_id is None:
                after = {(None, term) for term in cleaned}
            else:
                after = {(account_id, term) for term in cleaned}
            for row_account, row_term in before - after:
                note_term_change(
                    cursor,
                    category_id=category_id,
                    person_id=person_id,
                    account_id=row_account,
                    term=row_term,
                    added=False,
                )
            for row_account, row_term in after - before:
                note_term_change(
                    cursor,
                    category_id=category_id,
                    person_id=person_id,
                    account_id=row_account,
                    term=row_term,
                    added=True,
                )
            cursor.execute(f"DELETE FROM dbo.category_term WHERE {scope_sql}", scope_params)
            if cleaned:
                try:
                    cursor.executemany(
                        """
                        INSERT INTO dbo.category_term (category_id, person_id, account_id, term, sort_order)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        [
                            (category_id, person_id, account_id, term, index)
                            for index, term in enumerate(cleaned)
                        ],
                    )
                except Exception as exc:
                    if _is_duplicate_key(exc):
                        detail = _duplicate_key_hint(exc)
                        raise ValueError(
                            f"Database unicity conflict: check if this term does not already exist"
                            + (f" ({detail})" if detail else "")
                        ) from exc
                    raise
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


def _lookup_category_term_bucket(
    cursor: Any,
    country: str,
    category_name: str,
    *,
    person: str | None,
    account: str | None,
) -> tuple[int, int | None, int | None, list[str]]:
    """Return category_id, person_id, account_id, and the current term list."""
    from shared.balance_values import is_remainder_role

    label = category_name.strip()
    try:
        code = int(label[:4])
    except ValueError:
        code = None
    cursor.execute(
        """
        SELECT d.category_id, d.category_role
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
    if is_remainder_role(row[1]):
        raise ValueError(f"Cannot add terms to category {label!r}")
    category_id = int(row[0])
    person_id: int | None = None
    account_id: int | None = None
    person_name = (person or "").strip() or None
    account_key = (account or "").strip() or None
    if person_name:
        cursor.execute(
            "SELECT id FROM dbo.person WHERE username = ? COLLATE Latin1_General_CI_AI",
            (person_name,),
        )
        prow = cursor.fetchone()
        if prow is None:
            raise ValueError(f"Unknown person {person_name!r}")
        person_id = int(prow[0])
        if account_key:
            cursor.execute(
                "SELECT account_id FROM dbo.account WHERE person_id = ? AND uid = ?",
                (person_id, account_key),
            )
            arow = cursor.fetchone()
            if arow is None:
                raise ValueError(f"Unknown account {account_key!r} for {person_name!r}")
            account_id = int(arow[0])
            cursor.execute(
                """
                SELECT term FROM dbo.category_term
                WHERE category_id = ? AND person_id = ? AND account_id = ?
                ORDER BY sort_order
                """,
                (category_id, person_id, account_id),
            )
        else:
            cursor.execute(
                """
                SELECT term FROM dbo.category_term
                WHERE category_id = ? AND person_id = ? AND account_id IS NULL
                ORDER BY sort_order
                """,
                (category_id, person_id),
            )
    else:
        cursor.execute(
            """
            SELECT term FROM dbo.category_term
            WHERE category_id = ? AND person_id IS NULL
            ORDER BY sort_order
            """,
            (category_id,),
        )
    terms = [str(item[0]) for item in cursor.fetchall() if str(item[0] or "").strip()]
    return category_id, person_id, account_id, terms


def append_category_term_sql(
    country: str,
    category_name: str,
    term: str,
    *,
    person: str | None = None,
    account: str | None = None,
) -> tuple[list[str], bool]:
    """Append one keyword and return ``(terms, added)``.

    Serialized so two rapid adds cannot each rewrite the list without the other.
    Does not use the process calc scope, so it can run while a rescore holds
    ``CALC_LOCK``.
    """
    cleaned = str(term or "").strip().lower()
    if not cleaned:
        raise ValueError("term must not be empty")
    name = (country or "").strip()
    if not name:
        raise ValueError(f"Cannot save terms for {category_name!r}: no country")

    def _run() -> tuple[list[str], bool]:
        from app import user_store

        conn = user_store._sql_connect()
        cursor = conn.cursor()
        _category_id, _person_id, _account_id, existing = _lookup_category_term_bucket(
            cursor,
            name,
            category_name,
            person=person,
            account=account,
        )
        lowered = [item.strip().lower() for item in existing]
        if cleaned in lowered:
            return existing, False
        updated = [*existing, cleaned]
        return updated, True

    with _term_write_lock:
        updated, added = _sql_retry(_run)
        if added:
            save_category_terms(
                category_name,
                updated,
                person=person,
                account=account,
                country=name,
            )
        return updated, added


def account_belongs_to_person(center: str, person: str, account_uid: str) -> bool:
    """True when ``account_uid`` is an account of ``person`` in ``center``."""
    ws = (center or "").strip()
    who = (person or "").strip()
    uid = (account_uid or "").strip()
    if not ws or not who or not uid or not _sql_ready():
        return False

    def _run() -> bool:
        cursor = _cursor()
        cursor.execute(
            """
            SELECT 1
            FROM dbo.account a
            JOIN dbo.person p ON p.id = a.person_id
            JOIN dbo.center n ON n.center_id = p.center_id
            WHERE n.username = ? COLLATE Latin1_General_CI_AI
              AND p.username = ? COLLATE Latin1_General_CI_AI
              AND a.uid = ?
            """,
            (ws, who, uid),
        )
        return cursor.fetchone() is not None

    try:
        return bool(_sql_retry(_run))
    except Exception:  # noqa: BLE001
        return False


def apply_center_account_term_delta(
    center: str,
    category_name: str,
    *,
    add: list[str] | None = None,
    remove: list[str] | None = None,
    person: str | None = None,
) -> dict[str, Any]:
    """Add/remove keywords on every account in a center (optionally one person).

    Each removed term is deleted once per ``dbo.account`` row. Each added
    term is inserted once per account that does not already have it.
    """
    label = (category_name or "").strip()
    ws = (center or "").strip()
    person_name = (person or "").strip() or None
    added = [str(item).strip().lower() for item in (add or []) if str(item or "").strip()]
    removed = [str(item).strip().lower() for item in (remove or []) if str(item or "").strip()]
    if not label or not ws:
        raise ValueError("center and category are required")
    if not _sql_ready():
        raise ValueError("center-account terms require the database")
    try:
        code = int(label[:4])
    except ValueError:
        code = None

    def _run() -> dict[str, Any]:
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
                JOIN dbo.center n ON n.country_id = c.country_id
                WHERE n.username = ? COLLATE Latin1_General_CI_AI
                  AND (d.label = ? OR d.local_code = ?)
                """,
                (ws, label, code),
            )
            row = cursor.fetchone()
            if row is None:
                raise ValueError(f"Unknown category {label!r} for center {ws!r}")
            category_id = int(row[0])
            if person_name:
                cursor.execute(
                    """
                    SELECT a.account_id, p.id
                    FROM dbo.account a
                    JOIN dbo.person p ON p.id = a.person_id
                    JOIN dbo.center n ON n.center_id = p.center_id
                    WHERE n.username = ? COLLATE Latin1_General_CI_AI
                      AND p.username = ? COLLATE Latin1_General_CI_AI
                    ORDER BY a.account_id
                    """,
                    (ws, person_name),
                )
            else:
                cursor.execute(
                    """
                    SELECT a.account_id, p.id
                    FROM dbo.account a
                    JOIN dbo.person p ON p.id = a.person_id
                    JOIN dbo.center n ON n.center_id = p.center_id
                    WHERE n.username = ? COLLATE Latin1_General_CI_AI
                    ORDER BY a.account_id
                    """,
                    (ws,),
                )
            accounts = [
                (int(account_id), int(person_id))
                for account_id, person_id in cursor.fetchall()
                if account_id is not None and person_id is not None
            ]
            person_ids = {person_id for _, person_id in accounts}
            for person_id in person_ids:
                for term in removed:
                    cursor.execute(
                        """
                        DELETE FROM dbo.category_term
                        WHERE category_id = ? AND person_id = ?
                          AND account_id IS NULL AND term = ?
                        """,
                        (category_id, person_id, term),
                    )
                    if cursor.rowcount:
                        note_term_change(
                            cursor,
                            category_id=category_id,
                            person_id=person_id,
                            account_id=None,
                            term=term,
                            added=False,
                        )
            for account_id, person_id in accounts:
                for term in removed:
                    cursor.execute(
                        """
                        DELETE FROM dbo.category_term
                        WHERE category_id = ? AND person_id = ?
                          AND account_id = ? AND term = ?
                        """,
                        (category_id, person_id, account_id, term),
                    )
                    if cursor.rowcount:
                        note_term_change(
                            cursor,
                            category_id=category_id,
                            person_id=person_id,
                            account_id=account_id,
                            term=term,
                            added=False,
                        )
                for term in added:
                    cursor.execute(
                        """
                        SELECT 1 FROM dbo.category_term
                        WHERE category_id = ? AND person_id = ?
                          AND account_id = ? AND term = ?
                        """,
                        (category_id, person_id, account_id, term),
                    )
                    if cursor.fetchone() is None:
                        cursor.execute(
                            """
                            INSERT INTO dbo.category_term
                                (category_id, person_id, account_id, term, sort_order)
                            VALUES (?, ?, ?, ?, 0)
                            """,
                            (category_id, person_id, account_id, term),
                        )
                        note_term_change(
                            cursor,
                            category_id=category_id,
                            person_id=person_id,
                            account_id=account_id,
                            term=term,
                            added=True,
                        )
            conn.commit()
            _CAT_CACHE.clear()
            return {
                "accounts": len(accounts),
                "added": added,
                "removed": removed,
            }
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

    return _sql_retry(_run)


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


def _is_duplicate_key(exc: Exception) -> bool:
    """True when ``exc`` is a SQL unique-name/index violation (duplicate key)."""
    try:
        sqlstate = str((exc.args[0] or "") if exc.args else "")
    except Exception:  # noqa: BLE001
        sqlstate = ""
    if sqlstate.startswith(("23000", "2601", "2627")):
        return True
    import re as _re

    text = str(exc)
    return bool(
        _re.search(r"(duplicate key|unique index|unique constraint|violation of UNIQUE)", text, _re.I)
    )


def _duplicate_key_hint(exc: Exception) -> str:
    """Short human-readable hint: the offending index name, when visible."""
    import re as _re

    match = _re.search(r"unique index ['\"]([^'\"]+)['\"]", str(exc), _re.I)
    return match.group(1) if match else ""


def country_has_balance(country: str) -> bool:
    """True when the country uses per-account personal-term modality."""
    name = (country or "").strip()
    if not name or not _sql_ready():
        return False

    def _run() -> bool:
        cursor = _cursor()
        cursor.execute(
            "SELECT has_balance FROM dbo.country WHERE username = ? COLLATE Latin1_General_CI_AI",
            (name,),
        )
        row = cursor.fetchone()
        return bool(row and int(row[0] or 0))

    try:
        return _sql_retry(_run)
    except Exception:  # noqa: BLE001
        return False


def _pnl_per_account(
    cursor,
    country_id: int,
    year: int,
    table: str,
    *,
    month_count: int | None = None,
    scope_sql: str = "",
    scope_params: tuple[Any, ...] = (),
) -> tuple[list[dict[str, Any]], dict[int, dict[int, Any]]]:
    """Bank accounts with a booking in ``year`` and P&L sums per account.

    Returns ``(accounts, sums)``: ``accounts`` are the accounts in scope
    (``account_id``, ``account_name``, ``iban``, ``person``) ordered by
    person then name; ``sums[category_id][account_id]`` is the year sum of
    3000-4999 bookings (all bank_id copies, spaar source rows excluded — the
    same bookings as ``dbo.category_total``). ``month_count`` limits both to
    January..that month; ``None`` takes the whole year. ``scope_sql`` may
    narrow on aliases ``p`` (person) / ``n`` (center) and must start with
    ``AND``.
    """
    from decimal import Decimal

    from shared.balance_values import spaar_source_exclude_clause

    exclude_sql, exclude_params = spaar_source_exclude_clause(
        int(country_id), cursor=cursor
    )
    month_sql = ""
    month_params: list[Any] = []
    if month_count is not None:
        month_sql = " AND t.booked_on IS NOT NULL AND MONTH(t.booked_on) BETWEEN 1 AND ?"
        month_params = [int(month_count)]

    accounts: list[dict[str, Any]] = []
    cursor.execute(
        f"""
        SELECT a.account_id, a.account_name, a.iban, p.username
        FROM dbo.account a
        JOIN dbo.person p ON p.id = a.person_id
        JOIN dbo.center n ON n.center_id = p.center_id
        WHERE n.country_id = ?
          {scope_sql}
          AND EXISTS (
            SELECT 1 FROM {table} t
            WHERE t.account_id = a.account_id
              AND t.year = ?
              {month_sql}
              {exclude_sql}
          )
        ORDER BY p.username, a.account_name, a.account_id
        """,
        (int(country_id), *scope_params, int(year), *month_params, *exclude_params),
    )
    for account_id, account_name, iban, username in cursor.fetchall():
        accounts.append(
            {
                "account_id": int(account_id),
                "account_name": str(account_name or "").strip(),
                "iban": str(iban or "").strip() or None,
                "person": str(username or "").strip() or None,
            }
        )

    sums: dict[int, dict[int, Any]] = {}
    cursor.execute(
        f"""
        SELECT t.category_id, t.account_id,
               SUM(CAST(t.amount AS decimal(19, 2)))
        FROM {table} t
        JOIN dbo.person p ON p.id = t.person_id
        JOIN dbo.center n ON n.center_id = p.center_id
        JOIN dbo.dim_category d
          ON d.category_id = t.category_id
         AND d.country_id = n.country_id
        WHERE n.country_id = ?
          AND t.year = ?
          AND d.local_code BETWEEN 3000 AND 4999
          {month_sql}
          {exclude_sql}
          {scope_sql}
        GROUP BY t.category_id, t.account_id
        """,
        (int(country_id), int(year), *month_params, *exclude_params, *scope_params),
    )
    for category_id, account_id, amount in cursor.fetchall():
        if account_id is None:
            continue
        by_acc = sums.setdefault(int(category_id), {})
        by_acc[int(account_id)] = by_acc.get(int(account_id), Decimal("0")) + Decimal(
            str(amount or 0)
        )
    return accounts, sums


def export_resultaat_excel_data(
    country: str,
    year: int,
    *,
    person: str | None = None,
    center: str | None = None,
) -> dict[str, Any]:
    """P&L (3000–4999) plus Saldo, scoped to the login.

    Person: that person's bookings, same set as ``dbo.category_total``.
    Center: every person in that center.
    Country (neither person nor center): the whole country, plus journal/mirror
    overlay so Saldo matches the balance-sheet Resultaat sheet.

    ``category_role`` can hold a login username. If that username appears on
    any P&L row, only those tagged rows plus ``remainder`` are listed; otherwise every P&L
    category is listed. That same case also sends monthly meal counts from
    ``dbo.maaltijden_aantallen`` (ontbijt / koud / warm / warm_hd) for the Excel
    footer; equivalent tafelgenoten and food cost per tafelgenoot are
    calculated in the client. Month columns run from January through the
    current month of this year (all twelve when the export year is already
    over). Cumulatief is their sum. Totaal is the sum of the displayed P&L
    rows. Incoming on category 1053 is used only in the cash-flow block at
    the end: Stichting de Oude Gracht (signed amounts to/from IBAN
    NL94INGB0006200605), Overige inkomsten, Uitgaven, their Resultaat, then
    Banksaldo einde maand.
    """
    name = (country or "").strip()
    person_name = (person or "").strip()
    center_name = "" if person_name else (center or "").strip()
    if not name or not _sql_ready():
        raise ValueError("country is required")

    def _run() -> dict[str, Any]:
        import calendar as _calendar
        import datetime
        from decimal import Decimal

        from shared.balance_values import (
            account_links,
            category_local_codes,
            is_hit_forbidden_role,
            is_remainder_role,
            is_resultaat,
            journal_deltas,
            spaar_source_exclude_clause,
            transaction_table,
        )

        cursor = _cursor()
        country_id = _country_id_for(cursor, name)
        if country_id is None:
            raise ValueError(f"unknown country: {name}")
        today = datetime.date.today()
        y = int(year)
        if y < today.year:
            month_count = 12
        elif y > today.year:
            month_count = 0
        else:
            month_count = int(today.month)
        person_id: int | None = None
        if person_name:
            cursor.execute(
                """
                SELECT p.id
                FROM dbo.person p
                JOIN dbo.center n ON n.center_id = p.center_id
                WHERE n.country_id = ?
                  AND p.username = ? COLLATE Latin1_General_CI_AI
                """,
                (int(country_id), person_name),
            )
            prow = cursor.fetchone()
            if prow is None:
                raise ValueError(f"unknown person: {person_name}")
            person_id = int(prow[0])
        elif center_name:
            cursor.execute(
                """
                SELECT center_id
                FROM dbo.center
                WHERE country_id = ?
                  AND username = ? COLLATE Latin1_General_CI_AI
                """,
                (int(country_id), center_name),
            )
            if cursor.fetchone() is None:
                raise ValueError(f"unknown center: {center_name}")

        monthly: dict[int, list[Decimal]] = {}

        def _add_month(cid: int, month: int, value: Decimal) -> None:
            m = int(month)
            if m < 1 or m > month_count:
                return
            row = monthly.setdefault(int(cid), [Decimal("0")] * 12)
            row[m - 1] += value

        # Login scope shared by every booking query below (``p`` = dbo.person,
        # ``n`` = dbo.center aliases).
        scope_sql = ""
        scope_params: list[Any] = []
        if person_id is not None:
            scope_sql = " AND p.id = ?"
            scope_params = [person_id]
        elif center_name:
            scope_sql = " AND n.username = ? COLLATE Latin1_General_CI_AI"
            scope_params = [center_name]

        table = transaction_table(int(country_id), cursor)
        if table and month_count > 0:
            cursor.execute(f"SELECT OBJECT_ID(N'{table}', N'U')")
            if cursor.fetchone()[0] is not None:
                exclude_sql, exclude_params = spaar_source_exclude_clause(
                    int(country_id), cursor=cursor
                )
                # Same bookings as dbo.category_total (all bank_id copies, spaar
                # source rows excluded), split by MONTH(booked_on).
                sql = f"""
                    SELECT t.category_id, MONTH(t.booked_on),
                           SUM(CAST(t.amount AS decimal(19, 2)))
                    FROM {table} t
                    JOIN dbo.person p ON p.id = t.person_id
                    JOIN dbo.center n ON n.center_id = p.center_id
                    JOIN dbo.dim_category d
                      ON d.category_id = t.category_id
                     AND d.country_id = n.country_id
                    WHERE n.country_id = ?
                      AND t.year = ?
                      AND d.local_code BETWEEN 3000 AND 4999
                      AND t.booked_on IS NOT NULL
                      AND MONTH(t.booked_on) BETWEEN 1 AND ?
                      {exclude_sql}
                      {scope_sql}
                    GROUP BY t.category_id, MONTH(t.booked_on)
                """
                params: list[Any] = [
                    int(country_id),
                    int(year),
                    month_count,
                    *exclude_params,
                    *scope_params,
                ]
                cursor.execute(sql, tuple(params))
                for category_id, month, amount in cursor.fetchall():
                    _add_month(
                        int(category_id),
                        int(month),
                        Decimal(str(amount or 0)),
                    )

        if not person_name and not center_name:
            codes = category_local_codes(country_id, cursor)
            cursor.execute("SELECT OBJECT_ID(N'dbo.journal', N'U')")
            if cursor.fetchone()[0] is not None:
                cursor.execute(
                    """
                    SELECT j.category_from, j.category_to, j.amount, MONTH(j.date)
                    FROM dbo.journal j
                    JOIN dbo.dim_category d ON d.category_id = j.category_from
                    WHERE d.country_id = ? AND j.year = ?
                      AND MONTH(j.date) BETWEEN 1 AND ?
                    """,
                    (int(country_id), int(year), month_count),
                )
                for cat_from, cat_to, amount, month in cursor.fetchall():
                    try:
                        src, dst, m = int(cat_from), int(cat_to), int(month)
                    except (TypeError, ValueError):
                        continue
                    src_delta, dst_delta = journal_deltas(
                        codes.get(src, src),
                        codes.get(dst, dst),
                        Decimal(str(amount or 0)),
                    )
                    if is_resultaat(codes.get(src, src)):
                        _add_month(src, m, src_delta)
                    if is_resultaat(codes.get(dst, dst)):
                        _add_month(dst, m, dst_delta)
            cursor.execute("SELECT OBJECT_ID(N'dbo.transaction_mirror', N'U')")
            if cursor.fetchone()[0] is not None:
                cursor.execute(
                    """
                    SELECT category_id, amount, MONTH(date)
                    FROM dbo.transaction_mirror
                    WHERE country_id = ? AND year = ?
                      AND MONTH(date) BETWEEN 1 AND ?
                    """,
                    (int(country_id), int(year), month_count),
                )
                for category_id, amount, month in cursor.fetchall():
                    try:
                        cid, m = int(category_id), int(month)
                    except (TypeError, ValueError):
                        continue
                    if not is_resultaat(codes.get(cid, cid)):
                        continue
                    _add_month(cid, m, Decimal(str(amount or 0)))

        cursor.execute(
            """
            SELECT category_id, local_code, label, category_role
            FROM dbo.dim_category
            WHERE country_id = ?
              AND local_code BETWEEN 3000 AND 4999
            ORDER BY local_code, label
            """,
            (int(country_id),),
        )
        dim_rows = cursor.fetchall()
        login = (person_name or center_name or name).strip()
        login_l = login.lower()
        role_listed = False
        if login_l:
            for _cid, _code, _label, role in dim_rows:
                if str(role or "").strip().lower() == login_l:
                    role_listed = True
                    break
        rows: list[dict[str, Any]] = []
        total_months = [Decimal("0")] * 12
        total = Decimal("0")
        for category_id, local_code, label, role in dim_rows:
            if is_hit_forbidden_role(role):
                continue
            role_text = str(role or "").strip()
            if role_listed and role_text.lower() != login_l and not is_remainder_role(role):
                continue
            cid = int(category_id)
            months = list(monthly.get(cid, [Decimal("0")] * 12))[:month_count]
            amount = sum(months, Decimal("0"))
            total += amount
            for i, part in enumerate(months):
                total_months[i] += part
            rows.append(
                {
                    "code": int(local_code),
                    "label": str(label or "").strip() or f"cat_{local_code}",
                    "months": [float(part) for part in months],
                    "amount": float(amount),
                }
            )
        maaltijden: dict[str, list[float]] | None = None
        if role_listed and login:
            cursor.execute("SELECT OBJECT_ID(N'dbo.maaltijden_aantallen', N'U')")
            if cursor.fetchone()[0] is not None:
                ont = [0.0] * month_count
                koud = [0.0] * month_count
                warm = [0.0] * month_count
                warm_hd = [0.0] * month_count
                if month_count > 0:
                    cursor.execute(
                        """
                        SELECT maand, ontbijt, koud, warm, warm_hd
                        FROM dbo.maaltijden_aantallen
                        WHERE username = ? COLLATE Latin1_General_CI_AI
                          AND jaar = ?
                          AND maand BETWEEN 1 AND ?
                        """,
                        (login, int(year), month_count),
                    )
                    for month, o, k, w, wh in cursor.fetchall():
                        m = int(month)
                        if 1 <= m <= month_count:
                            ont[m - 1] = float(o or 0)
                            koud[m - 1] = float(k or 0)
                            warm[m - 1] = float(w or 0)
                            warm_hd[m - 1] = float(wh or 0)
                maaltijden = {
                    "ontbijten": ont,
                    "koude": koud,
                    "warme": warm,
                    "warm_hd": warm_hd,
                }
        incoming_1053_months = [0.0] * month_count
        incoming_1053_label = "Ontvangsten"
        q_months = [0.0] * month_count
        r_months = [0.0] * month_count
        s_months = [0.0] * month_count
        banksaldo_months = [0.0] * month_count
        stichting_iban = "NL94INGB0006200605"
        account_id_1053: int | None = None
        links = account_links(int(country_id), cursor)
        cursor.execute(
            """
            SELECT TOP 1 d.category_id
            FROM dbo.dim_category d
            WHERE d.country_id = ? AND d.local_code = 1053
            """,
            (int(country_id),),
        )
        cat_1053 = cursor.fetchone()
        if cat_1053 is not None:
            account_id_1053 = links.get(int(cat_1053[0]))
        if account_id_1053 is None:
            account_id_1053 = links.get(1053)
        table_ok = False
        if table:
            cursor.execute(f"SELECT OBJECT_ID(N'{table}', N'U')")
            table_ok = cursor.fetchone()[0] is not None
        if table_ok and account_id_1053 is not None and month_count > 0:
            cursor.execute(
                f"""
                SELECT MONTH(t.booked_on),
                       SUM(CAST(t.amount AS decimal(19, 2)))
                FROM {table} t
                WHERE t.year = ?
                  AND t.account_id = ?
                  AND t.amount > 0
                  AND t.booked_on IS NOT NULL
                  AND MONTH(t.booked_on) BETWEEN 1 AND ?
                GROUP BY MONTH(t.booked_on)
                """,
                (int(year), int(account_id_1053), month_count),
            )
            for month, amount in cursor.fetchall():
                m = int(month)
                if 1 <= m <= month_count:
                    incoming_1053_months[m - 1] = float(amount or 0)
            iban_sql = (
                "REPLACE(REPLACE(UPPER(ISNULL(t.counterparty_iban, N'')), "
                "N' ', N''), N'-', N'')"
            )
            cursor.execute(
                f"""
                SELECT MONTH(t.booked_on),
                       SUM(CASE WHEN {iban_sql} = ?
                                THEN CAST(t.amount AS decimal(19, 2))
                                ELSE 0 END),
                       SUM(CASE WHEN {iban_sql} <> ?
                                 AND t.amount > 0
                                THEN CAST(t.amount AS decimal(19, 2))
                                ELSE 0 END),
                       SUM(CASE WHEN {iban_sql} <> ?
                                 AND t.amount < 0
                                THEN CAST(t.amount AS decimal(19, 2))
                                ELSE 0 END)
                FROM {table} t
                WHERE t.year = ?
                  AND t.account_id = ?
                  AND t.booked_on IS NOT NULL
                  AND MONTH(t.booked_on) BETWEEN 1 AND ?
                GROUP BY MONTH(t.booked_on)
                """,
                (
                    stichting_iban,
                    stichting_iban,
                    stichting_iban,
                    int(year),
                    int(account_id_1053),
                    month_count,
                ),
            )
            for month, q_amt, r_amt, s_amt in cursor.fetchall():
                m = int(month)
                if 1 <= m <= month_count:
                    q_months[m - 1] = float(q_amt or 0)
                    r_months[m - 1] = float(r_amt or 0)
                    s_months[m - 1] = float(s_amt or 0)
            cursor.execute(
                "SELECT balance FROM dbo.account WHERE account_id = ?",
                (int(account_id_1053),),
            )
            bal_row = cursor.fetchone()
            live = float(bal_row[0] or 0) if bal_row else 0.0

            def _as_date(value: object) -> datetime.date:
                if isinstance(value, datetime.datetime):
                    return value.date()
                if isinstance(value, datetime.date):
                    return value
                return datetime.date.fromisoformat(str(value)[:10])

            cutoffs: list[datetime.date] = []
            for month in range(1, month_count + 1):
                last_day = _calendar.monthrange(int(year), month)[1]
                cutoff = datetime.date(int(year), month, last_day)
                if int(year) == today.year and month == today.month:
                    cutoff = today
                cutoffs.append(cutoff)
            later_by_date: list[tuple[datetime.date, float]] = []
            earliest = min(cutoffs)
            cursor.execute(
                f"""
                SELECT t.booked_on,
                       SUM(CAST(t.amount AS decimal(19, 2)))
                FROM {table} t
                WHERE t.account_id = ?
                  AND t.booked_on > ?
                GROUP BY t.booked_on
                """,
                (int(account_id_1053), earliest.isoformat()),
            )
            for booked_on, amount in cursor.fetchall():
                if booked_on is None:
                    continue
                later_by_date.append((_as_date(booked_on), float(amount or 0)))
            for i, cutoff in enumerate(cutoffs):
                later = sum(
                    amt for booked, amt in later_by_date if booked > cutoff
                )
                banksaldo_months[i] = live - later
        resultaat_months = [
            q_months[i] + r_months[i] + s_months[i] for i in range(month_count)
        ]

        def _line(code: object, label: str, months: list[float]) -> dict[str, Any]:
            return {
                "code": code,
                "label": label,
                "months": list(months),
                "amount": float(sum(months)),
            }

        return {
            "year": int(year),
            "country": name,
            "person": person_name or None,
            "center": center_name or None,
            "month_count": month_count,
            "incoming_1053": {
                "code": 1053,
                "label": incoming_1053_label,
                "months": incoming_1053_months,
                "amount": float(sum(incoming_1053_months)),
            },
            "resultaat": rows,
            "total_months": [float(part) for part in total_months[:month_count]],
            "total_resultaat": float(total),
            "maaltijden": maaltijden,
            "cashflow_1053": {
                "stichting": _line(
                    "", "Stichting de Oude Gracht", q_months
                ),
                "inkomsten": _line("", "Overige inkomsten", r_months),
                "uitgaven": _line("", "Uitgaven", s_months),
                "resultaat": _line("", "Resultaat", resultaat_months),
                "banksaldo": {
                    "code": "",
                    "label": "Banksaldo einde maand",
                    "months": banksaldo_months,
                    "amount": float(banksaldo_months[-1] if banksaldo_months else 0),
                },
            },
        }

    try:
        return _sql_retry(_run)
    except ValueError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ValueError(str(exc)) from exc


def export_matrix_excel_data(country: str, year: int) -> dict[str, Any]:
    """One JSON payload for the client's "Export balance sheet" workbook.

    Balance countries (``dbo.country.has_balance``) get ``activa``/``passiva``
    exactly like the balance app's sheet (including the computed Verlies and
    Eigen vermogen posts) plus ``balance_tree``: the posts that carry a
    ``dim_category.parent`` (``Activa/Vlottende activa/Kas``) nested by that
    path, each group with its total; posts without ``parent`` are omitted from
    the tree. Every country gets per-category ``resultaat`` rows (3000-4999)
    and, when any P&L row has a ``parent``, ``result_tree`` built the same
    way from those rows. Each P&L row (and tree group) carries ``columns``:
    its year sum per bank account (``result_accounts`` order), then per spaar
    ``mirror`` post (``result_mirrors``: the P&L leg of journals against that
    post), then one Journaal value holding the rest of the overlay, so the
    columns always sum to ``amount``.
    ``code`` is always the ``local_code``, never the ``category_id``.
    The Resultaat rows come from the recorded ``dbo.category_total`` plus the
    beheer journal/mirror overlay (R). Passiva 2100 Verlies uses that same R.
    """
    name = (country or "").strip()
    if not name or not _sql_ready():
        raise ValueError("country is required")

    def _run() -> dict[str, Any]:
        from decimal import Decimal

        from shared.balance_values import (
            balance_category_breakdown,
            build_parent_tree,
            category_labels,
            category_local_codes,
            category_map,
            category_parents,
            country_has_balance,
            eigen_vermogen_id,
            is_resultaat,
            journal_deltas,
            recorded_resultaat_totals,
            result_overlay_cents,
            spaar_mirrors,
            transaction_table,
            verlies_id,
        )

        cursor = _cursor()
        country_id = _country_id_for(cursor, name)
        if country_id is None:
            raise ValueError(f"unknown country: {name}")
        has_balance = country_has_balance(country_id, cursor)

        recorded = recorded_resultaat_totals(country_id, int(year), cursor)
        overlay = result_overlay_cents(country_id, int(year), cursor)
        labels = category_labels(country_id, cursor)
        local_codes = category_local_codes(country_id, cursor)
        parents = category_parents(country_id, cursor)

        def _local(cat_id: int) -> int:
            return int(local_codes.get(int(cat_id), int(cat_id)))

        # Resultaat drill-down: one column per bank account with a booking
        # this year; each P&L row carries its per-account year sums.
        result_accounts: list[dict[str, Any]] = []
        pnl_sums: dict[int, dict[int, Any]] = {}
        table = transaction_table(country_id, cursor)
        if table:
            cursor.execute(f"SELECT OBJECT_ID(N'{table}', N'U')")
            if cursor.fetchone()[0] is not None:
                result_accounts, pnl_sums = _pnl_per_account(
                    cursor, int(country_id), int(year), table
                )
        account_ids = [int(a["account_id"]) for a in result_accounts]

        # Spaarrekening (mirror) columns: the P&L leg of every journal whose
        # other side is that mirror post (interest and the like). The
        # remaining overlay — journals without a bank side, mirror rows on a
        # P&L category — lands in the trailing Journaal column below.
        mirror_ids = sorted(
            {int(pair["target_category"]) for pair in spaar_mirrors(country_id, cursor)},
            key=_local,
        )
        mirror_parts: dict[int, dict[int, Decimal]] = {}
        cursor.execute("SELECT OBJECT_ID(N'dbo.journal', N'U')")
        journal_exists = cursor.fetchone()[0] is not None
        if mirror_ids and journal_exists:
            cursor.execute(
                "SELECT j.category_from, j.category_to, j.amount FROM dbo.journal j "
                "JOIN dbo.dim_category d ON d.category_id = j.category_from "
                "WHERE d.country_id = ? AND j.year = ?",
                (int(country_id), int(year)),
            )
            for cat_from, cat_to, amount in cursor.fetchall():
                try:
                    src, dst = int(cat_from), int(cat_to)
                except (TypeError, ValueError):
                    continue
                src_delta, dst_delta = journal_deltas(
                    _local(src), _local(dst), Decimal(str(amount or 0))
                )
                if is_resultaat(_local(src)) and dst in mirror_ids:
                    by = mirror_parts.setdefault(src, {})
                    by[dst] = by.get(dst, Decimal("0")) + src_delta
                if is_resultaat(_local(dst)) and src in mirror_ids:
                    by = mirror_parts.setdefault(dst, {})
                    by[src] = by.get(src, Decimal("0")) + dst_delta
        result_mirrors = [
            {"code": _local(m), "label": labels.get(m, f"cat_{m}")} for m in mirror_ids
        ]

        combined: dict[int, Decimal] = {}
        for code, amount in recorded.items():
            combined[code] = combined.get(code, Decimal("0")) + amount
        for code, cents in overlay.items():
            combined[code] = combined.get(code, Decimal("0")) + Decimal(cents) / Decimal(100)

        def _result_columns(cat_id: int) -> list[float]:
            acc = [pnl_sums.get(cat_id, {}).get(aid, Decimal("0")) for aid in account_ids]
            mir = [mirror_parts.get(cat_id, {}).get(m, Decimal("0")) for m in mirror_ids]
            journal = combined[cat_id] - sum(acc, Decimal("0")) - sum(mir, Decimal("0"))
            return [float(v) for v in (*acc, *mir, journal)]

        result_rows = [
            {
                "code": _local(code),
                "label": labels.get(code, f"cat_{code}"),
                "amount": float(combined[code]),
                "columns": _result_columns(code),
            }
            for code in sorted(combined, key=_local)
        ]
        total_result = float(sum(combined.values()))
        # Tree sheets list only posts that have a ``parent``; the Resultaat
        # sheet stays a flat list when no P&L row has one.
        parented_result = [row for row in result_rows if int(row["code"]) in parents]
        result_tree = (
            build_parent_tree(parented_result, parents, "Resultaat")
            if parented_result
            else None
        )

        if not has_balance:
            return {
                "year": int(year),
                "has_balance": False,
                "activa": [],
                "passiva": [],
                "total_activa": 0.0,
                "total_passiva": 0.0,
                "balance_tree": [],
                "resultaat": result_rows,
                "result_accounts": result_accounts,
                "result_mirrors": result_mirrors,
                "total_resultaat": total_result,
                "result_tree": result_tree,
            }

        result_id = verlies_id(country_id, cursor)
        balance_id = eigen_vermogen_id(country_id, cursor)
        breakdown = balance_category_breakdown(country_id, int(year), cursor)
        cmap = category_map(country_id, cursor)

        activa: list[dict[str, Any]] = []
        passiva: list[dict[str, Any]] = []
        skip_ids = {i for i in (balance_id, result_id) if i is not None}
        for cat_id in sorted(cmap, key=_local):
            if cat_id in skip_ids:
                continue
            side, _account_id = cmap[cat_id]
            cents, _source = breakdown.get(cat_id, (0, "opening"))
            row = {
                "code": _local(cat_id),
                "label": labels.get(cat_id, f"cat_{cat_id}"),
                "amount": float(Decimal(cents) / Decimal(100)),
            }
            (passiva if side == "passiva" else activa).append(row)

        total_activa = sum(Decimal(str(row["amount"])) for row in activa) or Decimal("0")
        if result_id is not None:
            passiva.append(
                {
                    "code": _local(result_id),
                    "label": labels.get(result_id, "Verlies"),
                    "amount": float(total_result),
                    "source": "category_total",
                }
            )
        total_passiva_others = sum(Decimal(str(row["amount"])) for row in passiva) or Decimal("0")
        if balance_id is not None:
            passiva.append(
                {
                    "code": _local(balance_id),
                    "label": labels.get(balance_id, "Eigen vermogen"),
                    "amount": float(total_activa - total_passiva_others),
                    "source": "computed",
                }
            )
        total_passiva = total_activa  # Verlies + Eigen vermogen close the sheet
        # One tree over both sides, restricted to posts that have a ``parent``
        # (its first segment names the side).
        balance_tree = build_parent_tree(
            [row for row in activa + passiva if int(row["code"]) in parents],
            parents,
            "Activa",
        )
        return {
            "year": int(year),
            "has_balance": True,
            "activa": activa,
            "passiva": passiva,
            "total_activa": float(total_activa),
            "total_passiva": float(total_passiva),
            "balance_tree": balance_tree,
            "resultaat": result_rows,
            "result_accounts": result_accounts,
            "result_mirrors": result_mirrors,
            "total_resultaat": total_result,
            "result_tree": result_tree,
        }

    try:
        return _sql_retry(_run)
    except ValueError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ValueError(str(exc)) from exc


def display_digits(rows: list[dict[str, Any]]) -> int:
    """Frontend code-padding width for a country's local codes.

    Uniform backend storage is four digits; only ``beheer_sdog`` actually uses
    codes >= 100. This lets the frontend pad to 2 for everyone else.
    """
    codes = [int(row.get("local_code") or 0) for row in rows]
    return 4 if any(code >= 100 for code in codes) else 2


def booking_categories_payload(country: str) -> dict[str, Any]:
    """Booking rows in ``dbo.dim_category`` (excludes footers and role stamps)."""
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
            SELECT category_id, local_code, label, category_role
            FROM dbo.dim_category
            WHERE country_id = ?
            ORDER BY local_code, label
            """,
            (country_id,),
        )
        rows: list[dict[str, Any]] = []
        remainder_id: int | None = None
        from shared.balance_values import is_hit_forbidden_role, is_remainder_role

        for category_id, local_code, label, role in cursor.fetchall():
            if is_hit_forbidden_role(role):
                continue
            cid = int(category_id)
            remainder = is_remainder_role(role)
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
                SELECT category_id, local_code, label, category_role
                FROM dbo.dim_category
                WHERE country_id = ?
                """,
                (country_id,),
            )
            existing: dict[int, dict[str, Any]] = {}
            protected_ids: set[int] = set()
            protected_codes: set[int] = set()
            from shared.balance_values import is_hit_forbidden_role, is_remainder_role

            for category_id, local_code, label, role in cursor.fetchall():
                cid = int(category_id)
                if is_hit_forbidden_role(role):
                    protected_ids.add(cid)
                    protected_codes.add(int(local_code))
                    continue
                existing[cid] = {
                    "local_code": int(local_code),
                    "label": str(label or "").strip(),
                    "is_remainder": is_remainder_role(role),
                }
            cursor.execute("SELECT category_id FROM dbo.dim_category")
            taken_ids = {int(row[0]) for row in cursor.fetchall()}
            used_ids = set(existing) | protected_ids
            lo, hi = _alloc_category_id_bounds(cursor, table, country_id, used_ids)
            allocated: list[dict[str, Any]] = []
            for item in parsed:
                cid = item["category_id"]
                if cid is None:
                    raise ValueError("Each category needs a numeric id")
                code = int(item["local_code"])
                if cid in protected_ids or (
                    cid not in existing and cid in taken_ids
                ):
                    raise ValueError(f"Category id {cid} is already in use")
                if code in protected_codes:
                    raise ValueError(
                        f"Category code {code:04d} is already in use"
                    )
                if cid in existing:
                    item = {**item, "is_new": False}
                else:
                    if cid < lo or cid > hi:
                        raise ValueError(
                            f"Category id {cid} is outside the allowed range {lo}–{hi}"
                        )
                    taken_ids.add(cid)
                    item = {**item, "is_new": True}
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
                old_code = int(existing[cid]["local_code"])
                new_code = int(item["local_code"])
                if old_code != new_code:
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
                else:
                    cursor.execute(
                        """
                        UPDATE dbo.dim_category
                        SET label = ?
                        WHERE category_id = ?
                        """,
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
                    SET local_code = ?, label = ?, category_role = ?
                    WHERE category_id = ?
                    """,
                    int(item["local_code"]),
                    str(item["label"]),
                    "remainder" if item["is_remainder"] else None,
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
    ids: set[int] = set()
    remainders = 0
    for raw in items:
        if not isinstance(raw, dict):
            raise ValueError("Each category must be an object")
        cid_raw = raw.get("category_id")
        try:
            cid = int(cid_raw)
        except (TypeError, ValueError) as exc:
            raise ValueError("Each category needs a numeric id") from exc
        if cid_raw in (None, "", 0) or cid < 1:
            raise ValueError("Each category needs a numeric id")
        try:
            code = int(raw.get("local_code"))
        except (TypeError, ValueError) as exc:
            raise ValueError("Each category needs a numeric code") from exc
        if code < 1 or code > max_code or code in (98, 99):
            raise ValueError(f"Category code must be 1–{max_code} (98/99 are system), not {code}")
        label = str(raw.get("label") or "").strip()
        if not label:
            raise ValueError("Each category needs a label")
        if cid in ids:
            raise ValueError(f"Category id {cid} is already in use")
        if code in codes:
            raise ValueError(f"Category code {code:0{width}d} is already in use")
        codes.add(code)
        ids.add(cid)
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
            (category_id, country_id, local_code, label, category_role)
        VALUES (?, ?, ?, ?, ?)
        """,
        int(item["category_id"]),
        country_id,
        int(item["local_code"]),
        str(item["label"]),
        "remainder" if item["is_remainder"] else None,
    )


def _delete_dim_categories(cursor, deleted_ids: list[int]) -> None:
    placeholders, values = _sql_in(deleted_ids)
    cursor.execute(
        f"DELETE FROM dbo.dim_category WHERE category_id IN ({placeholders})",
        values,
    )

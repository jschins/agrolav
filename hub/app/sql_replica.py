"""SQL Server bookings for the person/year(/bank) bound in ``app.runtime``.

Reads return JSON-shaped rows. Writes INSERT/UPDATE ``transaction_*`` rows.
JSON files remain a write-through cache for imports and file publish.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from app.yearpath import is_year_name

_IDENT = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
_ENABLE_BANKING_ID = re.compile(r"^(\d+)_(\d+)$")
_DATE_DMY = re.compile(r"^(\d{2})-(\d{2})-(\d{4})$")
_SPLIT_CHILD = re.compile(r"^(.*)~s(\d+)$")
_MONEY = Decimal("0.01")


def _sql_ident(name: str) -> str | None:
    text = str(name or "").strip()
    return text if _IDENT.fullmatch(text) else None


def _transaction_table(country_name: str) -> str | None:
    from app.runtime import country_folder

    folder = country_folder(country_name) or country_name
    if folder in ("uk", "united_kingdom"):
        return "dbo.transaction_uk"
    ident = _sql_ident(folder)
    if not ident:
        return None
    return f"dbo.transaction_{ident}"


def _layout(data_dir: Path) -> tuple[str, str, int, str | None] | None:
    """country folder, person username, year, bank folder or None."""
    if is_year_name(data_dir.name):
        year_dir = data_dir
        bank_folder = None
    elif is_year_name(data_dir.parent.name):
        year_dir = data_dir.parent
        bank_folder = data_dir.name
    else:
        return None
    person_dir = year_dir.parent
    center_dir = person_dir.parent
    country_dir = center_dir.parent
    return country_dir.name, person_dir.name, int(year_dir.name), bank_folder


def _local_code(raw: Any) -> int | None:
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _json_amount(value: Any) -> str:
    try:
        amount = Decimal(str(value))
    except Exception:
        return "0.00"
    return f"{amount:.2f}"


def _json_date(value: Any) -> str:
    if value is None:
        return ""
    if hasattr(value, "day") and hasattr(value, "month") and hasattr(value, "year"):
        return f"{int(value.day):02d}-{int(value.month):02d}-{int(value.year):04d}"
    text = str(value).strip()
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        return f"{text[8:10]}-{text[5:7]}-{text[0:4]}"
    return text


def _json_text(value: Any) -> str:
    return "" if value is None else str(value)


def _decimal_amount(value: Any) -> Decimal | None:
    text = str(value or "").strip().replace(",", ".")
    if not text:
        return None
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return None


def _booked_on(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    match = _DATE_DMY.fullmatch(text)
    if match:
        return date(int(match.group(3)), int(match.group(2)), int(match.group(1)))
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        try:
            return date.fromisoformat(text[:10])
        except ValueError:
            return None
    return None


@dataclass
class _BoundScope:
    table: str
    username: str
    person_id: int
    year: int
    bank_key: int | None
    account_id: int | None
    cursor: Any
    conn: Any


def _account_id_for_folder(cursor, person_id: int, folder: str) -> int | None:
    compact = folder.replace(" ", "")
    cursor.execute(
        "SELECT account_id, iban FROM dbo.account WHERE person_id = ?",
        (person_id,),
    )
    rows = [(int(account_id), str(iban or "").replace(" ", "")) for account_id, iban in cursor.fetchall()]
    for account_id, ib in rows:
        if ib and ib == compact:
            return account_id
    for account_id, ib in rows:
        if ib and ib in compact:
            return account_id
    return None


def _bound_where(bound: _BoundScope, alias: str = "t") -> tuple[str, list[Any]]:
    """Person/year, plus bank vs consolidated.

    Bookings exist as a ``bank_id IS NULL`` (consolidated) copy and optional
    per-bank copies with the same ``source_id``. A view must not return both.
    """
    sql = f"{alias}.person_id = ? AND {alias}.year = ?"
    params: list[Any] = [bound.person_id, bound.year]
    if bound.account_id is not None:
        sql += f" AND {alias}.account_id = ?"
        params.append(bound.account_id)
        if bound.bank_key is not None:
            sql += f" AND {alias}.bank_id = ?"
            params.append(bound.bank_key)
        else:
            # Enable Banking / IBAN switcher: bookings are consolidated (bank_id NULL).
            sql += f" AND {alias}.bank_id IS NULL"
        return sql, params
    if bound.bank_key is not None:
        sql += f" AND {alias}.bank_id = ?"
        params.append(bound.bank_key)
        return sql, params
    sql += f" AND {alias}.bank_id IS NULL"
    return sql, params


def _open_bound_scope() -> _BoundScope | None:
    """Resolve the bound person/year(/bank) against SQL, or None if SQL is unused."""
    from app import runtime as paths, user_store

    if not user_store.database_url():
        return None
    country_name = str(paths.BOUND_COUNTRY or "").strip()
    username = str(paths.BOUND_PERSON or "").strip()
    year = paths.BOUND_YEAR
    bank_folder = paths.BOUND_BANK
    if not (country_name and username and year is not None):
        layout = _layout(paths.DATA_DIR)
        if layout is None:
            return None
        country_name, username, year, bank_folder = layout
    table = _transaction_table(country_name)
    if table is None:
        return None

    user_store.init_user_store()
    conn = user_store._sql_connect()
    cursor = conn.cursor()
    cursor.execute(f"SELECT OBJECT_ID(N'{table}', N'U')")
    if cursor.fetchone()[0] is None:
        return None
    cursor.execute(
        """
        SELECT id FROM dbo.person
        WHERE username = ? COLLATE Latin1_General_CI_AI
        """,
        (username,),
    )
    row = cursor.fetchone()
    if row is None:
        print(f"sql replica: no person {username!r}")
        return None
    person_id = int(row[0])

    bank_id: int | None = None
    account_id: int | None = None
    if bank_folder:
        account_id = _account_id_for_folder(cursor, person_id, bank_folder)
        if account_id is None:
            try:
                from app.core.bank_csv import format_for_bank

                fmt = format_for_bank(bank_folder)
                cursor.execute(
                    "SELECT bank_id FROM dbo.bank WHERE file_format = ?",
                    (fmt,),
                )
                bank_row = cursor.fetchone()
                if bank_row is None:
                    print(f"sql replica: no bank for folder {bank_folder!r} format {fmt!r}")
                    return None
                bank_id = int(bank_row[0])
            except ValueError:
                print(f"sql replica: no account for folder {bank_folder!r}")
                return None

    return _BoundScope(
        table=table,
        username=username,
        person_id=person_id,
        year=int(year),
        bank_key=bank_id,
        account_id=account_id,
        cursor=cursor,
        conn=conn,
    )


def load_bound_transactions(*, category_code: int | None = None) -> list[dict[str, Any]] | None:
    """JSON-shaped bookings from SQL, or ``None`` to keep using JSON files.

    When SQL is configured and the booking table exists, this returns a list
    (possibly empty) and callers must not fall back to categorized JSON.
    ``category_code`` limits rows to that ``dim_category.local_code``.
    """
    from app import user_store

    if not user_store.database_url():
        return None
    try:
        bound = _open_bound_scope()
        if bound is None:
            return None
        where_sql, where_params = _bound_where(bound)
        params: list[Any] = list(where_params)
        extra = ""
        if category_code is not None:
            extra = " AND COALESCE(d.local_code, 18) = ?"
            params.append(int(category_code))
        bound.cursor.execute(
            f"""
            SELECT
                t.source_id,
                t.amount,
                t.bank_type,
                t.counterparty_name,
                t.counterparty_iban,
                t.description,
                t.booked_on,
                t.modification,
                t.hit,
                d.local_code,
                c.currency_default
            FROM {bound.table} t
            JOIN dbo.person p ON p.id = t.person_id
            JOIN dbo.country c ON c.country_id = p.country_id
            LEFT JOIN dbo.dim_category d ON d.category_id = t.category_id
            WHERE {where_sql}{extra}
            ORDER BY t.booked_on DESC, t.source_id DESC
            """,
            tuple(params),
        )
        fetched = bound.cursor.fetchall()
    except Exception as exc:  # noqa: BLE001
        print(f"sql replica: failed to load bookings: {exc}")
        return []
    rows: list[dict[str, Any]] = []
    for item in fetched:
        (
            source_id,
            amount,
            bank_type,
            name,
            iban,
            description,
            booked_on,
            modification,
            hit,
            local_code,
            currency,
        ) = item
        try:
            flag = int(modification)
        except (TypeError, ValueError):
            flag = -1
        rows.append(
            {
                "id": str(source_id),
                "amount": _json_amount(amount),
                "currency": _json_text(currency) or "EUR",
                "type": _json_text(bank_type),
                "name": _json_text(name),
                "iban": _json_text(iban),
                "description": _json_text(description),
                "date": _json_date(booked_on),
                "category": int(local_code) if local_code is not None else 18,
                "modification": flag,
                "hit": None if hit in (None, "") else str(hit),
            }
        )
    return rows


def load_bound_category_totals(general_names: list[str]) -> dict[str, str] | None:
    """Per-category sums in SQL. ``None`` if SQL is unused for this bind."""
    from app import user_store
    from app.core.categorize import _amount_str, _category_code

    if not user_store.database_url():
        return None
    try:
        bound = _open_bound_scope()
        if bound is None:
            return None
        where_sql, where_params = _bound_where(bound)
        bound.cursor.execute(
            f"""
            SELECT COALESCE(d.local_code, 18), SUM(t.amount)
            FROM {bound.table} t
            LEFT JOIN dbo.dim_category d ON d.category_id = t.category_id
            WHERE {where_sql}
            GROUP BY COALESCE(d.local_code, 18)
            """,
            tuple(where_params),
        )
        by_code: dict[int, int] = {}
        for local_code, amount in bound.cursor.fetchall():
            try:
                code = int(local_code)
            except (TypeError, ValueError):
                code = 18
            try:
                cents = round(float(amount or 0) * 100)
            except (TypeError, ValueError):
                cents = 0
            by_code[code] = cents
    except Exception as exc:  # noqa: BLE001
        print(f"sql replica: failed to load category totals: {exc}")
        return {}
    name_by_code = {
        code: name for name in general_names if (code := _category_code(name)) is not None
    }
    booking_names = [name for name in general_names if _category_code(name) is not None]
    totals: dict[str, int] = {name: 0 for name in booking_names}
    for code, cents in by_code.items():
        name = name_by_code.get(code, str(code))
        totals[name] = totals.get(name, 0) + cents
    return {name: _amount_str(cents) for name, cents in totals.items()}


def load_bound_last_booked() -> str | None:
    """Latest booking date as ``DD-MM-YYYY``, or ``None`` if SQL is unused."""
    from app import user_store

    if not user_store.database_url():
        return None
    try:
        bound = _open_bound_scope()
        if bound is None:
            return None
        where_sql, where_params = _bound_where(bound)
        bound.cursor.execute(
            f"SELECT MAX(t.booked_on) FROM {bound.table} t WHERE {where_sql}",
            tuple(where_params),
        )
        row = bound.cursor.fetchone()
    except Exception as exc:  # noqa: BLE001
        print(f"sql replica: failed to load last booked date: {exc}")
        return None
    if not row or row[0] is None:
        return None
    text = _json_date(row[0])
    return text or None


def load_center_year_matrix(
    *,
    center: str,
    country: str,
    year: int,
    general_names: list[str],
) -> tuple[dict[str, dict[str, str]], dict[str, str], dict[str, str]] | None:
    """Totals, last booked date, and IBAN balances for every person in a center/year.

    One connection, three grouped queries. Does not download booking rows.
    """
    from app import user_store
    from app.core.categorize import _amount_str, _category_code

    if not user_store.database_url():
        return None
    table = _transaction_table(country)
    if not table:
        return None
    ws = (center or "").strip()
    try:
        user_store.init_user_store()
        cursor = user_store._sql_connect().cursor()
        cursor.execute(f"SELECT OBJECT_ID(N'{table}', N'U')")
        if cursor.fetchone()[0] is None:
            return None
        cursor.execute(
            f"""
            SELECT p.username, COALESCE(d.local_code, 18), SUM(t.amount)
            FROM {table} t
            JOIN dbo.person p ON p.id = t.person_id
            JOIN dbo.center n ON n.center_id = p.center_id
            LEFT JOIN dbo.dim_category d ON d.category_id = t.category_id
            WHERE n.username = ? COLLATE Latin1_General_CI_AI AND t.year = ?
              AND t.bank_id IS NULL
            GROUP BY p.username, COALESCE(d.local_code, 18)
            """,
            (ws, int(year)),
        )
        name_by_code = {
            code: name for name in general_names if (code := _category_code(name)) is not None
        }
        booking_names = [name for name in general_names if _category_code(name) is not None]
        totals_cents: dict[str, dict[str, int]] = {}
        for username, local_code, amount in cursor.fetchall():
            person = str(username or "").strip()
            if not person:
                continue
            try:
                code = int(local_code)
            except (TypeError, ValueError):
                code = 18
            try:
                cents = round(float(amount or 0) * 100)
            except (TypeError, ValueError):
                cents = 0
            bucket = totals_cents.setdefault(person, {name: 0 for name in booking_names})
            label = name_by_code.get(code, str(code))
            bucket[label] = bucket.get(label, 0) + cents
        totals = {
            person: {name: _amount_str(cents) for name, cents in amounts.items()}
            for person, amounts in totals_cents.items()
        }

        cursor.execute(
            f"""
            SELECT p.username, MAX(t.booked_on)
            FROM {table} t
            JOIN dbo.person p ON p.id = t.person_id
            JOIN dbo.center n ON n.center_id = p.center_id
            WHERE n.username = ? COLLATE Latin1_General_CI_AI AND t.year = ?
              AND t.bank_id IS NULL
            GROUP BY p.username
            """,
            (ws, int(year)),
        )
        last_booked = {
            str(username or "").strip(): _json_date(booked)
            for username, booked in cursor.fetchall()
            if str(username or "").strip() and booked is not None
        }

        cursor.execute(
            """
            SELECT p.username, a.balance
            FROM dbo.account a
            JOIN dbo.person p ON p.id = a.person_id
            JOIN dbo.center n ON n.center_id = p.center_id
            WHERE n.username = ? COLLATE Latin1_General_CI_AI
            ORDER BY a.account_id
            """,
            (ws,),
        )
        balance_cents: dict[str, int] = {}
        found: set[str] = set()
        for username, balance in cursor.fetchall():
            person = str(username or "").strip()
            if not person:
                continue
            text = str(balance or "").strip()
            if not text:
                continue
            try:
                balance_cents[person] = balance_cents.get(person, 0) + round(float(text) * 100)
            except ValueError:
                continue
            found.add(person)
        balances = {
            person: f"{cents / 100:.2f}" for person, cents in balance_cents.items() if person in found
        }
    except Exception as exc:  # noqa: BLE001
        print(f"sql replica: failed to load center matrix: {exc}")
        return None
    return totals, last_booked, balances


def _executemany_commit(conn, cursor, sql: str, params: list[tuple[Any, ...]]) -> None:
    """Write rows without fast_executemany (breaks NVARCHAR(MAX) on Driver 18)."""
    was = conn.autocommit
    try:
        conn.autocommit = False
        cursor.fast_executemany = False
        cursor.executemany(sql, params)
        conn.commit()
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


def sync_bound_transactions(records: list[dict[str, Any]]) -> None:
    """UPDATE ``transaction_*`` for the person/year(/bank) bound in ``app.runtime``."""
    from app import user_store
    from app.core.categorize import DEFAULT_CATEGORY

    if not user_store.database_url():
        return
    try:
        bound = _open_bound_scope()
        if bound is None:
            return
        bound.cursor.execute(
            """
            SELECT d.local_code, d.category_id, d.is_remainder
            FROM dbo.dim_category d
            JOIN dbo.country c ON c.country_id = d.country_id
            JOIN dbo.person u ON u.country_id = c.country_id
            WHERE u.id = ?
            """,
            bound.person_id,
        )
        by_code: dict[int, int] = {}
        remainder_id: int | None = None
        for local_code, category_id, is_remainder in bound.cursor.fetchall():
            by_code[int(local_code)] = int(category_id)
            if int(is_remainder):
                remainder_id = int(category_id)
        remainder_id = remainder_id or by_code.get(DEFAULT_CATEGORY)
        if remainder_id is None:
            print(f"sql replica: no remainder category for {bound.username!r}")
            return

        extra = ""
        if bound.account_id is not None:
            extra = " AND ((account_id = ? AND bank_id IS NOT NULL) OR bank_id IS NULL)"
        elif bound.bank_key is not None:
            extra = " AND (bank_id = ? OR bank_id IS NULL)"
        sql = f"""
            UPDATE {bound.table}
            SET category_id = ?, modification = ?, hit = ?, description = ?
            WHERE person_id = ? AND year = ? AND source_id = ?
            {extra}
            """
        params: list[tuple[Any, ...]] = []
        for item in records:
            if not isinstance(item, dict):
                continue
            source_id = str(item.get("id") or "").strip()
            if not source_id:
                continue
            code = _local_code(item.get("category"))
            category_id = by_code.get(code, remainder_id) if code is not None else remainder_id
            try:
                modification = int(item.get("modification"))
            except (TypeError, ValueError):
                modification = 0
            hit = item.get("hit")
            hit_s = str(hit)[:64] if hit not in (None, "") else None
            description = item.get("description")
            desc_s = None if description is None else str(description)
            row = (
                    category_id,
                    modification,
                    hit_s,
                    desc_s,
                    bound.person_id,
                    bound.year,
                    source_id,
                )
            if bound.account_id is not None:
                row = (*row, bound.account_id)
            elif bound.bank_key is not None:
                row = (*row, bound.bank_key)
            params.append(row)
        if not params:
            return
        _executemany_commit(bound.conn, bound.cursor, sql, params)
    except Exception as exc:  # noqa: BLE001
        print(f"sql replica: failed to update bookings: {exc}")
        raise


def _remainder_id(cursor, person_id: int) -> int | None:
    from app.core.categorize import DEFAULT_CATEGORY

    cursor.execute(
        """
        SELECT d.local_code, d.category_id, d.is_remainder
        FROM dbo.dim_category d
        JOIN dbo.country c ON c.country_id = d.country_id
        JOIN dbo.person u ON u.country_id = c.country_id
        WHERE u.id = ?
        """,
        person_id,
    )
    by_code: dict[int, int] = {}
    remainder_id: int | None = None
    for local_code, category_id, is_remainder in cursor.fetchall():
        by_code[int(local_code)] = int(category_id)
        if int(is_remainder):
            remainder_id = int(category_id)
    return remainder_id or by_code.get(DEFAULT_CATEGORY)


def _refresh_account_count(cursor, person_id: int) -> int:
    cursor.execute(
        "SELECT COUNT(*) FROM dbo.account WHERE person_id = ?",
        person_id,
    )
    count = int(cursor.fetchone()[0])
    cursor.execute(
        "UPDATE dbo.person SET number_of_accounts = ? WHERE id = ?",
        count,
        person_id,
    )
    return count


def ensure_bound_accounts(
    accounts: list[dict[str, Any]],
    *,
    default_format: str | None = None,
) -> list[dict[str, Any]]:
    """Insert missing ``dbo.account`` rows for the bound person; set ``number_of_accounts``."""
    from app import user_store

    if not user_store.database_url() or not accounts:
        return []
    try:
        bound = _open_bound_scope()
        if bound is None:
            return []
        out: list[dict[str, Any]] = []
        for item in accounts:
            if not isinstance(item, dict):
                continue
            iban = str(item.get("iban") or "").strip()[:64]
            name = str(item.get("account_name") or item.get("name") or iban or "account").strip()[:64]
            if not iban:
                iban = (name or "unknown")[:64]
            if not iban:
                continue
            fmt = str(item.get("format") or default_format or "").strip() or None
            uid = str(item.get("uid") or "").strip()[:128] or None
            ident_hash = str(item.get("identification_hash") or "").strip()[:128] or None
            balance = _decimal_amount(item.get("balance")) or Decimal("0")
            bound.cursor.execute(
                """
                SELECT account_id FROM dbo.account
                WHERE person_id = ? AND iban = ?
                """,
                bound.person_id,
                iban,
            )
            row = bound.cursor.fetchone()
            if row is None:
                bound.cursor.execute(
                    """
                    INSERT INTO dbo.account (person_id, iban, account_name, format, balance)
                    OUTPUT INSERTED.account_id
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    bound.person_id,
                    iban,
                    name or iban,
                    fmt,
                    balance,
                )
                account_id = int(bound.cursor.fetchone()[0])
            else:
                account_id = int(row[0])
                bound.cursor.execute(
                    """
                    UPDATE dbo.account
                    SET
                        account_name = ?,
                        format = COALESCE(?, format),
                        balance = ?,
                        uid = CASE
                            WHEN connection_id IS NOT NULL THEN COALESCE(?, uid)
                            ELSE uid
                        END,
                        identification_hash = CASE
                            WHEN connection_id IS NOT NULL THEN COALESCE(?, identification_hash)
                            ELSE identification_hash
                        END
                    WHERE account_id = ?
                    """,
                    name or iban,
                    fmt,
                    balance,
                    uid,
                    ident_hash,
                    account_id,
                )
            out.append({"account_id": account_id, "iban": iban, "account_name": name or iban})
        _refresh_account_count(bound.cursor, bound.person_id)
        bound.conn.commit()
        return out
    except Exception as exc:  # noqa: BLE001
        print(f"sql replica: failed to ensure accounts: {exc}")
        return []


def _resolve_account_id(
    cursor,
    *,
    person_id: int,
    source_id: str,
    account_id: int | None,
) -> int | None:
    if account_id is not None:
        return account_id
    cursor.execute(
        """
        SELECT account_id FROM dbo.account
        WHERE person_id = ?
        ORDER BY account_id
        """,
        person_id,
    )
    ids = [int(row[0]) for row in cursor.fetchall()]
    if not ids:
        return None
    if len(ids) == 1:
        return ids[0]
    match = _ENABLE_BANKING_ID.fullmatch(source_id)
    if match:
        index = int(match.group(2))
        if 0 <= index < len(ids):
            return ids[index]
    return ids[0]


def ingest_bound_transactions(
    records: list[dict[str, Any]],
    *,
    account_id: int | None = None,
) -> int:
    """INSERT bookings that are not yet in SQL as remainder / modification -1 / hit NULL."""
    from app import user_store

    if not user_store.database_url() or not records:
        return 0
    try:
        bound = _open_bound_scope()
        if bound is None:
            return 0
        remainder_id = _remainder_id(bound.cursor, bound.person_id)
        if remainder_id is None:
            print(f"sql replica: no remainder category for {bound.username!r}")
            return 0
        bank_id = bound.bank_key if (bound.bank_key or 0) >= 0 else None
        where_sql, where_params = _bound_where(bound)
        where_sql = where_sql.replace("t.", "")
        bound.cursor.execute(
            f"SELECT source_id FROM {bound.table} WHERE {where_sql}",
            *where_params,
        )
        existing = {str(row[0]) for row in bound.cursor.fetchall()}
        sql = f"""
            INSERT INTO {bound.table} (
                person_id, account_id, year, bank_id, source_id, amount,
                bank_type, counterparty_name, counterparty_iban, description,
                booked_on, category_id, modification, hit
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """
        params: list[tuple[Any, ...]] = []
        for item in records:
            if not isinstance(item, dict):
                continue
            source_id = str(item.get("id") or "").strip()
            if not source_id or source_id in existing:
                continue
            amount = _decimal_amount(item.get("amount"))
            booked = _booked_on(item.get("date"))
            if amount is None or booked is None:
                continue
            acc_id = account_id or bound.account_id or _resolve_account_id(
                bound.cursor,
                person_id=bound.person_id,
                source_id=source_id,
                account_id=None,
            )
            if acc_id is None:
                print(f"sql replica: no account for {bound.username!r} id={source_id}")
                continue
            iban = str(item.get("iban") or "").strip()[:64] or None
            params.append(
                (
                    bound.person_id,
                    acc_id,
                    bound.year,
                    bank_id,
                    source_id,
                    amount,
                    str(item.get("type") or "")[:64] or None,
                    str(item.get("name") or "")[:512] or None,
                    iban,
                    str(item.get("description") or "") or None,
                    booked,
                    remainder_id,
                    -1,
                    None,
                )
            )
            existing.add(source_id)
        if not params:
            return 0
        bound.cursor.fast_executemany = True
        bound.cursor.executemany(sql, params)
        bound.cursor.fast_executemany = False
        bound.conn.commit()
        return len(params)
    except Exception as exc:  # noqa: BLE001
        print(f"sql replica: failed to insert bookings: {exc}")
        return 0


def _money(value: Any) -> Decimal:
    amount = _decimal_amount(value)
    if amount is None:
        return Decimal("0.00")
    return amount.quantize(_MONEY)


def _root_source_id(source_id: str) -> str:
    match = _SPLIT_CHILD.fullmatch(str(source_id or "").strip())
    return match.group(1) if match else str(source_id or "").strip()


def _has_parent_source_column(cursor, table: str) -> bool:
    cursor.execute(f"SELECT COL_LENGTH(N'{table}', N'parent_source_id')")
    row = cursor.fetchone()
    return bool(row and row[0])


def _next_split_ids(parent_id: str, used: set[int], count: int) -> list[str]:
    n = 1
    out: list[str] = []
    while len(out) < count:
        if n not in used:
            child = f"{parent_id}~s{n}"
            if len(child) > 128:
                raise ValueError("Transaction id is too long to split")
            used.add(n)
            out.append(child)
        n += 1
    return out


def _split_payload(
    *,
    parent_id: str,
    parent: dict[str, Any],
    children: list[dict[str, Any]],
) -> dict[str, Any]:
    total = _money(parent.get("amount"))
    for child in children:
        total += _money(child.get("amount"))
    return {
        "id": parent_id,
        "original_amount": _json_amount(total),
        "description": str(parent.get("description") or ""),
        "date": str(parent.get("date") or ""),
        "name": str(parent.get("name") or ""),
        "iban": str(parent.get("iban") or ""),
        "type": str(parent.get("type") or ""),
        "category": parent.get("category"),
        "lines": [
            {
                "id": str(child.get("id") or ""),
                "description": str(child.get("description") or ""),
                "amount": _json_amount(child.get("amount")),
            }
            for child in children
        ],
    }


def load_bound_split(source_id: str) -> dict[str, Any]:
    """Parent booking plus split lines. Conserved total is the group sum."""
    needle = str(source_id or "").strip()
    if not needle:
        raise ValueError("Transaction id is required")
    bound = _open_bound_scope()
    if bound is None:
        raise RuntimeError("SQL Server is not configured")
    has_parent = _has_parent_source_column(bound.cursor, bound.table)
    where_sql, where_params = _bound_where(bound)
    bound.cursor.execute(
        f"SELECT t.source_id{', t.parent_source_id' if has_parent else ''} "
        f"FROM {bound.table} t WHERE {where_sql} AND t.source_id = ?",
        tuple([*where_params, needle]),
    )
    found = bound.cursor.fetchone()
    if found and has_parent and found[1]:
        parent_id = str(found[1])
    elif found:
        parent_id = str(found[0])
    else:
        parent_id = _root_source_id(needle)
    rows = load_bound_transactions() or []
    by_id = {str(item.get("id") or ""): item for item in rows if isinstance(item, dict)}
    parent = by_id.get(parent_id)
    if parent is None:
        raise ValueError(f"Transaction not found: {parent_id}")
    children: list[dict[str, Any]] = []
    prefix = f"{parent_id}~s"
    for item in rows:
        if not isinstance(item, dict):
            continue
        sid = str(item.get("id") or "")
        if sid.startswith(prefix) and _root_source_id(sid) == parent_id:
            children.append(item)
    children.sort(key=lambda item: str(item.get("id") or ""))
    return _split_payload(parent_id=parent_id, parent=parent, children=children)


def _mod_bits(current: int, *, category: bool = False, description: bool = False) -> int:
    value = 0 if current < 0 else int(current)
    if category:
        value |= 1
    if description:
        value |= 2
    return value


def save_bound_split(
    source_id: str,
    *,
    description: str,
    lines: list[dict[str, Any]],
) -> dict[str, Any]:
    """Rewrite split lines. Parent amount is the remainder of the original total."""
    current = load_bound_split(source_id)
    parent_id = str(current["id"])
    bound = _open_bound_scope()
    if bound is None:
        raise RuntimeError("SQL Server is not configured")
    has_parent = _has_parent_source_column(bound.cursor, bound.table)
    where_sql, where_params = _bound_where(bound)
    bound.cursor.execute(
        f"""
        SELECT
            t.account_id, t.bank_id, t.amount, t.bank_type, t.counterparty_name,
            t.counterparty_iban, t.description, t.booked_on, t.category_id,
            t.modification, t.hit
        FROM {bound.table} t
        WHERE {where_sql} AND t.source_id = ?
        """,
        tuple([*where_params, parent_id]),
    )
    parent_row = bound.cursor.fetchone()
    if parent_row is None:
        raise ValueError(f"Transaction not found: {parent_id}")
    (
        account_id,
        bank_id,
        _old_amount,
        bank_type,
        name,
        iban,
        old_description,
        booked_on,
        category_id,
        modification,
        hit,
    ) = parent_row

    original = _money(current["original_amount"])
    cleaned_lines: list[tuple[str | None, str, Decimal]] = []
    for item in lines:
        if not isinstance(item, dict):
            continue
        line_id = str(item.get("id") or "").strip() or None
        if line_id and _root_source_id(line_id) != parent_id:
            line_id = None
        cleaned_lines.append(
            (
                line_id,
                str(item.get("description") or ""),
                _money(item.get("amount")),
            )
        )
    remainder = original - sum((amount for _i, _d, amount in cleaned_lines), Decimal("0.00"))
    remainder = remainder.quantize(_MONEY)
    new_description = str(description or "")
    desc_changed = new_description != str(old_description or "")
    try:
        flag = int(modification)
    except (TypeError, ValueError):
        flag = 0
    if desc_changed:
        flag = _mod_bits(flag, description=True)

    bare_where = where_sql.replace("t.", "")
    bound.cursor.execute(
        f"""
        UPDATE {bound.table}
        SET amount = ?, description = ?, modification = ?
        WHERE {bare_where} AND source_id = ?
        """,
        (
            remainder,
            new_description or None,
            flag,
            *where_params,
            parent_id,
        ),
    )

    existing: dict[str, None] = {}
    prefix = f"{parent_id}~s"
    bound.cursor.execute(
        f"SELECT t.source_id FROM {bound.table} t WHERE {where_sql}",
        tuple(where_params),
    )
    for (sid,) in bound.cursor.fetchall():
        text = str(sid or "")
        if text.startswith(prefix) and _root_source_id(text) == parent_id:
            existing[text] = None

    used_n = set()
    for sid in existing:
        match = _SPLIT_CHILD.fullmatch(sid)
        if match:
            used_n.add(int(match.group(2)))

    keep: set[str] = set()
    need_new = sum(1 for line_id, _d, _a in cleaned_lines if not (line_id and line_id in existing))
    fresh_ids = _next_split_ids(parent_id, used_n, need_new)
    fresh_i = 0

    insert_sql = f"""
        INSERT INTO {bound.table} (
            person_id, account_id, year, bank_id, source_id, amount,
            bank_type, counterparty_name, counterparty_iban, description,
            booked_on, category_id, modification, hit
            {', parent_source_id' if has_parent else ''}
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            {', ?' if has_parent else ''})
        """
    update_sql = f"""
        UPDATE {bound.table}
        SET amount = ?, description = ?, modification = ?
        WHERE {bare_where} AND source_id = ?
        """

    for line_id, line_desc, amount in cleaned_lines:
        if line_id and line_id in existing:
            child_id = line_id
        else:
            child_id = fresh_ids[fresh_i]
            fresh_i += 1
        keep.add(child_id)
        child_flag = _mod_bits(1, description=bool(str(line_desc or "").strip()))
        if child_id in existing:
            bound.cursor.execute(
                update_sql,
                (
                    amount,
                    line_desc or None,
                    child_flag,
                    *where_params,
                    child_id,
                ),
            )
            continue
        values: list[Any] = [
            bound.person_id,
            account_id,
            bound.year,
            bank_id,
            child_id,
            amount,
            bank_type,
            name,
            iban,
            line_desc or None,
            booked_on,
            category_id,
            child_flag,
            hit,
        ]
        if has_parent:
            values.append(parent_id)
        bound.cursor.execute(insert_sql, tuple(values))

    for sid in list(existing):
        if sid in keep:
            continue
        bound.cursor.execute(
            f"""
            DELETE FROM {bound.table}
            WHERE {bare_where} AND source_id = ?
            """,
            (*where_params, sid),
        )

    bound.conn.commit()
    return load_bound_split(parent_id)


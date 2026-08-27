"""SQL Server bookings for the person/year(/bank) bound in ``app.paths``.

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
    bank_key: int
    account_id: int | None
    cursor: Any
    conn: Any


def _account_id_for_folder(cursor, person_id: int, folder: str) -> int | None:
    compact = folder.replace(" ", "")
    cursor.execute(
        "SELECT account_id, iban FROM dbo.account WHERE person_id = ?",
        person_id,
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
    sql = f"{alias}.person_id = ? AND {alias}.year = ?"
    params: list[Any] = [bound.person_id, bound.year]
    if bound.account_id is not None:
        sql += f" AND {alias}.account_id = ?"
        params.append(bound.account_id)
        return sql, params
    sql += f" AND COALESCE({alias}.bank_id, -1) = ?"
    params.append(bound.bank_key)
    return sql, params


def _open_bound_scope() -> _BoundScope | None:
    """Resolve the bound person/year(/bank) against SQL, or None if SQL is unused."""
    from app import paths, user_store

    if not user_store.database_url():
        return None
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
        WHERE username = ?
        """,
        username,
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
                    fmt,
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
        year=year,
        bank_key=-1 if bank_id is None else bank_id,
        account_id=account_id,
        cursor=cursor,
        conn=conn,
    )


def load_bound_transactions() -> list[dict[str, Any]] | None:
    """JSON-shaped bookings from SQL, or ``None`` to keep using JSON files.

    When SQL is configured and the booking table exists, this returns a list
    (possibly empty) and callers must not fall back to categorized JSON.
    """
    from app import user_store

    if not user_store.database_url():
        return None
    try:
        bound = _open_bound_scope()
        if bound is None:
            return None
        where_sql, where_params = _bound_where(bound)
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
            JOIN dbo.dim_category d ON d.category_id = t.category_id
            JOIN dbo.country c ON c.country_id = d.country_id
            WHERE {where_sql}
            ORDER BY t.booked_on DESC, t.source_id DESC
            """,
            *where_params,
        )
        rows: list[dict[str, Any]] = []
        for item in bound.cursor.fetchall():
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
                    "category": int(local_code),
                    "modification": flag,
                    "hit": None if hit in (None, "") else str(hit),
                }
            )
        return rows
    except Exception as exc:  # noqa: BLE001
        try:
            user_store._SQL.rollback()
        except Exception:
            pass
        print(f"sql replica: failed to load bookings: {exc}")
        return []


def sync_bound_transactions(records: list[dict[str, Any]]) -> None:
    """UPDATE ``transaction_*`` for the person/year(/bank) bound in ``app.paths``."""
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

        extra = " AND account_id = ?" if bound.account_id is not None else ""
        sql = f"""
            UPDATE {bound.table}
            SET category_id = ?, modification = ?, hit = ?, description = ?
            WHERE person_id = ? AND year = ? AND source_id = ?
              AND COALESCE(bank_id, -1) = ?{extra}
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
                    bound.bank_key,
                )
            if bound.account_id is not None:
                row = (*row, bound.account_id)
            params.append(row)
        if not params:
            return
        bound.cursor.fast_executemany = True
        bound.cursor.executemany(sql, params)
        bound.cursor.fast_executemany = False
        bound.conn.commit()
    except Exception as exc:  # noqa: BLE001
        try:
            user_store._SQL.rollback()
        except Exception:
            pass
        print(f"sql replica: failed to update bookings: {exc}")


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
    default_format: str | None = "secret",
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
                    SET account_name = ?, format = COALESCE(?, format), balance = ?
                    WHERE account_id = ?
                    """,
                    name or iban,
                    fmt,
                    balance,
                    account_id,
                )
            out.append({"account_id": account_id, "iban": iban, "account_name": name or iban})
        _refresh_account_count(bound.cursor, bound.person_id)
        bound.conn.commit()
        return out
    except Exception as exc:  # noqa: BLE001
        try:
            user_store._SQL.rollback()
        except Exception:
            pass
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
        bank_id = None if bound.bank_key < 0 else bound.bank_key
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
        try:
            user_store._SQL.rollback()
        except Exception:
            pass
        print(f"sql replica: failed to insert bookings: {exc}")
        return 0

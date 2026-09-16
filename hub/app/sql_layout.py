"""Create dbo.country / dbo.center rows. Does not create on-disk country/center directories."""
from __future__ import annotations

import re
from typing import Any

from app.core.categorize import DEFAULT_CATEGORY
from app.runtime import country_folder
from app.sql_replica import _sql_ident, _transaction_table

_FOLDER_NAME_MAX = 32
_CURRENCY = re.compile(r"^[A-Za-z]{3}$")


def _valid_name(name: str) -> str:
    cleaned = name.strip()
    if not cleaned or ".." in cleaned or "/" in cleaned or "\\" in cleaned:
        raise ValueError(f"Invalid name: {name!r}")
    if not all(c.isalnum() or c in "_-" for c in cleaned):
        raise ValueError(f"Name must be alphanumeric/underscore/hyphen: {name!r}")
    if len(cleaned) > _FOLDER_NAME_MAX:
        raise ValueError(f"Name too long (max {_FOLDER_NAME_MAX}): {name!r}")
    if _sql_ident(cleaned) is None:
        raise ValueError(f"Name must start with a letter: {name!r}")
    return cleaned


def _valid_currency(currency: str) -> str:
    text = str(currency or "").strip().upper()
    if not _CURRENCY.fullmatch(text):
        raise ValueError(f"Currency must be a 3-letter code: {currency!r}")
    return text


def _seed_system_categories(cursor, country_id: int) -> None:
    """Balance, Updated, and unclassified entry (role remainder; seed local_code only)."""
    base = country_id * 10000
    cursor.execute(
        """
        INSERT INTO dbo.dim_category
            (category_id, country_id, local_code, label, category_role)
        VALUES (?, ?, ?, ?, ?)
        """,
        base,
        country_id,
        98,
        "Balance",
        "balance",
    )
    cursor.execute(
        """
        INSERT INTO dbo.dim_category
            (category_id, country_id, local_code, label, category_role)
        VALUES (?, ?, ?, ?, ?)
        """,
        base + 1,
        country_id,
        99,
        "Updated",
        "last_booked",
    )
    cursor.execute(
        """
        INSERT INTO dbo.dim_category
            (category_id, country_id, local_code, label, category_role)
        VALUES (?, ?, ?, ?, ?)
        """,
        base + 2,
        country_id,
        DEFAULT_CATEGORY,
        "Unclassified",
        "remainder",
    )


_BANK_FORMAT_ROWS: list[tuple[int, str, str]] = [
    (1, "BoS", "bos-csv"),
    (2, "LLOYDS", "lloyds-csv"),
    (3, "RBS", "rbs-csv"),
    (4, "Natwest", "natwest-csv"),
]


def _seed_bank_formats(cursor) -> None:
    """Register the four bank upload formats in ``dbo.bank`` (idempotent).

    The upload UI offers excel plus one entry per ``dbo.bank`` row, so the
    table must be seeded exactly once (the four formats the file sniffers
    recognize: BoS/Lloyds debit-credit and RBS/Natwest value-balance CSVs).
    """
    cursor.execute("SELECT COUNT(*) FROM dbo.bank")
    if cursor.fetchone()[0]:
        return
    cursor.executemany(
        """
        INSERT INTO dbo.bank (bank_id, bank_name_official, file_format)
        VALUES (?, ?, ?)
        """,
        _BANK_FORMAT_ROWS,
    )


def _require_transaction_table(cursor, *, country: str, country_id: int | None = None) -> str:
    """Return ``dbo.transaction_{country}``; it must already exist (SSMS)."""
    del country_id
    table = _transaction_table(country)
    if table is None:
        raise ValueError(f"Cannot derive transaction table for {country!r}")
    cursor.execute(f"SELECT OBJECT_ID(N'{table}', N'U')")
    if cursor.fetchone()[0] is None:
        raise ValueError(f"{table} is missing. Create it in SSMS.")
    return table


def ensure_transaction_table(*, country: str) -> str:
    """Return ``dbo.transaction_{country}`` if it exists, else ``""``."""
    from app import user_store

    username = _valid_name(country)
    if not username or not user_store.database_url():
        return ""
    table = _transaction_table(username)
    if table is None:
        return ""
    user_store.init_user_store()
    cursor = user_store._sql_connect().cursor()
    cursor.execute(f"SELECT OBJECT_ID(N'{table}', N'U')")
    if cursor.fetchone()[0] is None:
        return ""
    return table


def _next_center_id(cursor) -> int:
    cursor.execute("SELECT center_id FROM dbo.center")
    used = {int(row[0]) for row in cursor.fetchall()}
    candidate = 1
    while candidate in used:
        candidate += 1
    return candidate


def _reseed_center_id(cursor, center_id: int) -> None:
    cursor.execute(f"DBCC CHECKIDENT (N'dbo.center', RESEED, {int(center_id)})")


def _center_id_is_identity(cursor) -> bool:
    cursor.execute(
        "SELECT COLUMNPROPERTY(OBJECT_ID(N'dbo.center'), N'center_id', N'IsIdentity')"
    )
    row = cursor.fetchone()
    return bool(row and int(row[0] or 0))


def _insert_center_row(
    cursor, *, country_id: int, username: str, title: str
) -> int:
    """Insert ``dbo.center`` with the next unused ``center_id`` (1, 2, 3, …)."""
    center_id = _next_center_id(cursor)
    if _center_id_is_identity(cursor):
        cursor.execute("SET IDENTITY_INSERT dbo.center ON")
        try:
            cursor.execute(
                """
                INSERT INTO dbo.center (center_id, country_id, username, title)
                VALUES (?, ?, ?, ?)
                """,
                center_id,
                country_id,
                username,
                title,
            )
        finally:
            cursor.execute("SET IDENTITY_INSERT dbo.center OFF")
        _reseed_center_id(cursor, center_id)
    else:
        cursor.execute(
            """
            INSERT INTO dbo.center (center_id, country_id, username, title)
            VALUES (?, ?, ?, ?)
            """,
            center_id,
            country_id,
            username,
            title,
        )
    return center_id


def create_country(*, name: str, currency: str, title: str = "") -> dict[str, Any]:
    """Insert ``dbo.country``. ``dbo.transaction_{country}`` must already exist."""
    from app import user_store

    username = _valid_name(name)
    currency_s = _valid_currency(currency)
    if not user_store.database_url():
        raise RuntimeError("SQL Server is not configured (HUB_DATABASE_URL)")

    user_store.init_user_store()
    conn = user_store._sql_connect()
    cursor = conn.cursor()
    try:
        _seed_bank_formats(cursor)
        cursor.execute(
            """
            SELECT country_id, title, currency_default FROM dbo.country
            WHERE username = ? COLLATE Latin1_General_CI_AI
            """,
            username,
        )
        existing = cursor.fetchone()
        if existing:
            raise ValueError(f"Country already exists: {username}")
        if user_store._sql_username_taken(cursor, username):
            raise ValueError(f"Username already used: {username}")
        table = _require_transaction_table(cursor, country=username)
        cursor.execute("SELECT ISNULL(MAX(country_id), 0) + 1 FROM dbo.country")
        country_id = int(cursor.fetchone()[0])
        cursor.execute(
            """
            INSERT INTO dbo.country (country_id, username, title, currency_default)
            VALUES (?, ?, ?, ?)
            """,
            country_id,
            username,
            (title.strip() or user_store.display_title(username) or username),
            currency_s,
        )
        _seed_system_categories(cursor, country_id)
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    return {
        "ok": True,
        "country_id": country_id,
        "name": username,
        "currency": currency_s,
        "transaction_table": table,
        "title": (title.strip() or user_store.display_title(username) or username),
        "login": {
            "username": username,
            "password": user_store.password_for_username(username),
        },
    }


def create_center(*, name: str, country: str, title: str = "") -> dict[str, Any]:
    """Insert ``dbo.center`` under an existing country."""
    from app import user_store

    username = _valid_name(name)
    country_key = str(country or "").strip()
    if not country_key:
        raise ValueError("country is required")
    resolved = country_folder(country_key) or country_key
    if not user_store.database_url():
        raise RuntimeError("SQL Server is not configured (HUB_DATABASE_URL)")

    user_store.init_user_store()
    conn = user_store._sql_connect()
    cursor = conn.cursor()
    try:
        _seed_bank_formats(cursor)
        if user_store._sql_username_taken(cursor, username):
            raise ValueError(f"Username already used: {username}")
        cursor.execute(
            "SELECT country_id FROM dbo.country WHERE username = ? COLLATE Latin1_General_CI_AI",
            resolved,
        )
        row = cursor.fetchone()
        if row is None:
            raise ValueError(f"Unknown country: {resolved}")
        country_id = int(row[0])
        cursor.execute(
            """
            SELECT center_id FROM dbo.center
            WHERE country_id = ? AND username = ? COLLATE Latin1_General_CI_AI
            """,
            country_id,
            username,
        )
        if cursor.fetchone():
            raise ValueError(f"Center already exists: {username}")
        title_value = title.strip() or user_store.display_title(username) or username
        center_id = _insert_center_row(
            cursor,
            country_id=country_id,
            username=username,
            title=title_value,
        )
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    return {
        "ok": True,
        "center_id": center_id,
        "name": username,
        "country": resolved,
        "country_id": country_id,
        "title": (title.strip() or user_store.display_title(username) or username),
        "login": {
            "username": username,
            "password": user_store.password_for_username(username),
        },
    }

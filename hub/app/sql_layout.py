"""Create dbo.country / dbo.center rows. Does not create workspace directories."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from app.core.categorize import DEFAULT_CATEGORY
from app.runtime import country_folder, data_root
from app.sql_replica import _sql_ident, _transaction_table

_FOLDER_NAME_MAX = 32
_CURRENCY = re.compile(r"^[A-Za-z]{3}$")
_LOCAL_CODE = re.compile(r"^(\d{2})\b")


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


def _local_code(label: str) -> int | None:
    match = _LOCAL_CODE.match(str(label).strip())
    if match:
        return int(match.group(1))
    try:
        return int(str(label)[:2])
    except ValueError:
        return None


def _donor_categories() -> Path | None:
    root = data_root()
    for folder in ("nederland", "united_kingdom", "uk"):
        path = root / folder / "categories.json"
        if path.is_file():
            return path
    return None


def _seed_matrix_footers(cursor, country_id: int) -> None:
    """Matrix saldo/datum rows: local codes 98 Balance and 99 Updated."""
    base = country_id * 100
    cursor.execute(
        """
        INSERT INTO dbo.dim_category
            (category_id, country_id, local_code, label, is_remainder, matrix_role)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        base,
        country_id,
        98,
        "Balance",
        0,
        "balance",
    )
    cursor.execute(
        """
        INSERT INTO dbo.dim_category
            (category_id, country_id, local_code, label, is_remainder, matrix_role)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        base + 1,
        country_id,
        99,
        "Updated",
        0,
        "last_booked",
    )


def _seed_dim_category(cursor, country_id: int, categories_path: Path) -> None:
    payload = json.loads(categories_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Invalid categories.json: {categories_path}")
    categories = payload.get("categories")
    if not isinstance(categories, dict) or not categories:
        raise ValueError(f"No categories in {categories_path}")
    term_rows: list[tuple[int, str, int]] = []
    abbr_rows: list[tuple[int, str, str]] = []
    booking_index = 0
    for label, terms in categories.items():
        code = _local_code(str(label))
        if code is None or code in (98, 99):
            continue
        category_id = country_id * 100 + 2 + booking_index
        booking_index += 1
        is_remainder = 1 if code == DEFAULT_CATEGORY else 0
        cursor.execute(
            """
            INSERT INTO dbo.dim_category
                (category_id, country_id, local_code, label, is_remainder, matrix_role)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            category_id,
            country_id,
            code,
            str(label),
            is_remainder,
            None,
        )
        if isinstance(terms, list):
            for sort_order, term in enumerate(terms):
                text = str(term).strip()
                if text:
                    term_rows.append((category_id, text, sort_order))
    abbreviations = payload.get("abbreviations") or {}
    if isinstance(abbreviations, dict):
        for bank_type, abbreviation in abbreviations.items():
            abbr_rows.append((country_id, str(bank_type), str(abbreviation)[:16]))
    if term_rows:
        cursor.executemany(
            """
            INSERT INTO dbo.category_term (category_id, person_id, term, sort_order)
            VALUES (?, NULL, ?, ?)
            """,
            term_rows,
        )
    if abbr_rows:
        cursor.executemany(
            """
            INSERT INTO dbo.type_abbreviation (country_id, bank_type, abbreviation)
            VALUES (?, ?, ?)
            """,
            abbr_rows,
        )


def _txn_constraint_tag(table: str) -> str:
    name = table.split(".")[-1]
    prefix = "transaction_"
    if name.lower().startswith(prefix):
        tag = _sql_ident(name[len(prefix) :])
        if tag:
            return tag
    ident = _sql_ident(name)
    if ident is None:
        raise ValueError(f"Cannot derive constraint names for {table!r}")
    return ident


def _expected_transaction_tables(cursor) -> set[str]:
    cursor.execute("SELECT username FROM dbo.country")
    tables: set[str] = set()
    for (username,) in cursor.fetchall():
        table = _transaction_table(str(username or ""))
        if table:
            tables.add(table.lower())
    return tables


def _drop_orphan_transaction_tables(cursor) -> None:
    """Drop leftover ``transaction_*`` tables that have no matching country."""
    expected = _expected_transaction_tables(cursor)
    cursor.execute(
        """
        SELECT name FROM sys.tables
        WHERE schema_id = SCHEMA_ID(N'dbo')
          AND name LIKE N'transaction[_]%'
        """
    )
    for (name,) in list(cursor.fetchall()):
        ident = _sql_ident(str(name or ""))
        if ident is None:
            continue
        table = f"dbo.{ident}"
        if table.lower() in expected:
            continue
        cursor.execute(f"DROP TABLE {table}")


def _create_transaction_table(cursor, *, country: str, country_id: int) -> str:
    """Create empty ``dbo.transaction_{country}`` with the standard booking columns."""
    table = _transaction_table(country)
    if table is None:
        raise ValueError(f"Cannot derive transaction table for {country!r}")
    lo = country_id * 100
    hi = lo + 99
    tag = _txn_constraint_tag(table)
    cursor.execute(f"SELECT OBJECT_ID(N'{table}', N'U')")
    if cursor.fetchone()[0] is not None:
        return table
    cursor.execute(
        f"""
        CREATE TABLE {table} (
            transaction_id BIGINT IDENTITY(1, 1) NOT NULL PRIMARY KEY,
            person_id INT NOT NULL,
            account_id INT NOT NULL,
            year SMALLINT NOT NULL,
            bank_id INT NULL,
            source_id NVARCHAR(128) NOT NULL,
            amount DECIMAL(18, 2) NOT NULL,
            bank_type NVARCHAR(64) NULL,
            counterparty_name NVARCHAR(512) NULL,
            counterparty_iban NVARCHAR(64) NULL,
            description NVARCHAR(MAX) NULL,
            booked_on DATE NOT NULL,
            category_id INT NOT NULL,
            modification SMALLINT NOT NULL CONSTRAINT df_txn_{tag}_mod DEFAULT (-1),
            hit NVARCHAR(64) NULL,
            CONSTRAINT fk_txn_{tag}_person FOREIGN KEY (person_id) REFERENCES dbo.person (id),
            CONSTRAINT fk_txn_{tag}_account FOREIGN KEY (account_id) REFERENCES dbo.account (account_id),
            CONSTRAINT fk_txn_{tag}_bank FOREIGN KEY (bank_id) REFERENCES dbo.bank (bank_id),
            CONSTRAINT fk_txn_{tag}_category FOREIGN KEY (category_id) REFERENCES dbo.dim_category (category_id),
            CONSTRAINT ck_txn_{tag}_year CHECK (year >= 1990 AND year <= 2100),
            CONSTRAINT ck_txn_{tag}_mod CHECK (modification IN (-1, 0, 1, 2, 3)),
            CONSTRAINT ck_txn_{tag}_cat CHECK (category_id BETWEEN {lo} AND {hi})
        )
        """
    )
    cursor.execute(
        f"""
        CREATE UNIQUE INDEX ux_txn_{tag}_consolidated
            ON {table} (person_id, year, source_id)
            WHERE bank_id IS NULL
        """
    )
    cursor.execute(
        f"""
        CREATE UNIQUE INDEX ux_txn_{tag}_bank
            ON {table} (person_id, year, bank_id, source_id)
            WHERE bank_id IS NOT NULL
        """
    )
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
    """Insert ``dbo.country`` and empty ``dbo.transaction_{country}``. Login password equals the username."""
    from app import user_store

    username = _valid_name(name)
    currency_s = _valid_currency(currency)
    if not user_store.database_url():
        raise RuntimeError("SQL Server is not configured (HUB_DATABASE_URL)")

    user_store.init_user_store()
    conn = user_store._sql_connect()
    cursor = conn.cursor()
    try:
        _drop_orphan_transaction_tables(cursor)
        cursor.execute(
            """
            SELECT country_id, title, currency_default FROM dbo.country
            WHERE username = ? COLLATE Latin1_General_CI_AI
            """,
            username,
        )
        existing = cursor.fetchone()
        if existing:
            country_id = int(existing[0])
            wanted = _transaction_table(username)
            if wanted is None:
                raise ValueError(f"Cannot derive transaction table for {username!r}")
            cursor.execute(f"SELECT OBJECT_ID(N'{wanted}', N'U')")
            had_table = cursor.fetchone()[0] is not None
            table = _create_transaction_table(
                cursor, country=username, country_id=country_id
            )
            if had_table:
                raise ValueError(f"Country already exists: {username}")
            conn.commit()
            return {
                "ok": True,
                "country_id": country_id,
                "name": username,
                "currency": str(existing[2] or currency_s),
                "transaction_table": table,
                "title": str(existing[1] or username),
                "login": {"username": username, "password": username},
            }
        if user_store._sql_username_taken(cursor, username):
            raise ValueError(f"Username already used: {username}")
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
        _seed_matrix_footers(cursor, country_id)
        donor = _donor_categories()
        if donor is not None:
            _seed_dim_category(cursor, country_id, donor)
        table = _create_transaction_table(cursor, country=username, country_id=country_id)
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
        "login": {"username": username, "password": username},
    }


def create_center(*, name: str, country: str, title: str = "") -> dict[str, Any]:
    """Insert ``dbo.center`` under an existing country. Login password equals the username."""
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
        "login": {"username": username, "password": username},
    }

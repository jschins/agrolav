"""Create dbo.country / dbo.center rows (and matching workspace folders)."""
from __future__ import annotations

import json
import re
import shutil
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


def _seed_dim_category(cursor, country_id: int, categories_path: Path) -> None:
    payload = json.loads(categories_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Invalid categories.json: {categories_path}")
    categories = payload.get("categories")
    if not isinstance(categories, dict) or not categories:
        raise ValueError(f"No categories in {categories_path}")
    term_rows: list[tuple[int, str, int]] = []
    abbr_rows: list[tuple[int, str, str]] = []
    footers = 0
    for index, (label, terms) in enumerate(categories.items()):
        category_id = country_id * 100 + index
        code = _local_code(str(label))
        matrix_role = None
        if code is None:
            if footers == 0:
                code = 22
                matrix_role = "balance"
            elif footers == 1:
                code = 23
                matrix_role = "last_booked"
            else:
                raise ValueError(f"Extra footer label {label!r}")
            footers += 1
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
            matrix_role,
        )
        if isinstance(terms, list) and matrix_role is None:
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


def _create_transaction_table(cursor, *, folder: str, country_id: int) -> str:
    table = _transaction_table(folder)
    if table is None:
        raise ValueError(f"Cannot derive transaction table for {folder!r}")
    lo = country_id * 100
    hi = lo + 99
    tag = f"c{country_id}"
    cursor.execute(f"SELECT OBJECT_ID(N'{table}', N'U')")
    if cursor.fetchone()[0] is None:
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


def create_country(*, name: str, currency: str) -> dict[str, Any]:
    """Insert ``dbo.country`` and scaffold the workspace folder. Login is the username."""
    from app import user_store

    folder = _valid_name(name)
    currency_s = _valid_currency(currency)
    if not user_store.database_url():
        raise RuntimeError("SQL Server is not configured (HUB_DATABASE_URL)")

    root = data_root()
    dest = root / folder
    if dest.exists():
        raise ValueError(f"Folder already exists: {folder}")

    user_store.init_user_store()
    conn = user_store._sql_connect()
    cursor = conn.cursor()
    created_dir = False
    try:
        if user_store._sql_username_taken(cursor, folder):
            raise ValueError(f"Username already used: {folder}")
        cursor.execute(
            "SELECT country_id FROM dbo.country WHERE username = ? COLLATE Latin1_General_CI_AI",
            folder,
        )
        if cursor.fetchone():
            raise ValueError(f"Country already exists: {folder}")
        cursor.execute("SELECT ISNULL(MAX(country_id), 0) + 1 FROM dbo.country")
        country_id = int(cursor.fetchone()[0])
        cursor.execute(
            "INSERT INTO dbo.country (country_id, username, currency_default) VALUES (?, ?, ?)",
            country_id,
            folder,
            currency_s,
        )
        dest.mkdir(parents=True, exist_ok=False)
        created_dir = True
        donor = _donor_categories()
        categories_path = dest / "categories.json"
        if donor is not None:
            shutil.copy2(donor, categories_path)
            _seed_dim_category(cursor, country_id, categories_path)
        else:
            categories_path.write_text("{}\n", encoding="utf-8")
        table = _create_transaction_table(cursor, folder=folder, country_id=country_id)
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        if created_dir and dest.exists():
            shutil.rmtree(dest, ignore_errors=True)
        raise
    return {
        "ok": True,
        "country_id": country_id,
        "name": folder,
        "currency": currency_s,
        "transaction_table": table,
        "login": {"username": folder, "password": folder},
    }


def create_center(*, name: str, country: str) -> dict[str, Any]:
    """Insert ``dbo.center`` under an existing country and scaffold the folder. Login is the username."""
    from app import user_store

    folder = _valid_name(name)
    country_key = str(country or "").strip()
    if not country_key:
        raise ValueError("country is required")
    resolved = country_folder(country_key) or country_key
    if not user_store.database_url():
        raise RuntimeError("SQL Server is not configured (HUB_DATABASE_URL)")

    dest = data_root() / resolved / folder
    if dest.exists():
        raise ValueError(f"Folder already exists: {resolved}/{folder}")
    country_dir = data_root() / resolved
    if not country_dir.is_dir():
        raise ValueError(f"Unknown country folder: {resolved}")

    user_store.init_user_store()
    conn = user_store._sql_connect()
    cursor = conn.cursor()
    created_dir = False
    try:
        if user_store._sql_username_taken(cursor, folder):
            raise ValueError(f"Username already used: {folder}")
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
            folder,
        )
        if cursor.fetchone():
            raise ValueError(f"Center already exists: {folder}")
        cursor.execute(
            "INSERT INTO dbo.center (country_id, username) OUTPUT INSERTED.center_id VALUES (?, ?)",
            country_id,
            folder,
        )
        center_id = int(cursor.fetchone()[0])
        dest.mkdir(parents=True, exist_ok=False)
        created_dir = True
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        if created_dir and dest.exists():
            shutil.rmtree(dest, ignore_errors=True)
        raise
    return {
        "ok": True,
        "center_id": center_id,
        "name": folder,
        "country": resolved,
        "country_id": country_id,
        "login": {"username": folder, "password": folder},
    }

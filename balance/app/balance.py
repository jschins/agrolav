"""Balance sheet calculation for balance countries (Beheer country_id=4, …).

Each balance country reads bank account balances from ``dbo.account`` and
non-bank opening balances from ``dbo.balance_opening``, plus hand-edited
journal rows (``dbo.balance_journal``) and auto spaar-mirror rows
(``dbo.balance_transaction``).  The Verlies (loss/profit) post is computed as
the balancing figure: ``total_activa - sum(other passiva)``.

The balance tables carry a ``country_id`` so every country keeps its own
opening balances, journal and mirror.  The instance serves the country given
by ``BALANCE_COUNTRY_ID`` (default 4).
"""
from __future__ import annotations

import os
import re
from decimal import Decimal
from typing import Any

from app.db import connect

SPAAR_MARKER = "[spaar-mirror]"
_VERLIES_SUFFIX = "Verlies"
_IDENT = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")

# category_id → (side, account_id | None)
# side: "activa" or "passiva"
_BEHEER_CATEGORY_MAP: dict[int, tuple[str, int | None]] = {
    1000: ("activa", None),       # Gebouwen
    1005: ("activa", None),       # Verbouwingen
    1010: ("activa", None),       # Inventaris
    1015: ("activa", None),       # Autos
    1051: ("activa", 18),         # Bank algemeen
    1052: ("activa", None),       # Spaarrekening
    1053: ("activa", 20),         # Bank huishoudelijke dienst
    1054: ("activa", 17),         # Bank FPU
    1055: ("activa", 19),         # Bank FOH
    1056: ("activa", 21),         # Bank residentie ddkg
    1110: ("activa", None),       # Kruisposten
    1111: ("activa", None),       # r/c K218
    2000: ("passiva", None),      # Eigen vermogen
    2050: ("passiva", None),      # Reserve Vergeer
    2055: ("passiva", None),      # Reserve FF-OG
    2100: ("passiva", None),      # Verlies (computed)
    2500: ("passiva", None),      # Schulden particulieren
}

# The checking → spaarrekening pair for Beheer. Money moves between 1051
# (account 18, NL34..667) and 1052 via transactions that are invisible on the
# spaarrekening side. We reconstruct them by mirroring the 1051 rows whose
# description contains "spaarrekening", with the sign flipped.
_BEHEER_MIRROR: dict[str, Any] = {
    "source_account_id": 18,
    "source_category": 1051,
    "target_category": 1052,
    "keyword": "spaarrekening",
}

# Per-country balance configuration:
#   verlies_id:   the computed Verlies category on the passiva side
#   category_map: category_id → (side, account_id | None); account_id links a
#                 bank account whose live balance feeds that category. When
#                 empty, every dim_category row 1000-4999 is used (side by
#                 range, no account link).
#   mirror:       spaarrekening mirror settings, or None when not used.
#
# Whether a country carries a balance sheet at all is declared in the database
# on ``dbo.country.has_balance`` (set to 1 for sdog and instudo, 0 elsewhere).
_BALANCE_COUNTRIES: dict[int, dict[str, Any]] = {
    4: {
        "verlies_id": 2100,
        "category_map": _BEHEER_CATEGORY_MAP,
        "mirror": _BEHEER_MIRROR,
    },
    5: {
        "verlies_id": 2100,
        # instudo: fill in its own balance categories and bank-account links.
        "category_map": {},
        "mirror": None,
    },
}

_EMPTY_CONFIG: dict[str, Any] = {
    "verlies_id": 2100,
    "category_map": {},
    "mirror": None,
}

_has_balance_cache: dict[int, bool] = {}


def _country_has_balance(country_id: int) -> bool:
    """``dbo.country.has_balance`` for a country (True when the column is missing)."""
    cached = _has_balance_cache.get(country_id)
    if cached is not None:
        return cached
    try:
        with connect() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT has_balance FROM dbo.country WHERE country_id = ?",
                country_id,
            )
            row = cur.fetchone()
        value = bool(row[0]) if row else False
    except Exception:
        value = True
    _has_balance_cache[country_id] = value
    return value


def balance_country_ids() -> list[int]:
    """Country ids flagged ``has_balance = 1`` (falls back to Beheer/sdog)."""
    try:
        with connect() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT country_id FROM dbo.country "
                "WHERE has_balance = 1 ORDER BY country_id"
            )
            ids = [int(r[0]) for r in cur.fetchall()]
    except Exception:
        ids = []
    return ids or [4]


def active_country_id() -> int:
    """The balance country this instance serves.

    ``BALANCE_COUNTRY_ID`` overrides; otherwise the first country flagged
    ``dbo.country.has_balance = 1`` is used (that flag is what makes a country
    a balance country at all).
    """
    raw = os.environ.get("BALANCE_COUNTRY_ID", "").strip()
    if raw:
        try:
            country_id = int(raw)
        except ValueError:
            country_id = 0
        if country_id > 0:
            return country_id
    ids = balance_country_ids()
    return ids[0] if ids else 4


def _country_config(country_id: int) -> dict[str, Any]:
    if not _country_has_balance(country_id):
        return dict(_EMPTY_CONFIG)
    return _BALANCE_COUNTRIES.get(country_id, dict(_EMPTY_CONFIG))


def _verlies_id(country_id: int) -> int:
    return int(_country_config(country_id).get("verlies_id") or 2100)


def _sql_ident(text: str) -> str | None:
    return text if _IDENT.fullmatch(text or "") else None


def _transaction_table(country_id: int) -> str | None:
    """``dbo.transaction_{country.username}`` for a balance country."""
    with connect() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT username FROM dbo.country WHERE country_id = ?",
            country_id,
        )
        row = cur.fetchone()
    if not row:
        return None
    ident = _sql_ident(str(row[0] or ""))
    return f"dbo.transaction_{ident}" if ident else None


def _account_balances(country_id: int) -> dict[int, Decimal]:
    """account_id → balance for the country's persons."""
    with connect() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT a.account_id, a.balance FROM dbo.account a "
            "JOIN dbo.person p ON p.id = a.person_id "
            "JOIN dbo.center c ON c.center_id = p.center_id "
            "WHERE c.country_id = ?",
            country_id,
        )
        return {int(r[0]): Decimal(str(r[1])) for r in cur.fetchall()}


def _opening_balances(country_id: int, year: int) -> dict[int, Decimal]:
    """category_id → amount from dbo.balance_opening."""
    with connect() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT category_id, amount FROM dbo.balance_opening "
            "WHERE country_id = ? AND year = ?",
            country_id,
            year,
        )
        return {int(r[0]): Decimal(str(r[1])) for r in cur.fetchall()}


def _journal_balances(country_id: int, year: int) -> dict[int, Decimal]:
    """category_id → net sum of dbo.balance_transaction for a country/year."""
    with connect() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT category_id, SUM(amount) FROM dbo.balance_transaction "
            "WHERE country_id = ? AND year = ? GROUP BY category_id",
            country_id,
            year,
        )
        return {int(r[0]): Decimal(str(r[1])) for r in cur.fetchall()}


def _journal_table_exists() -> bool:
    with connect() as conn:
        cur = conn.cursor()
        cur.execute("SELECT OBJECT_ID(N'dbo.balance_journal')")
        return cur.fetchone()[0] is not None


def _journal_effect(country_id: int, year: int) -> dict[int, Decimal]:
    """category_id → net effect from the hand-edited dbo.balance_journal.

    Each row moves money FROM ``category_from`` TO ``category_to``: the FROM
    category decreases by ``amount`` and the TO category increases by ``amount``.
    The sum over all categories is therefore zero (the sheet stays balanced).
    """
    if not _journal_table_exists():
        return {}
    effect: dict[int, Decimal] = {}
    with connect() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT category_from, category_to, amount FROM dbo.balance_journal "
            "WHERE country_id = ? AND year = ?",
            country_id,
            year,
        )
        for cat_from, cat_to, amount in cur.fetchall():
            d = Decimal(str(amount))
            effect[cat_from] = effect.get(cat_from, Decimal("0")) - d
            effect[cat_to] = effect.get(cat_to, Decimal("0")) + d
    return effect


def _spaar_mirror_rows(country_id: int, year: int) -> list[tuple[int, str, Decimal, str]]:
    """Derive the faked spaarrekening mirror transactions for a country.

    Each source-category row on the source account whose description contains
    the keyword gives one target-category journal entry with the sign flipped:
    a transfer out ("...spaarrekening", negative) increases the mirror account,
    and a transfer in ("Van ...spaarrekening", positive) decreases it.
    """
    mirror = _country_config(country_id).get("mirror")
    if not mirror:
        return []
    table = _transaction_table(country_id)
    if table is None:
        return []
    rows: list[tuple[int, str, Decimal, str]] = []
    with connect() as conn:
        cur = conn.cursor()
        cur.execute(
            f"SELECT booked_on, amount, description FROM {table} "
            "WHERE year = ? AND account_id = ? "
            "AND LOWER(COALESCE(description, N'')) LIKE ? "
            "ORDER BY booked_on",
            year,
            int(mirror["source_account_id"]),
            f"%{mirror['keyword']}%",
        )
        for booked_on, amount, description in cur.fetchall():
            d = Decimal(str(amount))
            rows.append(
                (
                    int(mirror["target_category"]),
                    str(booked_on),
                    -d,
                    f"{SPAAR_MARKER} {str(description or '')[:180]}",
                )
            )
    return rows


def _sum_amount(items: list[dict[str, Any]]) -> Decimal:
    return sum(Decimal(str(item["amount"])) for item in items)


def _category_labels(country_id: int) -> dict[int, str]:
    """category_id → label from dbo.dim_category (balance categories)."""
    with connect() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT category_id, label FROM dbo.dim_category "
            "WHERE country_id = ? AND category_id BETWEEN 1000 AND 4999",
            country_id,
        )
        return {int(r[0]): str(r[1]) for r in cur.fetchall()}


def _dim_category_ids(country_id: int) -> set[int]:
    with connect() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT DISTINCT category_id FROM dbo.dim_category "
            "WHERE country_id = ? AND category_id BETWEEN 1000 AND 4999",
            country_id,
        )
        return {int(r[0]) for r in cur.fetchall()}


def _category_ids(country_id: int) -> set[int]:
    ids = _dim_category_ids(country_id)
    ids.update(
        c for c in (_country_config(country_id).get("category_map") or {})
        if isinstance(c, int)
    )
    return {i for i in ids if 1000 <= i <= 4999}


def _category_map(country_id: int) -> dict[int, tuple[str, int | None]]:
    configured = _country_config(country_id).get("category_map") or {}
    if configured:
        return {
            int(c): (str(s), (int(a) if a is not None else None))
            for c, (s, a) in configured.items()
        }
    return {cat: (_infer_side(cat), None) for cat in _dim_category_ids(country_id)}


def country_title(country_id: int) -> str:
    """Display title from dbo.country (falls back to the username)."""
    with connect() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT title, username FROM dbo.country WHERE country_id = ?",
            country_id,
        )
        row = cur.fetchone()
    if not row:
        return ""
    title = str(row[0] or "").strip()
    return title or str(row[1] or "")


def balance_sheet(country_id: int, year: int) -> dict[str, Any]:
    """Return the full balance sheet for a given country and year."""
    acct = _account_balances(country_id)
    opening = _opening_balances(country_id, year)
    journal = _journal_balances(country_id, year)
    journal_effect = _journal_effect(country_id, year)
    labels = _category_labels(country_id)
    category_map = _category_map(country_id)
    verlies_id = _verlies_id(country_id)

    activa: list[dict[str, Any]] = []
    passiva: list[dict[str, Any]] = []

    for cat_id in sorted(category_map):
        side, account_id = category_map[cat_id]
        label = labels.get(cat_id, f"cat_{cat_id}")

        if cat_id == verlies_id:
            # computed later
            continue

        if account_id is not None:
            opening_amount = opening.get(cat_id)
            if opening_amount is not None:
                # The bank category amount is the initial (opening) balance
                # recorded in dbo.balance_opening.
                amount = opening_amount
                source = "opening"
            else:
                # No recorded opening balance yet — fall back to the live
                # dbo.account.balance for the mapped account.
                amount = acct.get(account_id, Decimal("0"))
                source = f"account:{account_id}"
        else:
            amount = opening.get(cat_id, Decimal("0"))
            source = "opening"

        journal_amount = journal.get(cat_id)
        if journal_amount is not None:
            amount += journal_amount
            if "+journal" not in source:
                source += "+journal"

        effect = journal_effect.get(cat_id)
        if effect:
            amount += effect
            if "+journal" not in source:
                source += "+journal"

        row = {"category_id": cat_id, "code": cat_id, "label": label,
               "amount": float(amount), "source": source}
        if side == "activa":
            activa.append(row)
        else:
            passiva.append(row)

    total_activa = _sum_amount(activa)
    total_passiva_others = _sum_amount(passiva)

    verlies_amount = total_activa - total_passiva_others
    passiva.append({
        "category_id": verlies_id,
        "code": verlies_id,
        "label": labels.get(verlies_id, _VERLIES_SUFFIX),
        "amount": float(verlies_amount),
        "source": "computed",
    })

    total_passiva = total_passiva_others + verlies_amount

    return {
        "year": year,
        "country_id": country_id,
        "activa": activa,
        "passiva": passiva,
        "total_activa": float(total_activa),
        "total_passiva": float(total_passiva),
        "balanced": total_activa == total_passiva,
    }


def list_years(country_id: int) -> list[int]:
    """Years that have any data in balance_opening for this country."""
    with connect() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT DISTINCT year FROM dbo.balance_opening "
            "WHERE country_id = ? ORDER BY year",
            country_id,
        )
        return [int(r[0]) for r in cur.fetchall()]


def list_categories(country_id: int) -> list[dict[str, Any]]:
    """All balance categories (1000-4999) with their account links (if any)."""
    labels = _category_labels(country_id)
    acct = _account_balances(country_id)
    category_map = _category_map(country_id)
    ids = _category_ids(country_id)
    result = []
    for cat_id in sorted(i for i in ids if 1000 <= i <= 4999):
        side, account_id = category_map.get(cat_id, (_infer_side(cat_id), None))
        row: dict[str, Any] = {
            "category_id": cat_id,
            "code": cat_id,
            "label": labels.get(cat_id, f"cat_{cat_id}"),
            "side": side,
            "account_id": account_id,
        }
        if account_id is not None:
            row["iban"] = _iban_for_account(account_id)
            row["account_balance"] = float(acct.get(account_id, Decimal("0")))
        result.append(row)
    return result


def _infer_side(cat_id: int) -> str:
    if 1000 <= cat_id <= 1999:
        return "activa"
    if 2000 <= cat_id <= 2999:
        return "passiva"
    if 3000 <= cat_id <= 3999:
        return "kosten"
    return "opbrengsten"


def _iban_for_account(account_id: int) -> str:
    with connect() as conn:
        cur = conn.cursor()
        cur.execute("SELECT iban FROM dbo.account WHERE account_id = ?", account_id)
        row = cur.fetchone()
        return str(row[0]) if row else ""


def update_opening(country_id: int, year: int, items: list[dict[str, Any]]) -> None:
    """Upsert opening balances for a country and year.

    Each item: {"category_id": int, "amount": float, "note": str | None}.
    Bank categories are included too: their amount is the initial/opening
    balance recorded here and used by the sheet (see ``balance_sheet``).
    """
    verlies_id = _verlies_id(country_id)
    with connect() as conn:
        cur = conn.cursor()
        for item in items:
            cat_id = int(item["category_id"])
            if cat_id == verlies_id:
                continue  # computed, never stored
            amount = Decimal(str(item.get("amount", 0)))
            note = item.get("note")
            cur.execute(
                """
                IF EXISTS (SELECT 1 FROM dbo.balance_opening
                           WHERE country_id = ? AND category_id = ? AND year = ?)
                    UPDATE dbo.balance_opening
                    SET amount = ?, note = ?
                    WHERE country_id = ? AND category_id = ? AND year = ?
                ELSE
                    INSERT INTO dbo.balance_opening (country_id, category_id, year, amount, note)
                    VALUES (?, ?, ?, ?, ?)
                """,
                country_id, cat_id, year,
                amount, note, country_id, cat_id, year,
                country_id, cat_id, year, amount, note,
            )
        conn.commit()


def generate_spaarmirror(country_id: int, year: int) -> dict[str, Any]:
    """(Re)build the faked spaarrekening mirror journal for a country/year.

    Idempotent: any previously generated mirror rows for the country/year are
    deleted first, then re-derived from the current source rows. This keeps the
    balance sheet correct after bank data is refreshed.
    """
    rows = _spaar_mirror_rows(country_id, year)
    mirror = _country_config(country_id).get("mirror")
    with connect() as conn:
        cur = conn.cursor()
        if mirror:
            cur.execute(
                "DELETE FROM dbo.balance_transaction "
                "WHERE year = ? AND country_id = ? AND category_id = ? "
                "AND description LIKE ? ESCAPE '!'",
                year,
                country_id,
                int(mirror["target_category"]),
                "![" + SPAAR_MARKER[1:] + "%",
            )
        for category_id, booked_on, amount, description in rows:
            cur.execute(
                "INSERT INTO dbo.balance_transaction "
                "(year, country_id, date, category_id, amount, description, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, SYSUTCDATETIME())",
                year,
                country_id,
                booked_on,
                category_id,
                amount,
                description,
            )
        conn.commit()
    return {"ok": True, "year": year, "country_id": country_id, "generated": len(rows)}


def list_journal(country_id: int, year: int) -> list[dict[str, Any]]:
    """All hand-edited journal rows for a country/year (oldest first)."""
    labels = _category_labels(country_id)
    rows: list[dict[str, Any]] = []
    with connect() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT journal_id, date, category_from, category_to, amount, description "
            "FROM dbo.balance_journal WHERE country_id = ? AND year = ? "
            "ORDER BY date, journal_id",
            country_id,
            year,
        )
        for journal_id, date, cat_from, cat_to, amount, desc in cur.fetchall():
            rows.append({
                "journal_id": int(journal_id),
                "year": year,
                "date": str(date),
                "category_from": int(cat_from),
                "category_to": int(cat_to),
                "amount": float(amount),
                "description": str(desc or ""),
                "from_label": labels.get(int(cat_from), f"cat_{cat_from}"),
                "to_label": labels.get(int(cat_to), f"cat_{cat_to}"),
            })
    return rows


def save_journal(country_id: int, year: int, items: list[dict[str, Any]]) -> dict[str, Any]:
    """Full-replace the hand-edited journal for a country/year.

    Each item: {"date", "category_from", "category_to", "amount", "description"}.
    All existing rows for the country/year are deleted first, then the
    submitted set is inserted. Does not touch dbo.balance_transaction (the auto
    spaar-mirror).
    """
    with connect() as conn:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM dbo.balance_journal WHERE country_id = ? AND year = ?",
            country_id,
            year,
        )
        for item in items:
            date = str(item["date"])
            cat_from = int(item["category_from"])
            cat_to = int(item["category_to"])
            amount = Decimal(str(item.get("amount", 0)))
            description = str(item.get("description") or "")[:512]
            cur.execute(
                "INSERT INTO dbo.balance_journal "
                "(year, country_id, date, category_from, category_to, amount, description, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, SYSUTCDATETIME())",
                year, country_id, date, cat_from, cat_to, amount, description,
            )
        conn.commit()
    return {"ok": True, "year": year, "country_id": country_id, "saved": len(items)}
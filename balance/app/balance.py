"""Balance sheet calculation for Beheer (country_id=4).

Reads bank account balances from ``dbo.account`` and non-bank opening balances
from ``dbo.balance_opening``.  The Verlies (loss/profit) post is computed as
the balancing figure: ``total_activa - sum(other passiva)``.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.db import connect

COUNTRY_ID = 4

# category_id → (side, account_id | None)
# side: "activa" or "passiva"
CATEGORY_MAP: dict[int, tuple[str, int | None]] = {
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

VERLIES_ID = 2100

# The checking → spaarrekening pair. Money moves between 1051 (account 18,
# NL34..667) and 1052 via transactions that are invisible on the spaarrekening
# side. We reconstruct them by mirroring the 1051 rows whose description
# contains "spaarrekening", with the sign flipped.
SPAAR_SOURCE_ACCOUNT_ID = 18
SPAAR_SOURCE_CATEGORY = 1051
SPAAR_TARGET_CATEGORY = 1052
SPAAR_KEYWORD = "spaarrekening"
SPAAR_MARKER = "[spaar-mirror]"


def _account_balances() -> dict[int, Decimal]:
    """account_id → balance from dbo.account."""
    with connect() as conn:
        cur = conn.cursor()
        cur.execute("SELECT account_id, balance FROM dbo.account")
        return {int(r[0]): Decimal(str(r[1])) for r in cur.fetchall()}


def _opening_balances(year: int) -> dict[int, Decimal]:
    """category_id → amount from dbo.balance_opening."""
    with connect() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT category_id, amount FROM dbo.balance_opening WHERE year = ?",
            year,
        )
        return {int(r[0]): Decimal(str(r[1])) for r in cur.fetchall()}


def _journal_balances(year: int) -> dict[int, Decimal]:
    """category_id → net sum of dbo.balance_transaction for a year."""
    with connect() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT category_id, SUM(amount) FROM dbo.balance_transaction "
            "WHERE year = ? GROUP BY category_id",
            year,
        )
        return {int(r[0]): Decimal(str(r[1])) for r in cur.fetchall()}


def _spaar_mirror_rows(year: int) -> list[tuple[int, str, Decimal, str]]:
    """Derive the faked spaarrekening (1052) mirror transactions.

    Each 1051 row on the source account whose description contains the
    keyword gives one 1052 journal entry with the sign flipped:
    a transfer out of 1051 ("Naar ...spaarrekening", negative) increases the
    spaarrekening, and a transfer in ("Van ...spaarrekening", positive)
    decreases it.
    """
    rows: list[tuple[int, str, Decimal, str]] = []
    with connect() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT booked_on, amount, description "
            "FROM dbo.transaction_beheer "
            "WHERE year = ? AND account_id = ? "
            "AND LOWER(COALESCE(description, N'')) LIKE ? "
            "ORDER BY booked_on",
            year,
            SPAAR_SOURCE_ACCOUNT_ID,
            f"%{SPAAR_KEYWORD}%",
        )
        for booked_on, amount, description in cur.fetchall():
            d = Decimal(str(amount))
            rows.append(
                (
                    SPAAR_TARGET_CATEGORY,
                    str(booked_on),
                    -d,
                    f"{SPAAR_MARKER} {str(description or '')[:180]}",
                )
            )
    return rows


def _sum_amount(items: list[dict[str, Any]]) -> Decimal:
    return sum(Decimal(str(item["amount"])) for item in items)


def _category_labels() -> dict[int, str]:
    """category_id → label from dbo.dim_category (beheer balance categories)."""
    with connect() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT category_id, label FROM dbo.dim_category "
            "WHERE country_id = ? AND category_id BETWEEN 1000 AND 2999",
            COUNTRY_ID,
        )
        return {int(r[0]): str(r[1]) for r in cur.fetchall()}


def balance_sheet(year: int) -> dict[str, Any]:
    """Return the full balance sheet for a given year."""
    acct = _account_balances()
    opening = _opening_balances(year)
    journal = _journal_balances(year)
    labels = _category_labels()

    activa: list[dict[str, Any]] = []
    passiva: list[dict[str, Any]] = []

    for cat_id in sorted(CATEGORY_MAP):
        side, account_id = CATEGORY_MAP[cat_id]
        label = labels.get(cat_id, f"cat_{cat_id}")

        if cat_id == VERLIES_ID:
            # computed later
            continue

        if account_id is not None:
            amount = acct.get(account_id, Decimal("0"))
            source = f"account:{account_id}"
        else:
            amount = opening.get(cat_id, Decimal("0"))
            source = "opening"
            journal_amount = journal.get(cat_id)
            if journal_amount is not None:
                amount += journal_amount
                source = "opening+journal"

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
        "category_id": VERLIES_ID,
        "code": VERLIES_ID,
        "label": labels.get(VERLIES_ID, "Verlies"),
        "amount": float(verlies_amount),
        "source": "computed",
    })

    total_passiva = total_passiva_others + verlies_amount

    return {
        "year": year,
        "activa": activa,
        "passiva": passiva,
        "total_activa": float(total_activa),
        "total_passiva": float(total_passiva),
        "balanced": total_activa == total_passiva,
    }


def list_years() -> list[int]:
    """Years that have any data in balance_opening."""
    with connect() as conn:
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT year FROM dbo.balance_opening ORDER BY year")
        return [int(r[0]) for r in cur.fetchall()]


def list_categories() -> list[dict[str, Any]]:
    """All balance categories with their account links (if any)."""
    labels = _category_labels()
    acct = _account_balances()
    result = []
    for cat_id in sorted(CATEGORY_MAP):
        side, account_id = CATEGORY_MAP[cat_id]
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


def _iban_for_account(account_id: int) -> str:
    with connect() as conn:
        cur = conn.cursor()
        cur.execute("SELECT iban FROM dbo.account WHERE account_id = ?", account_id)
        row = cur.fetchone()
        return str(row[0]) if row else ""


def update_opening(year: int, items: list[dict[str, Any]]) -> None:
    """Upsert opening balances for a year.

    Each item: {"category_id": int, "amount": float, "note": str | None}.
    Only non-bank categories (account_id is None) may be updated.
    """
    with connect() as conn:
        cur = conn.cursor()
        for item in items:
            cat_id = int(item["category_id"])
            if cat_id == VERLIES_ID:
                continue  # computed, never stored
            _, account_id = CATEGORY_MAP.get(cat_id, (None, None))
            if account_id is not None:
                continue  # bank balance comes from dbo.account
            amount = Decimal(str(item.get("amount", 0)))
            note = item.get("note")
            cur.execute(
                """
                IF EXISTS (SELECT 1 FROM dbo.balance_opening
                           WHERE category_id = ? AND year = ?)
                    UPDATE dbo.balance_opening
                    SET amount = ?, note = ?
                    WHERE category_id = ? AND year = ?
                ELSE
                    INSERT INTO dbo.balance_opening (category_id, year, amount, note)
                    VALUES (?, ?, ?, ?)
                """,
                cat_id, year,
                amount, note, cat_id, year,
                cat_id, year, amount, note,
            )
        conn.commit()


def generate_spaarmirror(year: int) -> dict[str, Any]:
    """(Re)build the faked spaarrekening (1052) mirror journal for a year.

    Idempotent: any previously generated 1052 mirror rows for the year are
    deleted first, then re-derived from the current 1051 source rows. This
    keeps the balance sheet correct after bank data is refreshed.
    """
    rows = _spaar_mirror_rows(year)
    with connect() as conn:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM dbo.balance_transaction "
            "WHERE year = ? AND category_id = ? "
            "AND description LIKE ? ESCAPE '!'",
            year,
            SPAAR_TARGET_CATEGORY,
            "![" + SPAAR_MARKER[1:] + "%",
        )
        for category_id, booked_on, amount, description in rows:
            cur.execute(
                "INSERT INTO dbo.balance_transaction "
                "(year, date, category_id, amount, description, created_at) "
                "VALUES (?, ?, ?, ?, ?, SYSUTCDATETIME())",
                year,
                booked_on,
                category_id,
                amount,
                description,
            )
        conn.commit()
    return {"ok": True, "year": year, "generated": len(rows)}

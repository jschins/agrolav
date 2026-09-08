"""Balance sheet calculation for balance countries (Beheer country_id=4, …).

Each balance country reads bank account balances from ``dbo.account`` (linked
to balance categories through ``dbo.mapping``) and non-bank opening balances
from ``dbo.balance_opening``, plus hand-edited journal rows
(``dbo.balance_journal``) and auto spaar-mirror rows
(``dbo.balance_transaction``).  The Verlies (loss/profit) post is the recorded
result: the sum of the P&L category amounts (``category_id`` 3000-4999) stored
per person in ``dbo.category_total`` for that year.  The Eigen vermogen post is
computed as the balancing figure: ``total_activa - sum(other passiva)``.

The balance tables carry a ``country_id`` so every country keeps its own
opening balances, journal and mirror.  The instance serves the country given
by ``BALANCE_COUNTRY_ID`` (default 4).
"""
from __future__ import annotations

import os
import re
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from app.db import connect
from shared.balance_values import (
    SPAAR_MARKER,
    balance_category_breakdown,
    balance_config,
    category_labels as shared_category_labels,
    category_map as shared_category_map,
    country_has_balance as shared_country_has_balance,
    eigen_vermogen_id as shared_eigen_vermogen_id,
    result_overlay_cents,
    sql_ident,
    verlies_id as shared_verlies_id,
)

_VERLIES_SUFFIX = "Verlies"
_IDENT = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")

_has_balance_cache: dict[int, bool] = {}


def _country_has_balance(country_id: int) -> bool:
    """``dbo.country.has_balance`` for a country (True when the column is missing)."""
    cached = _has_balance_cache.get(country_id)
    if cached is not None:
        return cached
    try:
        with connect() as conn:
            cur = conn.cursor()
            value = shared_country_has_balance(country_id, cur)
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
    return dict(balance_config(country_id))


def _verlies_id(country_id: int) -> int:
    return shared_verlies_id(country_id)


def _balance_id(country_id: int) -> int:
    return shared_eigen_vermogen_id(country_id)


def _sql_ident(text: str) -> str | None:
    return sql_ident(text)


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
        return shared_category_labels(country_id, cur)


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
    with connect() as conn:
        cur = conn.cursor()
        return shared_category_map(country_id, cur)


def _result_overlay(country_id: int, year: int, as_of: str | None = None) -> Decimal:
    """Resultaat effect of the journal rows for categories 3000-4999 (Decimal sum).

    Mirrors the hub matrix overlay so the sheet's Verlies post agrees with the
    client's "Saldo" (kosten minus opbrengsten). Delegates to the shared module.
    With ``as_of`` (YYYY-MM-DD) only rows dated on or before that day are
    included.
    """
    with connect() as conn:
        cur = conn.cursor()
        overlay = result_overlay_cents(country_id, year, cur, as_of=as_of)
    return Decimal(sum(overlay.values())) / 100


def _recorded_result(country_id: int, year: int) -> Decimal:
    """Verlies (resultaat): sum of the P&L category totals (3000-4999).

    Reads the recorded per-person category totals from ``dbo.category_total``
    (consolidated rows with ``bank_id IS NULL``) for the country's persons,
    plus the beheer journal overlay so the sheet matches the client matrix
    "Saldo" (kosten minus opbrengsten). Empty when no totals are recorded (the
    balance post stays out of the sheet's stored passiva until the totals are
    written).
    """
    with connect() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT ROUND(SUM(CAST(ct.amount AS decimal(19,2))), 2)
            FROM dbo.category_total ct
            JOIN dbo.person p ON p.id = ct.person_id
            JOIN dbo.center c ON c.center_id = p.center_id
            WHERE c.country_id = ?
              AND ct.year = ?
              AND ct.bank_id IS NULL
              AND ct.category_id BETWEEN 3000 AND 4999
            """,
            country_id,
            year,
        )
        row = cur.fetchone()
    base = Decimal("0") if row is None or row[0] is None else Decimal(str(row[0]))
    return base + _result_overlay(country_id, year)


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


def balance_country_by_slug(slug: str) -> int | None:
    """Country id for a URL slug (``dbo.country.username``) with balance.

    Only countries flagged ``has_balance = 1`` are considered; any unknown
    or non-balance slug resolves to ``None`` so the route can answer 404.
    """
    slug = (slug or "").strip().lower()
    if not slug:
        return None
    if not _IDENT.match(slug):
        return None
    try:
        with connect() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT country_id FROM dbo.country "
                "WHERE username = ? AND has_balance = 1",
                slug,
            )
            row = cur.fetchone()
    except Exception:
        return None
    return int(row[0]) if row else None


def balance_country_slugs() -> list[str]:
    """Username slugs of every balance country, in ``country_id`` order."""
    try:
        with connect() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT username FROM dbo.country "
                "WHERE has_balance = 1 ORDER BY country_id"
            )
            return [str(r[0]).strip() for r in cur.fetchall() if r[0]]
    except Exception:
        return []


def list_dates(country_id: int, year: int) -> list[str]:
    """Distinct booking dates (YYYY-MM-DD) in the country's transaction table."""
    table = _transaction_table(country_id)
    if table is None:
        return []
    with connect() as conn:
        cur = conn.cursor()
        cur.execute(
            f"SELECT DISTINCT CONVERT(varchar(10), booked_on, 23) "
            f"FROM {table} WHERE year = ? ORDER BY 1",
            year,
        )
        return [str(r[0]) for r in cur.fetchall()]


def _asof_cutoff(country_id: int, year: int, as_of: str | None) -> date | None:
    """Resolve the ``as_of`` selector to a cutoff date.

    ``None``/``""`` means the live, full-year sheet. ``"initial"`` means a
    date strictly before the first booked transaction (the starting sheet).
    Anything else is parsed as YYYY-MM-DD.
    """
    if as_of in (None, ""):
        return None
    if as_of == "initial":
        table = _transaction_table(country_id)
        if table is not None:
            with connect() as conn:
                cur = conn.cursor()
                cur.execute(f"SELECT MIN(booked_on) FROM {table} WHERE year = ?", year)
                row = cur.fetchone()
            if row and row[0] is not None:
                first = row[0]
                if hasattr(first, "date"):
                    first = first.date()
                return first - timedelta(days=1)
        return date(2000, 1, 1)
    try:
        return date.fromisoformat(str(as_of))
    except ValueError:
        return None


def _result_amount(country_id: int, year: int, cutoff: date) -> Decimal:
    """Verlies recomputed from the transaction rows booked on or before cutoff."""
    table = _transaction_table(country_id)
    total = Decimal("0")
    if table is not None:
        with connect() as conn:
            cur = conn.cursor()
            cur.execute(
                f"SELECT category_id, amount FROM {table} "
                "WHERE year = ? AND booked_on <= ?",
                year,
                cutoff.isoformat(),
            )
            for cat, amt in cur.fetchall():
                try:
                    if 3000 <= int(cat) <= 4999:
                        total += Decimal(str(amt))
                except (TypeError, ValueError):
                    continue
    return total + _result_overlay(country_id, year, cutoff.isoformat())


def balance_sheet(country_id: int, year: int, as_of: str | None = None) -> dict[str, Any]:
    """Return the full balance sheet for a given country and year.

    With ``as_of`` ("initial" or YYYY-MM-DD) the Verlies post, the bank
    account balances, and the journal effects are computed up to that day; a
    date before the first transaction yields the starting balance sheet.
    """
    cutoff = _asof_cutoff(country_id, year, as_of)
    if cutoff is None:
        result_amount = _recorded_result(country_id, year)
        result_source = "category_total"
    else:
        result_amount = _result_amount(country_id, year, cutoff)
        result_source = "as_of"
    with connect() as conn:
        cur = conn.cursor()
        breakdown = balance_category_breakdown(country_id, year, cur, as_of=cutoff)
        category_map = shared_category_map(country_id, cur)
    labels = _category_labels(country_id)
    balance_id = _balance_id(country_id)
    result_id = _verlies_id(country_id)

    activa: list[dict[str, Any]] = []
    passiva: list[dict[str, Any]] = []

    for cat_id in sorted(category_map):
        side, account_id = category_map[cat_id]
        label = labels.get(cat_id, f"cat_{cat_id}")

        if cat_id in (balance_id, result_id):
            # computed later
            continue

        cents, source = breakdown.get(cat_id, (0, "opening"))
        amount = cents / 100

        row = {"category_id": cat_id, "code": cat_id, "label": label,
               "amount": float(amount), "source": source}
        if side == "activa":
            activa.append(row)
        else:
            passiva.append(row)

    total_activa = _sum_amount(activa)

    passiva.append({
        "category_id": result_id,
        "code": result_id,
        "label": labels.get(result_id, _VERLIES_SUFFIX),
        "amount": float(result_amount),
        "source": result_source,
    })

    total_passiva_others = _sum_amount(passiva)

    balance_amount = total_activa - total_passiva_others
    passiva.append({
        "category_id": balance_id,
        "code": balance_id,
        "label": labels.get(balance_id, "Eigen vermogen"),
        "amount": float(balance_amount),
        "source": "computed",
    })

    total_passiva = _sum_amount(passiva)

    return {
        "year": year,
        "country_id": country_id,
        "as_of": cutoff.isoformat() if cutoff is not None else None,
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
    Computed posts (Eigen vermogen / Verlies) are never stored, and categories
    with a live account link (bank categories) are skipped too: their amount is
    the live ``dbo.account.balance``, never an opening row in balance_opening.
    """
    balance_id = _balance_id(country_id)
    result_id = _verlies_id(country_id)
    with connect() as conn:
        cur = conn.cursor()
        account_linked = {
            cat_id
            for cat_id, (_side, account_id) in shared_category_map(country_id, cur).items()
            if account_id is not None
        }
        for item in items:
            cat_id = int(item["category_id"])
            if cat_id in (balance_id, result_id) or cat_id in account_linked:
                continue  # computed or live-account categories, never stored
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
"""Balance sheet calculation for balance countries (Beheer country_id=4, …).

Each balance country reads bank account balances from ``dbo.account`` (linked
to balance categories through ``dbo.mapping_banks``) and non-bank opening balances
from ``dbo.balance_opening``, plus hand-edited journal rows
(``dbo.journal``) and auto spaar-mirror rows
(``dbo.transaction_mirror``).  Resultaat R is the sum of P&L category
amounts (``category_id`` 3000-4999) in ``dbo.category_total``.  Passiva 2100
Verlies is that same R.  Eigen vermogen is the plug:
``total_activa - sum(other passiva)``.

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
    CatalogError,
    balance_category_breakdown,
    category_labels as shared_category_labels,
    category_local_codes as shared_category_local_codes,
    category_map as shared_category_map,
    category_roles as shared_category_roles,
    country_has_balance as shared_country_has_balance,
    eigen_vermogen_id as shared_eigen_vermogen_id,
    ensure_category_role_booking_rules,
    is_balance_sheet_code,
    is_journal_forbidden_code,
    require_remainder_row,
    result_overlay_cents,
    spaar_mirror,
    spaar_mirror_posted_amount,
    spaar_source_exclude_clause,
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
    return ids


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
    if not ids:
        raise CatalogError("No country with has_balance = 1")
    return ids[0]


def _verlies_id(country_id: int, cursor: object | None = None) -> int | None:
    if cursor is not None:
        return shared_verlies_id(country_id, cursor)
    with connect() as conn:
        return shared_verlies_id(country_id, conn.cursor())


def _balance_id(country_id: int, cursor: object | None = None) -> int | None:
    if cursor is not None:
        return shared_eigen_vermogen_id(country_id, cursor)
    with connect() as conn:
        return shared_eigen_vermogen_id(country_id, conn.cursor())


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

    Each source-account row whose description contains the keyword gives one
    target-category ``transaction_mirror`` of ``-d`` (d = source bank amount):
    a transfer out (d = -X, X > 0) increases the mirror by X so plug 2000 is still.
    """
    table = _transaction_table(country_id)
    if table is None:
        return []
    rows: list[tuple[int, str, Decimal, str]] = []
    with connect() as conn:
        cur = conn.cursor()
        ensure_category_role_booking_rules(cur)
        mirror = spaar_mirror(country_id, cur)
        if not mirror:
            return []
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
                    spaar_mirror_posted_amount(d),
                    f"{SPAAR_MARKER} {str(description or '')[:180]}",
                )
            )
    return rows


def _sum_amount(items: list[dict[str, Any]]) -> Decimal:
    return sum(Decimal(str(item["amount"])) for item in items)


def _opening_plug_amount(
    cursor: object,
    country_id: int,
    year: int,
    balance_id: int,
    local_code: int,
) -> Decimal:
    """``dbo.balance_opening.amount`` for Eigen vermogen (``equity`` / 2000).

    Crashes when the row is missing or the stored amount is not greater than 0.
    """
    cursor.execute(
        """
        SELECT TOP (1) o.amount
        FROM dbo.balance_opening o
        LEFT JOIN dbo.dim_category d
          ON d.category_id = o.category_id AND d.country_id = o.country_id
        WHERE o.country_id = ? AND o.year = ?
          AND (
            o.category_id IN (?, ?)
            OR d.local_code IN (?, ?)
          )
        """,
        (
            int(country_id),
            int(year),
            int(balance_id),
            int(local_code),
            int(balance_id),
            int(local_code),
        ),
    )
    row = cursor.fetchone()
    if row is None or row[0] is None:
        raise RuntimeError(
            "dbo.balance_opening has no Eigen vermogen amount "
            f"for country_id={country_id} year={year} "
            f"category_id={balance_id} local_code={local_code}"
        )
    amount = Decimal(str(row[0]))
    if amount <= 0:
        raise RuntimeError(
            "dbo.balance_opening Eigen vermogen must be > 0, "
            f"got {amount} for country_id={country_id} year={year} "
            f"category_id={balance_id} local_code={local_code}"
        )
    return amount


def _amounts_equal(left: object, right: object) -> bool:
    """True when both values match at eurocent precision."""
    quantum = Decimal("0.01")
    try:
        return Decimal(str(left)).quantize(quantum) == Decimal(str(right)).quantize(quantum)
    except Exception:
        return False


def _category_labels(country_id: int) -> dict[int, str]:
    """category_id → label from dbo.dim_category (balance categories)."""
    with connect() as conn:
        cur = conn.cursor()
        return shared_category_labels(country_id, cur)


def _category_roles(country_id: int) -> dict[int, str]:
    with connect() as conn:
        cur = conn.cursor()
        ensure_category_role_booking_rules(cur)
        return shared_category_roles(country_id, cur)


def _dim_category_ids(country_id: int) -> set[int]:
    with connect() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT DISTINCT category_id FROM dbo.dim_category "
            "WHERE country_id = ? AND local_code BETWEEN 1000 AND 4999",
            country_id,
        )
        return {int(r[0]) for r in cur.fetchall()}


def _category_ids(country_id: int) -> set[int]:
    return {i for i in _dim_category_ids(country_id) if 1000 <= i <= 4999}


def _category_map(country_id: int) -> dict[int, tuple[str, int | None]]:
    with connect() as conn:
        cur = conn.cursor()
        return shared_category_map(country_id, cur)


def _result_overlay(country_id: int, year: int, as_of: str | None = None) -> Decimal:
    """Resultaat effect of the journal rows for categories 3000-4999 (Decimal sum).

    Mirrors the hub matrix overlay so the sheet's Verlies post agrees with the
    client's "Saldo" (numerical sum of 3000-4999). Delegates to the shared module.
    With ``as_of`` (YYYY-MM-DD) only rows dated on or before that day are
    included.
    """
    with connect() as conn:
        cur = conn.cursor()
        overlay = result_overlay_cents(country_id, year, cur, as_of=as_of)
    return Decimal(sum(overlay.values())) / 100


def _recorded_result(country_id: int, year: int) -> Decimal:
    """Resultaat R: sum of the P&L category totals (3000-4999).

    Reads the recorded per-person category totals from ``dbo.category_total``
    (consolidated rows with ``bank_id IS NULL``) for the country's persons,
    plus the beheer journal overlay so R matches the client matrix "Saldo"
    (numerical sum of 3000-4999; K and O same sign). Passiva 2100 uses this same R.
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


def list_result_rows(country_id: int, year: int) -> list[dict[str, Any]]:
    """Per-category Resultaat rows (3000-4999) for the Excel export.

    Same derivation as ``_recorded_result`` but grouped per category: the
    recorded ``dbo.category_total`` (consolidated, ``bank_id IS NULL``) plus
    the beheer journal/mirror overlay. The grand total is R, equal to passiva
    2100.
    """
    with connect() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT ct.category_id, ROUND(SUM(CAST(ct.amount AS decimal(19, 2))), 2)
            FROM dbo.category_total ct
            JOIN dbo.person p ON p.id = ct.person_id
            JOIN dbo.center c ON c.center_id = p.center_id
            WHERE c.country_id = ?
              AND ct.year = ?
              AND ct.bank_id IS NULL
              AND ct.category_id BETWEEN 3000 AND 4999
            GROUP BY ct.category_id
            """,
            country_id,
            year,
        )
        records = {int(r[0]): Decimal(str(r[1] or 0)) for r in cur.fetchall()}
        overlay = result_overlay_cents(country_id, year, cur)
    labels = _category_labels(country_id)
    combined: dict[int, Decimal] = {}
    for code, amount in records.items():
        combined[code] = combined.get(code, Decimal("0")) + amount
    for code, cents in overlay.items():
        combined[code] = combined.get(code, Decimal("0")) + Decimal(cents) / Decimal(100)
    return [
        {
            "code": code,
            "label": labels.get(code, f"cat_{code}"),
            "amount": float(amount),
        }
        for code, amount in sorted(combined.items())
    ]


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
            exclude_sql, exclude_params = spaar_source_exclude_clause(
                country_id, cursor=cur
            )
            cur.execute(
                f"SELECT category_id, amount FROM {table} t "
                f"WHERE t.year = ? AND t.booked_on <= ?{exclude_sql}",
                year,
                cutoff.isoformat(),
                *exclude_params,
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
        balance_id = _balance_id(country_id, cur)
        result_id = _verlies_id(country_id, cur)
        local_codes = shared_category_local_codes(country_id, cur)
        if balance_id is None:
            raise RuntimeError(
                f"no Eigen vermogen category (category_role=equity) for country_id={country_id}"
            )
        start_plug = _opening_plug_amount(
            cur,
            country_id,
            year,
            balance_id,
            local_codes.get(int(balance_id), int(balance_id)),
        )
    labels = _category_labels(country_id)

    def display_code(cat_id: int | None) -> int | None:
        if cat_id is None:
            return None
        return local_codes.get(int(cat_id), int(cat_id))

    activa: list[dict[str, Any]] = []
    passiva: list[dict[str, Any]] = []

    for cat_id in sorted(category_map):
        side, _account_id = category_map[cat_id]
        local = display_code(cat_id)
        if local is None or not is_balance_sheet_code(local):
            continue
        if side not in ("activa", "passiva"):
            continue
        label = labels.get(cat_id, f"cat_{cat_id}")

        if cat_id in {i for i in (balance_id, result_id) if i is not None}:
            # computed later
            continue

        cents, source = breakdown.get(cat_id, (0, "opening"))
        amount = cents / 100

        row = {
            "category_id": cat_id,
            "code": display_code(cat_id),
            "label": label,
            "amount": float(amount),
            "source": source,
        }
        if balance_id is not None and cat_id == balance_id:
            row["role"] = "equity"
            row["unchanged"] = start_plug is not None and _amounts_equal(
                amount, start_plug
            )
        if side == "activa":
            activa.append(row)
        else:
            passiva.append(row)

    total_activa = _sum_amount(activa)

    if result_id is not None:
        passiva.append({
            "category_id": result_id,
            "code": display_code(result_id),
            "label": labels.get(result_id, _VERLIES_SUFFIX),
            "amount": float(result_amount),
            "source": result_source,
            "role": "profit",
        })

    total_passiva_others = _sum_amount(passiva)

    balance_amount = total_activa - total_passiva_others
    plug_unchanged = _amounts_equal(balance_amount, start_plug)
    passiva.append({
        "category_id": balance_id,
        "code": display_code(balance_id),
        "label": labels.get(balance_id, "Eigen vermogen"),
        "amount": float(balance_amount),
        "source": "computed",
        "unchanged": bool(plug_unchanged),
        "role": "equity",
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
        "plug_debug": {
            "opening": str(start_plug),
            "calculated": str(balance_amount),
            "equal": bool(plug_unchanged),
        },
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


def list_categories(country_id: int) -> dict[str, Any]:
    """Journal-eligible categories, plus remainder ``category_id`` for defaults."""
    labels = _category_labels(country_id)
    roles = _category_roles(country_id)
    acct = _account_balances(country_id)
    category_map = _category_map(country_id)
    ids = _category_ids(country_id)
    with connect() as conn:
        remainder_id, _remainder_code = require_remainder_row(
            country_id, conn.cursor()
        )
    ids.add(int(remainder_id))
    result = []
    for cat_id in sorted(ids):
        if is_journal_forbidden_code(cat_id, roles.get(cat_id)):
            continue
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
    return {"categories": result, "remainder_id": int(remainder_id)}


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
    with connect() as conn:
        cur = conn.cursor()
        balance_id = _balance_id(country_id, cur)
        result_id = _verlies_id(country_id, cur)
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
    with connect() as conn:
        cur = conn.cursor()
        ensure_category_role_booking_rules(cur)
        mirror = spaar_mirror(country_id, cur)
        if mirror:
            cur.execute(
                "DELETE FROM dbo.transaction_mirror "
                "WHERE year = ? AND country_id = ? AND category_id = ? "
                "AND description LIKE ? ESCAPE '!'",
                year,
                country_id,
                int(mirror["target_category"]),
                "![" + SPAAR_MARKER[1:] + "%",
            )
        for category_id, booked_on, amount, description in rows:
            cur.execute(
                "INSERT INTO dbo.transaction_mirror "
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


def list_subadministratie(country_id: int, local_code: int | None = None) -> list[dict[str, Any]]:
    """Rows of dbo.subadministratie for a country (by name), optionally for one local_code."""
    rows: list[dict[str, Any]] = []
    with connect() as conn:
        cur = conn.cursor()
        if local_code is None:
            cur.execute(
                "SELECT local_code, name, amount FROM dbo.subadministratie "
                "WHERE country_id = ? ORDER BY name",
                country_id,
            )
        else:
            cur.execute(
                "SELECT local_code, name, amount FROM dbo.subadministratie "
                "WHERE country_id = ? AND local_code = ? ORDER BY name",
                country_id,
                str(local_code),
            )
        for local_code, name, amount in cur.fetchall():
            rows.append({
                "local_code": int(local_code),
                "name": str(name),
                "amount": float(amount),
            })
    return rows


def list_journal(country_id: int, year: int) -> list[dict[str, Any]]:
    """All hand-edited journal rows for a country/year (oldest first)."""
    labels = _category_labels(country_id)
    rows: list[dict[str, Any]] = []
    with connect() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT journal_id, date, category_from, category_to, amount, description "
            "FROM dbo.journal WHERE country_id = ? AND year = ? "
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
    submitted set is inserted. Does not touch dbo.transaction_mirror (the auto
    spaar-mirror).
    """
    with connect() as conn:
        cur = conn.cursor()
        ensure_category_role_booking_rules(cur)
        roles = shared_category_roles(country_id, cur)
        parsed: list[tuple[str, int, int, Decimal, str]] = []
        for item in items:
            date = str(item["date"])
            cat_from = int(item["category_from"])
            cat_to = int(item["category_to"])
            if is_journal_forbidden_code(cat_from, roles.get(cat_from)):
                raise ValueError(f"Category {cat_from} cannot be used in a journal")
            if is_journal_forbidden_code(cat_to, roles.get(cat_to)):
                raise ValueError(f"Category {cat_to} cannot be used in a journal")
            amount = Decimal(str(item.get("amount", 0)))
            description = str(item.get("description") or "")[:512]
            parsed.append((date, cat_from, cat_to, amount, description))
        cur.execute(
            "DELETE FROM dbo.journal WHERE country_id = ? AND year = ?",
            country_id,
            year,
        )
        for date, cat_from, cat_to, amount, description in parsed:
            cur.execute(
                "INSERT INTO dbo.journal "
                "(year, country_id, date, category_from, category_to, amount, description, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, SYSUTCDATETIME())",
                year, country_id, date, cat_from, cat_to, amount, description,
            )
        conn.commit()
    return {"ok": True, "year": year, "country_id": country_id, "saved": len(parsed)}
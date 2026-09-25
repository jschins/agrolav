"""Balance sheet calculation for balance countries (Beheer country_id=4, …).

Each balance country reads bank account balances from ``dbo.account`` (linked
to balance categories through ``dbo.mapping_banks``) and non-bank opening balances
from ``dbo.balance_opening``, plus hand-edited journal rows
(``dbo.journal``) and auto spaar-mirror rows
(``dbo.transaction_mirror``).  Resultaat R is the sum of P&L category
amounts (``category_id`` 3000-4999) in ``dbo.category_total``.  Passiva 2100
Verlies is that same R.  Eigen vermogen is the plug:
``total_activa - sum(other passiva)``.

Each country is reached through ``dbo.dim_category``. The instance serves
the country given by ``BALANCE_COUNTRY_ID`` (default 4).
"""
from __future__ import annotations

import os
import re
import unicodedata
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
    infer_side,
    is_balance_sheet_code,
    is_journal_forbidden_code,
    apply_afschrijvingen,
    afschrijving_like_pattern,
    AFSCHRIJVING_MARKER,
    require_remainder_row,
    recorded_resultaat_totals,
    result_overlay_cents,
    rebuild_spaar_mirror_rows,
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
    One pair per source/mirror in the country (Instudo: one spaar per center).
    """
    from shared.balance_values import spaar_mirrors

    table = _transaction_table(country_id)
    if table is None:
        return []
    rows: list[tuple[int, str, Decimal, str]] = []
    with connect() as conn:
        cur = conn.cursor()
        ensure_category_role_booking_rules(cur)
        for mirror in spaar_mirrors(country_id, cur):
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
        JOIN dbo.dim_category d ON d.category_id = o.category_id
        WHERE d.country_id = ? AND o.year = ?
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
            "WHERE country_id = ? AND (local_code = 1099 OR local_code BETWEEN 1000 AND 4999)",
            country_id,
        )
        return {int(r[0]) for r in cur.fetchall()}


def _category_ids(country_id: int) -> set[int]:
    """All booking ``category_id``s (local_code 1000–4999), including Instudo ids."""
    return _dim_category_ids(country_id)


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


def list_result_rows(country_id: int, year: int) -> list[dict[str, Any]]:
    """Per-category Resultaat rows (3000-4999) for the Excel export.

    Same derivation as ``_recorded_result`` but grouped per category: the
    recorded ``dbo.category_total`` (consolidated, ``bank_id IS NULL``) plus
    the beheer journal/mirror overlay. The grand total is R, equal to passiva
    2100.
    """
    with connect() as conn:
        cur = conn.cursor()
        records = recorded_resultaat_totals(country_id, year, cur)
        overlay = result_overlay_cents(country_id, year, cur)
        local_codes = shared_category_local_codes(country_id, cur)
    labels = _category_labels(country_id)
    combined: dict[int, Decimal] = {}
    for code, amount in records.items():
        combined[code] = combined.get(code, Decimal("0")) + amount
    for code, cents in overlay.items():
        combined[code] = combined.get(code, Decimal("0")) + Decimal(cents) / Decimal(100)
    return [
        {
            "code": local_codes.get(code, code),
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


_COLOR_CONVENTION_NL = """<p><strong style="color:#15803d">Groen onderlijnde bedragen</strong> zijn genomen van een subadministratie</p>
<p><strong style="color:#2563eb">Blauw onderlijnde bedragen</strong> zijn genomen van zowel handmatige als automatische journaalposten</p>
<p><strong style="font-size:calc(1em + 2pt)">Legenda</strong></p>
<p>Handmatige journaalposten betreffen vaste bedragen</p>
<p>Automatische journaalposten betreffen percentages van</p>
<ul>
<li>ofwel de actuele waarde van een grootboekcategorie (vlag op 1)</li>
<li>ofwel de som van alle op die grootboekcategorie in dit jaar geboekte transacties (vlag op 0)</li>
</ul>
<p>Het onderscheid in de vlaggen maakt het mogelijk om het eerste jaar meer af te schrijven dan in latere jaren.</p>
<p>Handmatige en automatische journaalposten zijn alleen zichtbaar in de balans (blauw onderlijnde bedragen)</p>
<p>Bankafschriften zijn alleen zichtbaar in de resultaten (zwarte bedragen, in tegenstelling tot grijze)</p>
<p>Een subadministratie houdt bij op welke wijze een grootboekcategorie is opgebouwd; dit is typisch het geval voor particuliere crediteuren en debiteuren (waarvoor het immers niet zinvol is om eenieder van een eigen grootboekcategorie te voorzien)</p>"""

_COLOR_CONVENTION_EN = """<p><strong style="color:#15803d">Green underlined amounts</strong> are taken from a sub-ledger.</p>
<p><strong style="color:#2563eb">Blue underlined amounts</strong> are taken from both manual and automatic journal entries.</p>
<p><strong style="font-size:calc(1em + 2pt)">Legend</strong></p>
<p>Manual journal entries are fixed amounts.</p>
<p>Automatic journal entries are percentages of</p>
<ul>
<li>either the current value of a ledger category (flag set to 1)</li>
<li>or the sum of all transactions booked on that ledger category in this year (flag set to 0)</li>
</ul>
<p>The distinction between the flags makes it possible to depreciate more in the first year than in later years.</p>
<p>Manual and automatic journal entries are visible only on the balance sheet (blue underlined amounts).</p>
<p>Bank statements are visible only in the results (black amounts, as opposed to grey ones).</p>
<p>A sub-ledger records how a ledger category is built up; this is typically the case for private creditors and debtors (for whom it is not useful to give each one a ledger category of their own).</p>"""


def color_convention(country_id: int) -> dict[str, str]:
    """Title and body for the sheet color-convention note, in the country language."""
    title = "Kleurconventie"
    body = _COLOR_CONVENTION_NL
    close = "Sluiten"
    try:
        with connect() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT language_id FROM dbo.country WHERE country_id = ?",
                int(country_id),
            )
            row = cur.fetchone()
            lid = int(row[0]) if row and row[0] is not None else 2
            if lid < 1:
                lid = 1
            cur.execute(
                """
                SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_SCHEMA = N'dbo' AND TABLE_NAME = N'language'
                  AND COLUMN_NAME = ?
                """,
                f"term_lang{lid}",
            )
            if cur.fetchone() is None:
                lid = 1
            col = f"term_lang{lid}"
            cur.execute(
                f"SELECT {col} FROM dbo.language WHERE term_lang1 = ?",
                "Color convention",
            )
            found = cur.fetchone()
            if found and str(found[0] or "").strip():
                title = str(found[0]).strip()
            elif lid == 1:
                title = "Color convention"
            cur.execute(
                f"SELECT {col} FROM dbo.language_long WHERE term_key = ?",
                "color convention",
            )
            found = cur.fetchone()
            if found and str(found[0] or "").strip():
                body = str(found[0]).strip()
            elif lid == 1:
                body = _COLOR_CONVENTION_EN
            cur.execute(
                f"SELECT {col} FROM dbo.language WHERE term_lang1 = ?",
                "Close",
            )
            found = cur.fetchone()
            if found and str(found[0] or "").strip():
                close = str(found[0]).strip()
            elif lid == 1:
                close = "Close"
    except Exception:  # noqa: BLE001
        pass
    return {"title": title, "body": body, "close": close}


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


def _result_amount(country_id: int, year: int, cutoff: date | None) -> Decimal:
    """Verlies from the transaction rows.

    ``cutoff`` keeps bookings and journals on or before that day. ``None`` is
    the whole year (Actueel). Source-account spaarrekening rows are left out,
    same as on a chosen date. ``dbo.category_total`` is not read: that snapshot
    still holds those rows from before the source/mirror pair existed.
    """
    table = _transaction_table(country_id)
    total = Decimal("0")
    if table is not None:
        with connect() as conn:
            cur = conn.cursor()
            exclude_sql, exclude_params = spaar_source_exclude_clause(
                country_id, cursor=cur
            )
            sql = (
                f"SELECT t.amount FROM {table} t "
                "JOIN dbo.dim_category d ON d.category_id = t.category_id "
                "AND d.country_id = ? "
                "WHERE t.year = ? "
                "AND d.local_code BETWEEN 3000 AND 4999"
                f"{exclude_sql}"
            )
            params: list[object] = [country_id, year, *exclude_params]
            if cutoff is not None:
                sql += " AND t.booked_on <= ?"
                params.append(cutoff.isoformat())
            cur.execute(sql, *params)
            for (amt,) in cur.fetchall():
                try:
                    total += Decimal(str(amt))
                except (TypeError, ValueError):
                    continue
    overlay_as_of = cutoff.isoformat() if cutoff is not None else None
    return total + _result_overlay(country_id, year, overlay_as_of)


def balance_sheet(country_id: int, year: int, as_of: str | None = None) -> dict[str, Any]:
    """Return the full balance sheet for a given country and year.

    With ``as_of`` ("initial" or YYYY-MM-DD) the Verlies post, the bank
    account balances, and the journal effects are computed up to that day; a
    date before the first transaction yields the starting balance sheet.
    """
    with connect() as conn:
        cur = conn.cursor()
        apply_afschrijvingen(country_id, cur)
        conn.commit()
    cutoff = _asof_cutoff(country_id, year, as_of)
    result_amount = _result_amount(country_id, year, cutoff)
    result_source = "as_of" if cutoff is not None else "transactions"
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
        "subadministratie": list_subadministratie_sheet(country_id),
        "afschrijvingen": list_afschrijvingen(country_id, year),
    }


def list_years(country_id: int) -> list[int]:
    """Years that have any data in balance_opening for this country."""
    with connect() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT DISTINCT o.year FROM dbo.balance_opening o "
            "JOIN dbo.dim_category d ON d.category_id = o.category_id "
            "WHERE d.country_id = ? ORDER BY o.year",
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
        cur = conn.cursor()
        remainder_id, _remainder_code = require_remainder_row(country_id, cur)
        local_codes = shared_category_local_codes(country_id, cur)
    ids.add(int(remainder_id))
    result = []
    for cat_id in sorted(ids, key=lambda i: local_codes.get(i, i)):
        local = int(local_codes.get(cat_id, cat_id))
        if is_journal_forbidden_code(local, roles.get(cat_id)):
            continue
        side, account_id = category_map.get(cat_id, (infer_side(local), None))
        row: dict[str, Any] = {
            "category_id": cat_id,
            "code": local,
            "label": labels.get(cat_id, f"cat_{local}"),
            "side": side,
            "account_id": account_id,
        }
        if account_id is not None:
            row["iban"] = _iban_for_account(account_id)
            row["account_balance"] = float(acct.get(account_id, Decimal("0")))
        result.append(row)
    return {"categories": result, "remainder_id": int(remainder_id)}


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


def generate_spaarmirror(country_id: int, year: int) -> dict[str, Any]:
    """(Re)build the faked spaarrekening mirror journal for a country/year.

    Idempotent: any previously generated mirror rows for the country/year are
    deleted first, then re-derived from the current source rows. Writes one
    ``[spaar-mirror]`` row per source-account keyword booking, on every
    source/mirror pair (Instudo: both spaarrekeningen).
    """
    with connect() as conn:
        cur = conn.cursor()
        ensure_category_role_booking_rules(cur)
        generated = rebuild_spaar_mirror_rows(country_id, year, cur)
        conn.commit()
    return {"ok": True, "year": year, "country_id": country_id, "generated": generated}


_NAME_PARTICLES = frozenset({"ten", "te", "van", "den", "op", "de"})


def subadministratie_name(raw: object) -> str:
    """Normalize a ``dbo.subadministratie`` name.

    Lower case, no punctuation. One initial, then one surname.
    A word of two or three letters is initials, split into letters, unless
    that would leave no surname. Several surnames keep the first.
    Prefixes ten, te, van, den, op and de are always dropped.
    Only the first initial is kept.
    """
    text = re.sub(r"[^\w\s]", " ", str(raw or "").casefold(), flags=re.UNICODE)
    text = text.replace("_", " ")
    tokens = [
        part
        for part in text.replace("_", " ").split()
        if part and part not in _NAME_PARTICLES
    ]
    if not tokens:
        return ""
    surnames = [part for part in tokens if len(part) >= 4]
    if surnames:
        surname = surnames[0]
        initial_words = [part for part in tokens if len(part) <= 3]
    else:
        surname = tokens[-1]
        initial_words = tokens[:-1]
    letters: list[str] = []
    for part in initial_words:
        letters.extend(part)
    if not letters:
        return surname
    return f"{letters[0]} {surname}"


def _fold_letters(text: str) -> str:
    """ó → o, í → i, and the same for every other accented letter."""
    stripped = unicodedata.normalize("NFD", text)
    return "".join(ch for ch in stripped if unicodedata.category(ch) != "Mn")


def _person_initial_surname(name: str) -> tuple[str, str]:
    parts = name.split()
    if len(parts) == 2 and len(parts[0]) == 1:
        return parts[0], parts[1]
    return "", name


def _merge_subadministratie_persons(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Same surname with no initial is the first person who has one.

    Different initials stay different persons. A bare surname is added to the
    first matching person in the given order. Accents are ignored: ó is o,
    í is i.
    """
    grouped: dict[int, list[dict[str, Any]]] = {}
    codes: list[int] = []
    for row in rows:
        code = int(row["local_code"])
        if code not in grouped:
            codes.append(code)
            grouped[code] = []
        grouped[code].append(row)
    merged: list[dict[str, Any]] = []
    for code in codes:
        by_surname: dict[str, list[tuple[str, float, str]]] = {}
        surnames: list[str] = []
        for row in grouped[code]:
            label = str(row["name"])
            initial, surname = _person_initial_surname(label)
            key_surname = _fold_letters(surname)
            if key_surname not in by_surname:
                surnames.append(key_surname)
                by_surname[key_surname] = []
            by_surname[key_surname].append((initial, float(row["amount"]), label))
        for surname in surnames:
            items = by_surname[surname]
            first = next(
                (_fold_letters(initial) for initial, _amount, _label in items if initial),
                "",
            )
            totals: dict[str, float] = {}
            labels: dict[str, str] = {}
            locked: dict[str, bool] = {}
            order: list[str] = []
            for initial, amount, label in items:
                folded = _fold_letters(initial)
                key = first if (not folded and first) else folded
                if key not in totals:
                    order.append(key)
                    totals[key] = 0.0
                if initial and not locked.get(key):
                    labels[key] = label
                    locked[key] = True
                elif key not in labels:
                    labels[key] = label
                totals[key] += amount
            for key in order:
                merged.append({
                    "local_code": code,
                    "name": labels[key],
                    "amount": totals[key],
                })
    return merged


def list_subadministratie_sheet(country_id: int) -> dict[str, Any]:
    """Clickable local_codes and rows from ``dbo.subadministratie`` (no hardcoded codes)."""
    rows = list_subadministratie(country_id)
    codes = sorted({int(r["local_code"]) for r in rows})
    return {"local_codes": codes, "rows": rows}


def list_subadministratie(country_id: int, local_code: int | None = None) -> list[dict[str, Any]]:
    """Rows of dbo.subadministratie for a country (by name), optionally for one local_code."""
    rows: list[dict[str, Any]] = []
    with connect() as conn:
        cur = conn.cursor()
        try:
            cur.execute(
                "SELECT local_code, name, amount FROM dbo.subadministratie "
                "WHERE country_id = ? ORDER BY name",
                int(country_id),
            )
        except Exception as exc:
            if "42S02" in str(exc) or "Invalid object" in str(exc):
                return []
            raise
        wanted = None if local_code is None else int(local_code)
        for code, name, amount in cur.fetchall():
            try:
                found = int(code)
            except (TypeError, ValueError):
                continue
            if wanted is not None and found != wanted:
                continue
            rows.append({
                "local_code": found,
                "name": subadministratie_name(name),
                "amount": float(amount),
            })
    return _merge_subadministratie_persons(rows)


def _transaction_person_name(description: str) -> str:
    """Extract the person name from a "Naam: X Omschrijving: ..." description."""
    text = (description or "").strip()
    if not text:
        return ""
    _, _, rest = text.partition("Naam:")
    if rest:
        name = rest.split("Omschrijving:", 1)[0].strip()
        if name:
            return name
    return text


def list_category_transactions(
    country_id: int,
    local_code: int,
    year: int,
    as_of: str | None = None,
) -> list[dict[str, Any]]:
    """``dbo.transaction_{country}`` rows for a local_code/year on/before ``as_of`` (oldest first).

    Mirrors the sheet's ``as_of`` semantics (via ``_asof_cutoff``): ``None`` is
    the full year, ``"initial"`` is the starting sheet (before any transaction),
    anything else is a YYYY-MM-DD cutoff.
    """
    table = _transaction_table(country_id)
    if table is None:
        return []
    cutoff = _asof_cutoff(country_id, year, as_of)
    rows: list[dict[str, Any]] = []
    with connect() as conn:
        cur = conn.cursor()
        sql = (
            f"SELECT t.description, t.counterparty_name, t.amount "
            f"FROM {table} t "
            f"JOIN dbo.dim_category c ON c.category_id = t.category_id "
            f"WHERE c.country_id = ? AND c.local_code = ? AND t.year = ?"
        )
        params: list[object] = [country_id, int(local_code), year]
        if cutoff is not None:
            sql += " AND t.booked_on <= ?"
            params.append(cutoff.isoformat())
        sql += " ORDER BY t.booked_on"
        cur.execute(sql, *params)
        for description, counterparty_name, amount in cur.fetchall():
            name = _transaction_person_name(
                description or str(counterparty_name or "")
            )
            rows.append({
                "name": name or "Onbekend",
                "amount": float(amount),
            })
    return rows


def post_popup(
    country_id: int,
    year: int,
    local_code: int,
    as_of: str | None = None,
) -> dict[str, Any]:
    """Journal rows (blue) and ``dbo.subadministratie`` rows (green) for one code."""
    code = int(local_code)
    names = list_subadministratie(country_id, code)
    by_name: dict[str, float] = {}
    for row in names:
        key = str(row["name"])
        by_name[key] = by_name.get(key, 0.0) + float(row["amount"])
    people = [
        {"local_code": code, "name": name, "amount": amount}
        for name, amount in sorted(by_name.items(), key=lambda item: item[0])
    ]
    journals = [
        row
        for row in list_afschrijvingen(country_id, year)["journals"]
        if int(row["category_from"]) == code
    ]
    return {
        "local_code": code,
        "people": people,
        "journals": journals,
    }


def list_afschrijvingen(country_id: int, year: int) -> dict[str, Any]:
    """Every ``dbo.journal`` row for the country and year.

    ``from_codes`` are the local codes on ``category_from``. Those amounts
    are the blue links on the sheet. ``dbo.afschrijvingen`` is not read here.
    """
    journals: list[dict[str, Any]] = []
    labels = _category_labels(country_id)
    with connect() as conn:
        cur = conn.cursor()
        cur.execute("SELECT OBJECT_ID(N'dbo.journal', N'U')")
        row = cur.fetchone()
        if row is None or row[0] is None:
            return {"from_codes": [], "journals": []}
        local_codes = shared_category_local_codes(country_id, cur)
        cur.execute(
            "SELECT j.journal_id, j.date, j.category_from, j.category_to, j.amount, j.description "
            "FROM dbo.journal j "
            "JOIN dbo.dim_category d ON d.category_id = j.category_from "
            "WHERE d.country_id = ? AND j.year = ? "
            "ORDER BY j.date, j.journal_id",
            country_id,
            year,
        )
        for journal_id, date, cat_from, cat_to, amount, desc in cur.fetchall():
            src, dst = int(cat_from), int(cat_to)
            journals.append({
                "journal_id": int(journal_id),
                "date": str(date),
                "category_from": int(local_codes.get(src, src)),
                "category_to": int(local_codes.get(dst, dst)),
                "from_label": labels.get(src, f"cat_{src}"),
                "to_label": labels.get(dst, f"cat_{dst}"),
                "amount": float(amount),
                "description": str(desc or ""),
            })
    from_codes = sorted({int(row["category_from"]) for row in journals})
    return {"from_codes": from_codes, "journals": journals}


def _afschrijving_category_options(country_id: int) -> list[dict[str, Any]]:
    """local_code options 1000-4999 for the automatic-journal editor."""
    labels = _category_labels(country_id)
    with connect() as conn:
        cur = conn.cursor()
        codes = shared_category_local_codes(country_id, cur)
        roles = shared_category_roles(country_id, cur)
    out: list[dict[str, Any]] = []
    for cat_id, local in codes.items():
        try:
            code = int(local)
        except (TypeError, ValueError):
            continue
        if code < 1000 or code > 4999:
            continue
        if is_journal_forbidden_code(int(cat_id), roles.get(int(cat_id))):
            continue
        out.append({
            "local_code": code,
            "label": labels.get(int(cat_id), f"cat_{code}"),
            "side": infer_side(code),
        })
    out.sort(key=lambda row: int(row["local_code"]))
    return out


def list_afschrijvingen_rules(country_id: int) -> dict[str, Any]:
    """Rows of ``dbo.afschrijvingen`` for a country, plus category options."""
    categories = _afschrijving_category_options(country_id)
    rows: list[dict[str, Any]] = []
    with connect() as conn:
        cur = conn.cursor()
        try:
            cur.execute(
                "SELECT a.id, a.role, a.fraction, dv.local_code, dn.local_code "
                "FROM dbo.afschrijvingen a "
                "JOIN dbo.dim_category dv ON dv.category_id = a.category_id_van "
                "JOIN dbo.dim_category dn ON dn.category_id = a.category_id_naar "
                "WHERE dv.country_id = ? AND dn.country_id = ? "
                "ORDER BY a.id",
                int(country_id),
                int(country_id),
            )
        except Exception as exc:
            if "42S02" in str(exc) or "Invalid object" in str(exc):
                return {"categories": categories, "rows": []}
            raise
        for rule_id, role, fraction, van, naar in cur.fetchall():
            rows.append({
                "id": int(rule_id),
                "role": 1 if role in (1, True) else 0,
                "fraction": float(fraction),
                "local_code_van": int(van),
                "local_code_naar": int(naar),
            })
    return {"categories": categories, "rows": rows}


def save_afschrijvingen_rules(
    country_id: int, items: list[dict[str, Any]]
) -> dict[str, Any]:
    """Replace ``dbo.afschrijvingen`` for a country and rebuild those journals."""
    parsed: list[tuple[int, Decimal, int, int]] = []
    for item in items:
        parsed.append((
            1 if item.get("role", 1) in (1, True, "1") else 0,
            Decimal(str(item.get("fraction") or 0)),
            int(item["local_code_van"]),
            int(item["local_code_naar"]),
        ))
    with connect() as conn:
        cur = conn.cursor()
        cur.execute("SELECT OBJECT_ID(N'dbo.afschrijvingen', N'U')")
        found = cur.fetchone()
        if found is None or found[0] is None:
            raise ValueError("dbo.afschrijvingen is missing")
        cur.execute(
            "SELECT local_code, category_id FROM dbo.dim_category WHERE country_id = ?",
            int(country_id),
        )
        local_to_id = {
            int(local): int(cat)
            for local, cat in cur.fetchall()
            if local is not None and cat is not None
        }
        missing = [
            code
            for _role, _fraction, van, naar in parsed
            for code in (van, naar)
            if code not in local_to_id
        ]
        if missing:
            raise ValueError(
                "unknown local_code for this country: "
                + ", ".join(str(code) for code in missing)
            )
        cur.execute(
            "DELETE a FROM dbo.afschrijvingen a "
            "JOIN dbo.dim_category d ON d.category_id = a.category_id_van "
            "WHERE d.country_id = ?",
            int(country_id),
        )
        for role, fraction, van, naar in parsed:
            cur.execute(
                "INSERT INTO dbo.afschrijvingen "
                "(role, fraction, category_id_van, category_id_naar) "
                "VALUES (?, ?, ?, ?)",
                role,
                fraction,
                local_to_id[van],
                local_to_id[naar],
            )
        apply_afschrijvingen(int(country_id), cur)
        conn.commit()
    return {
        "ok": True,
        "country_id": int(country_id),
        "saved": len(parsed),
    }


def list_journal(country_id: int, year: int) -> list[dict[str, Any]]:
    """All hand-edited journal rows for a country/year (oldest first)."""
    labels = _category_labels(country_id)
    rows: list[dict[str, Any]] = []
    with connect() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT j.journal_id, j.date, j.category_from, j.category_to, j.amount, j.description "
            "FROM dbo.journal j "
            "JOIN dbo.dim_category d ON d.category_id = j.category_from "
            "WHERE d.country_id = ? AND j.year = ? "
            "ORDER BY j.date, j.journal_id",
            country_id,
            year,
        )
        for journal_id, date, cat_from, cat_to, amount, desc in cur.fetchall():
            if str(desc or "").startswith(AFSCHRIJVING_MARKER):
                continue
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
            "DELETE j FROM dbo.journal j "
            "JOIN dbo.dim_category d ON d.category_id = j.category_from "
            "WHERE d.country_id = ? AND j.year = ? "
            "AND j.description NOT LIKE ? ESCAPE '!'",
            country_id,
            year,
            afschrijving_like_pattern(),
        )
        for date, cat_from, cat_to, amount, description in parsed:
            cur.execute(
                "INSERT INTO dbo.journal "
                "(year, date, category_from, category_to, amount, description, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, SYSUTCDATETIME())",
                year, date, cat_from, cat_to, amount, description,
            )
        apply_afschrijvingen(country_id, cur)
        conn.commit()
    return {"ok": True, "year": year, "country_id": country_id, "saved": len(parsed)}
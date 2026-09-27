"""Profit/loss sheet for port 8500.

Same two-column layout as the balance sheet, but local codes 3000–4999
(kosten / opbrengsten) and amounts limited to the login that opened the page.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from shared.balance_values import category_labels, result_overlay_cents, sql_ident

from app.db import connect


def country_id_for_slug(slug: str) -> int | None:
    """``dbo.country.country_id`` for a username, or ``None`` when unknown."""
    name = str(slug or "").strip()
    if not name:
        return None
    with connect() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT country_id FROM dbo.country "
            "WHERE username = ? COLLATE Latin1_General_CI_AI",
            name,
        )
        row = cur.fetchone()
    if not row or row[0] is None:
        return None
    return int(row[0])


def country_title(country_id: int) -> str:
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


def _transaction_table(country_id: int) -> str | None:
    with connect() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT username FROM dbo.country WHERE country_id = ?",
            country_id,
        )
        row = cur.fetchone()
    if not row:
        return None
    username = str(row[0] or "").strip().lower()
    folder = "uk" if username in ("uk", "united_kingdom") else str(row[0] or "").strip()
    ident = sql_ident(folder)
    if not ident:
        return None
    table = f"dbo.transaction_{ident}"
    with connect() as conn:
        cur = conn.cursor()
        cur.execute("SELECT OBJECT_ID(?, N'U')", table)
        if cur.fetchone()[0] is None:
            return None
    return table


def _scope_sql(person: str, center: str, account: str) -> tuple[str, list[object]]:
    clauses: list[str] = []
    params: list[object] = []
    if center:
        clauses.append(" AND n.username = ? COLLATE Latin1_General_CI_AI")
        params.append(center)
    if person:
        clauses.append(" AND p.username = ? COLLATE Latin1_General_CI_AI")
        params.append(person)
    if account:
        clauses.append(" AND REPLACE(UPPER(a.iban), ' ', '') = ?")
        params.append(account)
    return "".join(clauses), params


def _categories(country_id: int) -> list[tuple[int, int, str]]:
    with connect() as conn:
        cur = conn.cursor()
        labels = category_labels(country_id, cur)
        cur.execute(
            "SELECT category_id, local_code, label FROM dbo.dim_category "
            "WHERE country_id = ? AND local_code BETWEEN 3000 AND 4999 "
            "ORDER BY local_code, category_id",
            country_id,
        )
        rows: list[tuple[int, int, str]] = []
        for cat_id, local_code, label in cur.fetchall():
            if cat_id is None or local_code is None:
                continue
            cid = int(cat_id)
            rows.append((cid, int(local_code), labels.get(cid) or str(label or "")))
    return rows


def _amounts(
    country_id: int,
    year: int,
    *,
    person: str,
    center: str,
    account: str,
    cutoff: date | None,
) -> dict[int, Decimal]:
    table = _transaction_table(country_id)
    totals: dict[int, Decimal] = {}
    if table is not None:
        scope_sql, scope_params = _scope_sql(person, center, account)
        sql = (
            f"SELECT t.category_id, SUM(t.amount) "
            f"FROM {table} t "
            "JOIN dbo.person p ON p.id = t.person_id "
            "JOIN dbo.center n ON n.center_id = p.center_id "
            "JOIN dbo.dim_category d ON d.category_id = t.category_id "
            "AND d.country_id = ? "
            "LEFT JOIN dbo.account a ON a.account_id = t.account_id "
            "WHERE n.country_id = ? AND t.year = ? "
            "AND d.local_code BETWEEN 3000 AND 4999"
            f"{scope_sql}"
        )
        params: list[object] = [country_id, country_id, year, *scope_params]
        if cutoff is not None:
            sql += " AND t.booked_on <= ?"
            params.append(cutoff.isoformat())
        sql += " GROUP BY t.category_id"
        with connect() as conn:
            cur = conn.cursor()
            cur.execute(sql, *params)
            for cat_id, amount in cur.fetchall():
                if cat_id is None or amount is None:
                    continue
                try:
                    totals[int(cat_id)] = Decimal(str(amount))
                except (TypeError, ValueError):
                    continue
    if not person and not center and not account:
        as_of = cutoff.isoformat() if cutoff is not None else None
        with connect() as conn:
            cur = conn.cursor()
            overlay = result_overlay_cents(country_id, year, cur, as_of=as_of)
        for cat_id, cents in overlay.items():
            totals[int(cat_id)] = totals.get(int(cat_id), Decimal("0")) + (
                Decimal(int(cents)) / Decimal(100)
            )
    return totals


def _first_booked(
    country_id: int,
    year: int,
    *,
    person: str,
    center: str,
    account: str,
) -> date | None:
    table = _transaction_table(country_id)
    if table is None:
        return None
    scope_sql, scope_params = _scope_sql(person, center, account)
    sql = (
        f"SELECT MIN(t.booked_on) FROM {table} t "
        "JOIN dbo.person p ON p.id = t.person_id "
        "JOIN dbo.center n ON n.center_id = p.center_id "
        "JOIN dbo.dim_category d ON d.category_id = t.category_id "
        "AND d.country_id = ? "
        "LEFT JOIN dbo.account a ON a.account_id = t.account_id "
        "WHERE n.country_id = ? AND t.year = ? "
        "AND d.local_code BETWEEN 3000 AND 4999"
        f"{scope_sql}"
    )
    params: list[object] = [country_id, country_id, year, *scope_params]
    with connect() as conn:
        cur = conn.cursor()
        cur.execute(sql, *params)
        row = cur.fetchone()
    if not row or row[0] is None:
        return None
    first = row[0]
    if hasattr(first, "date"):
        first = first.date()
    return first


def _cutoff(
    country_id: int,
    year: int,
    as_of: str | None,
    *,
    person: str,
    center: str,
    account: str,
) -> date | None:
    if as_of in (None, ""):
        return None
    if as_of == "initial":
        first = _first_booked(
            country_id, year, person=person, center=center, account=account
        )
        if first is None:
            return date(2000, 1, 1)
        return first - timedelta(days=1)
    try:
        return date.fromisoformat(str(as_of))
    except ValueError:
        return None


def list_years(
    country_id: int,
    *,
    person: str = "",
    center: str = "",
    account: str = "",
) -> list[int]:
    table = _transaction_table(country_id)
    if table is None:
        return [date.today().year]
    scope_sql, scope_params = _scope_sql(person, center, account)
    sql = (
        f"SELECT DISTINCT t.year FROM {table} t "
        "JOIN dbo.person p ON p.id = t.person_id "
        "JOIN dbo.center n ON n.center_id = p.center_id "
        "LEFT JOIN dbo.account a ON a.account_id = t.account_id "
        "WHERE n.country_id = ?"
        f"{scope_sql} ORDER BY t.year"
    )
    with connect() as conn:
        cur = conn.cursor()
        cur.execute(sql, country_id, *scope_params)
        years = [int(r[0]) for r in cur.fetchall() if r[0] is not None]
    return years or [date.today().year]


def list_dates(
    country_id: int,
    year: int,
    *,
    person: str = "",
    center: str = "",
    account: str = "",
) -> list[str]:
    table = _transaction_table(country_id)
    if table is None:
        return []
    scope_sql, scope_params = _scope_sql(person, center, account)
    sql = (
        f"SELECT DISTINCT CONVERT(varchar(10), t.booked_on, 23) FROM {table} t "
        "JOIN dbo.person p ON p.id = t.person_id "
        "JOIN dbo.center n ON n.center_id = p.center_id "
        "JOIN dbo.dim_category d ON d.category_id = t.category_id "
        "AND d.country_id = ? "
        "LEFT JOIN dbo.account a ON a.account_id = t.account_id "
        "WHERE n.country_id = ? AND t.year = ? "
        "AND d.local_code BETWEEN 3000 AND 4999 "
        "AND t.booked_on IS NOT NULL"
        f"{scope_sql} ORDER BY 1"
    )
    with connect() as conn:
        cur = conn.cursor()
        cur.execute(sql, country_id, country_id, year, *scope_params)
        return [str(r[0]) for r in cur.fetchall() if r[0]]


def result_sheet(
    country_id: int,
    year: int,
    *,
    person: str = "",
    center: str = "",
    account: str = "",
    as_of: str | None = None,
) -> dict[str, Any]:
    """Kosten (3000–3999) and opbrengsten (4000–4999) for one login scope."""
    cutoff = _cutoff(
        country_id, year, as_of, person=person, center=center, account=account
    )
    amounts = _amounts(
        country_id,
        year,
        person=person,
        center=center,
        account=account,
        cutoff=cutoff,
    )
    kosten: list[dict[str, Any]] = []
    opbrengsten: list[dict[str, Any]] = []
    for cat_id, local_code, label in _categories(country_id):
        amount = amounts.get(cat_id, Decimal("0"))
        row = {
            "category_id": cat_id,
            "code": local_code,
            "label": label,
            "amount": float(amount),
            "source": "transactions",
        }
        if 3000 <= local_code <= 3999:
            kosten.append(row)
        elif 4000 <= local_code <= 4999:
            opbrengsten.append(row)

    def total(rows: list[dict[str, Any]]) -> float:
        return float(sum((Decimal(str(r["amount"])) for r in rows), Decimal("0")))

    return {
        "year": year,
        "country_id": country_id,
        "as_of": cutoff.isoformat() if cutoff is not None else None,
        "activa": kosten,
        "passiva": opbrengsten,
        "total_activa": total(kosten),
        "total_passiva": total(opbrengsten),
        "balanced": False,
        "subadministratie": {"local_codes": [], "rows": []},
        "afschrijvingen": {"from_codes": [], "journals": []},
    }

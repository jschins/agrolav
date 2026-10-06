"""Profit/loss sheet for port 8500.

Same two-column layout as the balance sheet, but local codes 3000–4999
(uitgaven / inkomsten) and amounts limited to the login that opened the page.
Zero amounts are left out. A cash table sets the bank beside those totals.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from shared.balance_values import (
    KRUISPOSTEN_CASH_LABEL,
    UNIT_KRUISPOSTEN_LABELS,
    UNIT_RESULT_RESERVE_ROLES,
    cash_inkomsten_uitgaven,
    category_labels,
    implicit_kruisposten_journal,
    category_role_canonical,
    is_cp_role,
    is_rc_role,
    result_overlay_cents,
    spaar_source_exclude_clause,
    split_kruisposten_extra,
    sql_ident,
    unit_kruisposten_role,
)

_UNIT_ROLE = re.compile(r"unit(\d{4})\Z")

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


def unit_login_kind(
    country_id: int, *, unit: str = "", account: str = "", login: str = ""
) -> str:
    """``hd`` or ``unit`` when this request is a unit-level login, else ``\"\"``."""
    if not _is_unit_level(unit, account):
        return ""
    accounts = _load_accounts(country_id)
    login_account = _prefer_hd_account(
        accounts, login, _resolve_unit_account(accounts, login, account)
    )
    return _unit_kind(login_account, login)


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
    include_overlay: bool = True,
) -> dict[int, Decimal]:
    table = _transaction_table(country_id)
    totals: dict[int, Decimal] = {}
    unscoped = not person and not center and not account
    if table is not None:
        with connect() as conn:
            cur = conn.cursor()
            if unscoped:
                exclude_sql, exclude_params = spaar_source_exclude_clause(
                    country_id, cursor=cur
                )
                sql = (
                    f"SELECT t.category_id, SUM(t.amount) FROM {table} t "
                    "JOIN dbo.dim_category d ON d.category_id = t.category_id "
                    "AND d.country_id = ? "
                    "WHERE t.year = ? "
                    "AND d.local_code BETWEEN 3000 AND 4999"
                    f"{exclude_sql}"
                )
                params = [country_id, year, *exclude_params]
            else:
                scope_sql, scope_params = _scope_sql(person, center, account)
                sql = (
                    f"SELECT t.category_id, SUM(t.amount) "
                    f"FROM {table} t "
                    "JOIN dbo.person p ON p.id = t.person_id "
                    "JOIN dbo.center n ON n.center_id = p.center_id "
                    "JOIN dbo.dim_category d ON d.category_id = t.category_id "
                    "AND d.country_id = ? "
                    "LEFT JOIN dbo.account a ON a.account_id = t.account_id "
                    "WHERE n.country_id = ? AND t.year = ? AND t.bank_id IS NULL "
                    "AND d.local_code BETWEEN 3000 AND 4999"
                    f"{scope_sql}"
                )
                params = [country_id, country_id, year, *scope_params]
            if cutoff is not None:
                sql += " AND t.booked_on <= ?"
                params.append(cutoff.isoformat())
            sql += " GROUP BY t.category_id"
            cur.execute(sql, *params)
            for cat_id, amount in cur.fetchall():
                if cat_id is None or amount is None:
                    continue
                try:
                    totals[int(cat_id)] = Decimal(str(amount))
                except (TypeError, ValueError):
                    continue
    if unscoped and include_overlay:
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


def _first_any_booked(country_id: int, year: int) -> date | None:
    """Earliest booking in the year, the same instant the balance sheet uses."""
    table = _transaction_table(country_id)
    if table is None:
        return None
    with connect() as conn:
        cur = conn.cursor()
        cur.execute(f"SELECT MIN(booked_on) FROM {table} WHERE year = ?", year)
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
        if not person and not center and not account:
            first = _first_any_booked(country_id, year)
        else:
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


def _transaction_years(
    country_id: int,
    *,
    person: str = "",
    center: str = "",
    account: str = "",
) -> list[int]:
    table = _transaction_table(country_id)
    if table is None:
        return []
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
        return [int(r[0]) for r in cur.fetchall() if r[0] is not None]


def _has_opening(country_id: int, year: int) -> bool:
    with connect() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) FROM dbo.balance_opening o "
            "JOIN dbo.dim_category d ON d.category_id = o.category_id "
            "WHERE d.country_id = ? AND o.year = ?",
            (int(country_id), int(year)),
        )
        row = cur.fetchone()
    return bool(row and row[0])


def country_years(
    transaction_years: list[int],
    *,
    opening_for_next: bool,
    today: int | None = None,
) -> tuple[list[int], int]:
    """Years for a country login, plus the default year to open.

    The default is the latest year that has bookings. The following year is
    added when that year already has rows in ``dbo.balance_opening``.
    """
    base = sorted(set(transaction_years)) or [int(today if today is not None else date.today().year)]
    default = max(base)
    nxt = default + 1
    if opening_for_next and nxt not in base:
        return sorted([*base, nxt]), default
    return base, default


def opening_year_to_offer(
    country_id: int,
    *,
    person: str = "",
    center: str = "",
    account: str = "",
    unit: str = "",
) -> int | None:
    """Next year on a country login, when its opening balance is already stored.

    A person, center, or unit login stays on the years that have bookings.
    """
    if person or center or account or str(unit or "").strip():
        return None
    years = _transaction_years(
        country_id, person=person, center=center, account=account
    )
    base = years or [date.today().year]
    nxt = max(base) + 1
    if nxt in years or not _has_opening(country_id, nxt):
        return None
    return nxt


def list_years(
    country_id: int,
    *,
    person: str = "",
    center: str = "",
    account: str = "",
    unit: str = "",
) -> tuple[list[int], int]:
    years = _transaction_years(
        country_id, person=person, center=center, account=account
    )
    offer = opening_year_to_offer(
        country_id, person=person, center=center, account=account, unit=unit
    )
    listed, default = country_years(
        years,
        opening_for_next=offer is not None,
    )
    return listed, default


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


@dataclass
class _BankAccount:
    account_id: int
    name: str
    balance: Decimal
    iban: str
    center_id: int
    person: str
    center: str
    role: str
    unit_username: str = ""


def _unit_digits(role: str) -> int | None:
    match = _UNIT_ROLE.fullmatch(role.strip().lower())
    if not match:
        return None
    return int(match.group(1))


def _unit_xx0x(role: str) -> int | None:
    """Four digits of ``unitXX0X`` (the third digit is 0)."""
    digits = _unit_digits(role)
    if digits is None or (digits // 10) % 10 != 0:
        return None
    return digits


def _better_role(current: str, new: str) -> str:
    def rank(role: str) -> int:
        if role == "hd":
            return 3
        if _unit_digits(role) is not None:
            return 2
        if role:
            return 1
        return 0

    incoming = new.strip().lower()
    if rank(incoming) > rank(current):
        return incoming
    return current


def _name_slug(name: str) -> str:
    return "_".join(name.split()).lower()


def _name_stems(name: str) -> set[str]:
    slug = _name_slug(name)
    if not slug:
        return set()
    stems = {slug}
    if slug.startswith("hd_"):
        stems.add(slug[3:])
    return stems


def _names_pair(left: str, right: str) -> bool:
    """``HD Den Eker`` pairs with ``Den Eker``."""
    own = _name_stems(left)
    other = _name_stems(right)
    if not own or not other or own == other:
        return False
    return bool(own & other)


def _iban_key(iban: str) -> str:
    return "".join(str(iban or "").split()).upper()


def _load_accounts(country_id: int) -> list[_BankAccount]:
    with connect() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT a.account_id, a.account_name, a.balance, a.iban,
                   n.center_id, p.username, n.username, d.category_role
            FROM dbo.account a
            JOIN dbo.person p ON p.id = a.person_id
            JOIN dbo.center n ON n.center_id = p.center_id
            LEFT JOIN dbo.mapping m
              ON m.account_id = a.account_id AND m.country_id = n.country_id
             AND m.counterparty_account_id IS NULL
            LEFT JOIN dbo.dim_category d
              ON d.category_id = m.category_id AND d.country_id = m.country_id
            WHERE n.country_id = ?
            """,
            country_id,
        )
        found: dict[int, dict[str, Any]] = {}
        for account_id, name, balance, iban, center_id, person, center, role in cur.fetchall():
            if account_id is None or center_id is None:
                continue
            aid = int(account_id)
            slot = found.get(aid)
            text = str(role or "").strip().lower()
            if slot is None:
                try:
                    amount = Decimal(str(balance if balance is not None else 0))
                except (TypeError, ValueError):
                    amount = Decimal("0")
                found[aid] = {
                    "name": str(name or "").strip(),
                    "balance": amount,
                    "iban": str(iban or ""),
                    "center_id": int(center_id),
                    "person": str(person or ""),
                    "center": str(center or ""),
                    "role": text,
                }
            else:
                slot["role"] = _better_role(str(slot["role"]), text)
    usernames = _unit_usernames(country_id)
    rows: list[_BankAccount] = []
    for aid, slot in sorted(found.items()):
        rows.append(
            _BankAccount(
                account_id=aid,
                name=str(slot["name"]),
                balance=slot["balance"],
                iban=str(slot["iban"]),
                center_id=int(slot["center_id"]),
                person=str(slot["person"]),
                center=str(slot["center"]),
                role=str(slot["role"]),
                unit_username=usernames.get(aid, ""),
            )
        )
    return rows


def _unit_usernames(country_id: int) -> dict[int, str]:
    """account_id → ``dbo.unit.username`` for this country."""
    sql = """
        SELECT u.username, a.account_id
        FROM dbo.unit u
        INNER JOIN dbo.account a ON a.account_id = (
            SELECT TOP 1 a2.account_id
            FROM dbo.account a2
            JOIN dbo.person p2 ON p2.id = a2.person_id
            WHERE p2.center_id = u.center_id
              AND (
                a2.account_id = u.unit_id
                OR LOWER(REPLACE(a2.account_name, N' ', N'_')) = LOWER(u.username)
              )
            ORDER BY
              CASE
                WHEN LOWER(REPLACE(a2.account_name, N' ', N'_')) = LOWER(u.username) THEN 0
                ELSE 1
              END,
              CASE WHEN a2.account_id = u.unit_id THEN 0 ELSE 1 END,
              a2.account_id
        )
        WHERE u.country_id = ?
    """
    try:
        with connect() as conn:
            cur = conn.cursor()
            cur.execute(sql, country_id)
            rows = cur.fetchall()
    except Exception:
        return {}
    out: dict[int, str] = {}
    for username, account_id in rows:
        if account_id is None or not str(username or "").strip():
            continue
        out[int(account_id)] = str(username).strip()
    return out


def _is_unit_level(unit: str, account: str) -> bool:
    """A unit login is marked on the result URL, or carries its account."""
    flag = str(unit or "").strip().lower()
    return flag in ("1", "true", "yes") or bool(str(account or "").strip())


def _find_by_login(accounts: list[_BankAccount], login: str) -> _BankAccount | None:
    slug = _name_slug(login)
    if not slug:
        return None
    hits = [
        item
        for item in accounts
        if _name_slug(item.unit_username) == slug or _name_slug(item.name) == slug
    ]
    if not hits:
        return None
    return sorted(
        hits,
        key=lambda item: (
            0 if _name_slug(item.unit_username) == slug else 1,
            item.account_id,
        ),
    )[0]


def _resolve_unit_account(
    accounts: list[_BankAccount],
    login: str,
    account: str,
) -> _BankAccount | None:
    if account:
        matches = _scoped_accounts(accounts, person="", center="", account=account)
        if matches:
            return matches[0]
    return _find_by_login(accounts, login)


def _unit_kind(login_account: _BankAccount | None, login: str) -> str:
    """``hd`` or ``unit`` for a unit-level login.

    A login named ``hd_…`` is the huishoudelijke dienst even when the
    account it resolved first carries a ``unitNNNN`` role. Country 4's
    Keizersgracht bank is ``unit1111``; the HD bank is role ``hd``.
    """
    if _name_slug(login).startswith("hd_"):
        return "hd"
    if login_account is not None and login_account.role == "hd":
        return "hd"
    return "unit"


def _prefer_hd_account(
    accounts: list[_BankAccount],
    login: str,
    current: _BankAccount | None,
) -> _BankAccount | None:
    """Use the role-``hd`` bank for an ``hd_`` login.

    The resultaat then moves that bank's Kruisposten onto 4995, the same
    way an Instudo HD login does. A work-unit login keeps ``current``.
    """
    if not _name_slug(login).startswith("hd_"):
        return current
    if current is not None and current.role == "hd":
        return current
    candidates = [item for item in accounts if item.role == "hd"]
    if current is not None:
        in_center = [item for item in candidates if item.center_id == current.center_id]
        if in_center:
            candidates = in_center
    if len(candidates) == 1:
        return candidates[0]
    slug = _name_slug(login)
    named = [
        item
        for item in candidates
        if slug == _name_slug(item.unit_username)
        or slug in _name_stems(item.name)
        or slug in _name_stems(item.unit_username)
        or _names_pair(login, item.name)
        or _names_pair(login, item.unit_username)
    ]
    if len(named) == 1:
        return named[0]
    return current


def _sibling_for(
    login_account: _BankAccount,
    accounts: list[_BankAccount],
    kind: str,
    login: str,
) -> _BankAccount | None:
    found = _find_sibling(login_account, accounts, "unit" if kind == "hd" else "hd")
    if found is not None:
        return found
    slug = _name_slug(login) or _name_slug(login_account.unit_username) or _name_slug(
        login_account.name
    )
    stem = slug[3:] if slug.startswith("hd_") else slug
    if not stem:
        return None
    other = _find_by_login(accounts, stem if kind == "hd" else f"hd_{stem}")
    if (
        other is None
        or other.account_id == login_account.account_id
        or other.center_id != login_account.center_id
    ):
        return None
    return other


def _scoped_accounts(
    accounts: list[_BankAccount],
    *,
    person: str,
    center: str,
    account: str,
) -> list[_BankAccount]:
    key = _iban_key(account)
    if key:
        return [item for item in accounts if _iban_key(item.iban) == key]
    if person.strip():
        wanted = person.strip().lower()
        return [item for item in accounts if item.person.strip().lower() == wanted]
    if center.strip():
        wanted = center.strip().lower()
        return [item for item in accounts if item.center.strip().lower() == wanted]
    return list(accounts)


def _find_sibling(
    login: _BankAccount,
    accounts: list[_BankAccount],
    want: str,
) -> _BankAccount | None:
    """``hd`` looks for ``unitXX0X`` in the same center, and the reverse."""
    others = [
        item
        for item in accounts
        if item.center_id == login.center_id and item.account_id != login.account_id
    ]
    if want == "unit":
        candidates = [item for item in others if _unit_xx0x(item.role) is not None]
    else:
        candidates = [item for item in others if item.role == "hd"]
    named = [item for item in candidates if _names_pair(login.name, item.name)]
    if named:
        pool = named
    elif len(candidates) == 1:
        pool = candidates
    else:
        return None
    return sorted(pool, key=lambda item: item.account_id)[0]


def _slash_date(value: date) -> str:
    return f"{value.day:02d}/{value.month:02d}/{value.year}"


def _cents(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"))


def _present_day(year: int, cutoff: date | None) -> date:
    if cutoff is not None:
        return cutoff
    today = date.today()
    if year < today.year:
        return date(year, 12, 31)
    return today


def build_cash_table(
    banks: list[tuple[str, Decimal, Decimal]],
    *,
    named: bool,
    inkomsten: Decimal,
    uitgaven: Decimal,
    opening_day: date,
    present_day: date,
    extras: list[tuple[str, Decimal]] | None = None,
) -> dict[str, Any]:
    """Opening bank, inkomsten, uitgaven, totaal, then the present bank."""
    opening_text = _slash_date(opening_day)
    present_text = _slash_date(present_day)
    use_names = named and len(banks) > 1
    if use_names:
        opening_lines = [
            (f"Banksaldo {name} d.d. {opening_text}", opening, False)
            for name, opening, _present in banks
        ]
        present_lines = [
            (f"Banksaldo {name} d.d. {present_text}", present, False)
            for name, _opening, present in banks
        ]
    else:
        opening = sum((item[1] for item in banks), Decimal("0"))
        present = sum((item[2] for item in banks), Decimal("0"))
        opening_lines = [(f"Banksaldo d.d. {opening_text}", opening, False)]
        present_lines = [(f"Banksaldo d.d. {present_text}", present, True)]
    opening_sum = sum((amount for _label, amount, _alert in opening_lines), Decimal("0"))
    present_sum = sum((amount for _label, amount, _alert in present_lines), Decimal("0"))
    extra_lines = list(extras or [])
    extra_sum = sum((amount for _label, amount in extra_lines), Decimal("0"))
    calculated = opening_sum + inkomsten + uitgaven + extra_sum
    # Sum the cent amounts, then compare. A gap of at most one euro is the
    # same total: both rows keep that one decimal, so the rounded euros match.
    if abs(calculated - present_sum) <= Decimal("1"):
        agreed = _cents(present_sum)
        calculated = agreed
        present_sum = agreed
        mismatch = False
    else:
        mismatch = True
    rows: list[dict[str, Any]] = []

    def add(label: str, amount: Decimal, *, alert: bool, strong: bool = False) -> None:
        rows.append(
            {
                "label": label,
                "amount": float(_cents(amount)),
                "alert": bool(alert and mismatch),
                "strong": strong or (alert and mismatch),
                "gap": False,
            }
        )

    for label, amount, alert in opening_lines:
        add(label, amount, alert=alert)
    add("Inkomsten", inkomsten, alert=False)
    add("Uitgaven", uitgaven, alert=False)
    for label, amount in extra_lines:
        add(label, amount, alert=False)
    add("Totaal", calculated, alert=True, strong=True)
    rows.append(
        {"label": "", "amount": None, "alert": False, "strong": False, "gap": True}
    )
    for label, amount, alert in present_lines:
        add(label, amount, alert=alert)
    if use_names:
        add("Totaal", present_sum, alert=True, strong=True)
    return {"rows": rows, "mismatch": mismatch}


def _balances_at(
    country_id: int,
    accounts: list[_BankAccount],
    opening_day: date,
    present_day: date,
) -> list[tuple[str, Decimal, Decimal]]:
    """``(name, balance at the start of opening_day, balance at the end of present_day)``."""
    if not accounts:
        return []
    since: dict[int, Decimal] = {}
    after: dict[int, Decimal] = {}
    table = _transaction_table(country_id)
    if table is not None:
        marks = ",".join("?" * len(accounts))
        ids = [item.account_id for item in accounts]
        sql = (
            "SELECT t.account_id, "
            "SUM(CASE WHEN t.booked_on >= ? THEN t.amount ELSE 0 END), "
            "SUM(CASE WHEN t.booked_on > ? THEN t.amount ELSE 0 END) "
            f"FROM {table} t "
            f"WHERE t.bank_id IS NULL AND t.account_id IN ({marks}) "
            "GROUP BY t.account_id"
        )
        with connect() as conn:
            cur = conn.cursor()
            cur.execute(sql, opening_day.isoformat(), present_day.isoformat(), *ids)
            for account_id, opened, later in cur.fetchall():
                if account_id is None:
                    continue
                since[int(account_id)] = Decimal(str(opened or 0))
                after[int(account_id)] = Decimal(str(later or 0))
    rows: list[tuple[str, Decimal, Decimal]] = []
    for item in accounts:
        name = item.name.strip() or "Bank"
        rows.append(
            (
                name,
                item.balance - since.get(item.account_id, Decimal("0")),
                item.balance - after.get(item.account_id, Decimal("0")),
            )
        )
    return rows


def _rc_label(center: str) -> str:
    text = center.strip().lower()
    if text in ("sia", "center_sia") or text.endswith("_sia"):
        return "Rekening courant SIa"
    return "Rekening courant SIb"


def _fold_cash_extras(
    rows: list[tuple[int | None, str, Decimal, str]],
    *,
    center: str,
) -> list[tuple[str, Decimal]]:
    """Collapse non-resultaat cash into the lines shown above Totaal.

    ``category_role`` ``rc``, ``sia`` or ``sib`` shares one Rekening courant
    label for this center. ``category_role=cp`` is kept only when the lines
    do not cancel. Every other code keeps its category name.
    """
    buckets: dict[str, Decimal] = {}
    order: list[tuple[int, str]] = []
    sibling = Decimal("0")

    def add(label: str, amount: Decimal, sort: int) -> None:
        if label not in buckets:
            buckets[label] = Decimal("0")
            order.append((sort, label))
        buckets[label] += amount

    for local_code, label, amount, role in rows:
        if amount == 0:
            continue
        code = int(local_code) if local_code is not None else None
        kind = category_role_canonical(role)
        if is_rc_role(kind):
            add(_rc_label(center), amount, 0)
        elif is_cp_role(kind):
            sibling += amount
        else:
            name = (label or "").strip() or (str(code) if code is not None else "Overige")
            add(name, amount, code if code is not None else 99999)
    if sibling != 0:
        add(KRUISPOSTEN_CASH_LABEL, sibling, 1)
    lines: list[tuple[str, Decimal]] = []
    for _sort, label in sorted(order):
        total = buckets[label]
        if total != 0:
            lines.append((label, total))
    return lines


def _cross_cash_lines(
    country_id: int,
    account_ids: list[int],
    opening_day: date,
    present_day: date,
    *,
    center: str,
) -> list[tuple[str, Decimal]]:
    """Statement amounts on these banks that are not uitgaven or inkomsten.

    The window matches the bank saldo: booked on or after 1 January and on
    or before the present day, consolidated rows only.
    """
    if not account_ids:
        return []
    table = _transaction_table(country_id)
    if table is None:
        return []
    marks = ",".join("?" * len(account_ids))
    sql = (
        f"SELECT d.local_code, MIN(d.label), SUM(t.amount), "
        f"MIN(d.category_role) FROM {table} t "
        "LEFT JOIN dbo.dim_category d ON d.category_id = t.category_id "
        "AND d.country_id = ? "
        f"WHERE t.bank_id IS NULL AND t.account_id IN ({marks}) "
        "AND t.booked_on >= ? AND t.booked_on <= ? "
        "AND (d.local_code IS NULL OR d.local_code < 3000 OR d.local_code > 4999) "
        "GROUP BY d.local_code"
    )
    params: list[object] = [
        country_id,
        *account_ids,
        opening_day.isoformat(),
        present_day.isoformat(),
    ]
    with connect() as conn:
        cur = conn.cursor()
        cur.execute(sql, *params)
        fetched = cur.fetchall()
    rows: list[tuple[int | None, str, Decimal, str]] = []
    for local_code, label, amount, role in fetched:
        if amount is None:
            continue
        try:
            value = Decimal(str(amount))
        except (TypeError, ValueError):
            continue
        code = int(local_code) if local_code is not None else None
        rows.append((code, str(label or ""), value, str(role or "")))
    return _fold_cash_extras(rows, center=center)


def _unit_reserve_categories(country_id: int) -> dict[str, tuple[int, int, str]]:
    """``role`` → ``(category_id, local_code, label)`` for role 4000."""
    found: dict[str, tuple[int, int, str]] = {}
    with connect() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT category_id, local_code, label, category_role
            FROM dbo.dim_category
            WHERE country_id = ?
            """,
            country_id,
        )
        for cat_id, local_code, label, role in cur.fetchall():
            kind = category_role_canonical(role)
            if kind not in UNIT_RESULT_RESERVE_ROLES or kind in found:
                continue
            if cat_id is None or local_code is None:
                continue
            found[kind] = (int(cat_id), int(local_code), str(label or "").strip())
    return found


def _insert_by_code(rows: list[dict[str, Any]], row: dict[str, Any]) -> None:
    code = int(row["code"])
    for index, existing in enumerate(rows):
        if int(existing["code"]) > code:
            rows.insert(index, row)
            return
    rows.append(row)


def _cp_local(country_id: int) -> int:
    from shared.balance_values import role_category_row

    with connect() as conn:
        row = role_category_row(country_id, "cp", conn.cursor())
    if row is None:
        return 1200
    return int(row[1])


def _release_kruis_from_rc(
    lines: list[tuple[str, Decimal]],
    kruis: Decimal,
    *,
    center: str,
) -> list[tuple[str, Decimal]]:
    """Take the 4995 amount out of Rekening courant.

    ``kruis`` is the cp statement an HD login shows as Inkomsten residentie.
    On a work unit that opposite leg sits in Rekening courant. Adding
    ``kruis`` removes it, and the cash totals still meet the banks.
    """
    if kruis == 0:
        return lines
    label = _rc_label(center)
    found = False
    adjusted: list[tuple[str, Decimal]] = []
    for name, amount in lines:
        if name == label or name.startswith("Rekening courant"):
            adjusted.append((name, amount + kruis))
            found = True
        else:
            adjusted.append((name, amount))
    if not found:
        adjusted.insert(0, (label, kruis))
    return [(name, amount) for name, amount in adjusted if amount != 0]


def _add_unit_kruisposten_row(
    country_id: int,
    kosten: list[dict[str, Any]],
    opbrengsten: list[dict[str, Any]],
    kind: str,
    kruis: Decimal,
    reserves: dict[str, tuple[int, int, str]],
    cp_local: int,
) -> Decimal:
    """Hand journal van 4995, naar cp, amount minus the cp total.

    The P&L line shows Inkomsten residentie, opposite the van-leg. Returns
    that shown amount.
    """
    from shared.balance_values import (
        balance_category_id,
        shown_kruisposten_result,
        unit_kruisposten_local,
    )

    if kruis == 0:
        return Decimal("0")
    local = unit_kruisposten_local(kind)
    role = unit_kruisposten_role(kind)
    if local is None or role is None:
        return Decimal("0")
    _amount, effect_van, _effect_cp = implicit_kruisposten_journal(
        local, int(cp_local), kruis
    )
    shown = shown_kruisposten_result(kind, effect_van)
    if shown == 0:
        return Decimal("0")
    cat_id, code, label = reserves.get(
        role,
        (balance_category_id(country_id, local), local, UNIT_KRUISPOSTEN_LABELS.get(role, "")),
    )
    row = {
        "category_id": cat_id,
        "code": code,
        "label": label or UNIT_KRUISPOSTEN_LABELS.get(role, ""),
        "amount": float(shown),
        "source": "journal",
    }
    _insert_by_code(opbrengsten, row)
    return shown


def result_sheet(
    country_id: int,
    year: int,
    *,
    person: str = "",
    center: str = "",
    account: str = "",
    unit: str = "",
    login: str = "",
    as_of: str | None = None,
) -> dict[str, Any]:
    """Uitgaven (3000–3999) and inkomsten (4000–4999) for one login scope."""
    cutoff = _cutoff(
        country_id, year, as_of, person=person, center=center, account=account
    )
    opening_only = (
        opening_year_to_offer(
            country_id,
            person=person,
            center=center,
            account=account,
            unit=unit,
        )
        == year
    )
    amounts = _amounts(
        country_id,
        year,
        person=person,
        center=center,
        account=account,
        cutoff=cutoff,
        include_overlay=not opening_only,
    )
    accounts = _load_accounts(country_id)
    unit_level = _is_unit_level(unit, account)
    login_account: _BankAccount | None = None
    sibling: _BankAccount | None = None
    kind = ""
    named_banks = False
    if unit_level:
        login_account = _prefer_hd_account(
            accounts, login, _resolve_unit_account(accounts, login, account)
        )
        kind = _unit_kind(login_account, login)
        if login_account is not None:
            sibling = _sibling_for(login_account, accounts, kind, login)
            # Fold the HD into the unit. An HD login keeps only its own amounts.
            if kind == "unit" and sibling is not None:
                named_banks = True
                extra = _amounts(
                    country_id,
                    year,
                    person="",
                    center="",
                    account=_iban_key(sibling.iban),
                    cutoff=cutoff,
                )
                for cat_id, extra_amount in extra.items():
                    amounts[cat_id] = amounts.get(cat_id, Decimal("0")) + extra_amount
    reserves = _unit_reserve_categories(country_id)
    reserve_ids = {item[0] for item in reserves.values()}
    kosten: list[dict[str, Any]] = []
    opbrengsten: list[dict[str, Any]] = []
    for cat_id, local_code, label in _categories(country_id):
        if cat_id in reserve_ids:
            continue
        amount = amounts.get(cat_id, Decimal("0"))
        if amount == 0:
            continue
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

    def total(rows: list[dict[str, Any]]) -> Decimal:
        return sum((Decimal(str(r["amount"])) for r in rows), Decimal("0"))

    scope_banks = bool(person.strip() or center.strip()) and not unit_level
    cash = None
    kruis = Decimal("0")
    column_effect = Decimal("0")
    rc_lines: list[tuple[str, Decimal]] = []
    bank_rows: list[_BankAccount] = []
    named = False
    opening_day = date(year, 1, 1)
    present_day = opening_day
    if unit_level or scope_banks:
        present_day = _present_day(year, cutoff)
        if unit_level and named_banks and login_account is not None and sibling is not None:
            bank_rows = [login_account, sibling]
            named = True
            rc_center = login_account.center
        elif unit_level and login_account is not None:
            bank_rows = [login_account]
            named = False
            rc_center = login_account.center
        else:
            bank_rows = _scoped_accounts(
                accounts, person=person, center=center, account=account
            )
            named = not unit_level and len(bank_rows) > 1
            rc_center = center or (bank_rows[0].center if bank_rows else "")
        rc_lines = _cross_cash_lines(
            country_id,
            [item.account_id for item in bank_rows],
            opening_day,
            present_day,
            center=rc_center,
        )
        if kind == "hd":
            rc_lines, kruis = split_kruisposten_extra(rc_lines)
            column_effect = _add_unit_kruisposten_row(
                country_id,
                kosten,
                opbrengsten,
                kind,
                kruis,
                reserves,
                _cp_local(country_id),
            )
        elif kind == "unit":
            rc_lines, kruis = split_kruisposten_extra(rc_lines)
            rc_lines = _release_kruis_from_rc(rc_lines, kruis, center=rc_center)
            kruis = Decimal("0")
    uitgaven = total(kosten)
    opbrengsten_sum = total(opbrengsten)
    cash_uitgaven, cash_inkomsten = cash_inkomsten_uitgaven(
        kind, uitgaven, opbrengsten_sum, kruis, column_effect
    )
    if bank_rows:
        cash = build_cash_table(
            _balances_at(country_id, bank_rows, opening_day, present_day),
            named=named,
            inkomsten=cash_inkomsten,
            uitgaven=cash_uitgaven,
            opening_day=opening_day,
            present_day=present_day,
            extras=rc_lines,
        )

    if unit_level:
        level = "unit"
    elif person.strip():
        level = "person"
    elif center.strip():
        level = "center"
    else:
        level = "country"
    cash_labels = [
        str(row.get("label") or "")
        for row in (cash or {}).get("rows") or []
        if isinstance(row, dict)
    ]
    from shared.handset_debug import login_debug

    login_debug(
        "pl-window",
        country_id=country_id,
        year=year,
        level=level,
        login=login,
        unit=unit,
        person=person,
        center=center,
        account=account,
        kind=kind or "-",
        bank_id=None if login_account is None else login_account.account_id,
        bank_role="" if login_account is None else login_account.role,
        bank_name="" if login_account is None else login_account.name,
        kruis=str(kruis),
        column_effect=str(column_effect),
        inkomsten_4995=any(int(row.get("code") or 0) == 4995 for row in opbrengsten),
        cash_kruisposten=any(label == "Kruisposten" for label in cash_labels),
        cash_labels=cash_labels,
    )

    return {
        "year": year,
        "country_id": country_id,
        "as_of": cutoff.isoformat() if cutoff is not None else None,
        "activa": kosten,
        "passiva": opbrengsten,
        "total_activa": float(uitgaven),
        "total_passiva": float(opbrengsten_sum),
        "balanced": False,
        "subadministratie": {"local_codes": [], "rows": []},
        "afschrijvingen": {"from_codes": [], "journals": []},
        **({"cash": cash} if cash is not None else {}),
    }

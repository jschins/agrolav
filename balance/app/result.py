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
    _journal_balances,
    _journal_effect,
    booking_signed_amount,
    category_labels,
    result_overlay_cents,
    sql_ident,
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
            "WHERE n.country_id = ? AND t.year = ? AND t.bank_id IS NULL "
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
            LEFT JOIN dbo.mapping_banks m
              ON m.account_id = a.account_id AND m.country_id = n.country_id
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
    """``hd`` or ``unit`` for a unit-level login."""
    if login_account is not None and login_account.role == "hd":
        return "hd"
    if login_account is not None and _unit_digits(login_account.role) is not None:
        return "unit"
    if _name_slug(login).startswith("hd_"):
        return "hd"
    return "unit"


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
    rows: list[tuple[int | None, str, Decimal]],
    *,
    unit_code: int | None,
    center: str,
) -> list[tuple[str, Decimal]]:
    """Collapse non-resultaat cash into the lines shown above Totaal.

    Centrale legs (1125, 1126, and the unit's own four digits) share one
    Rekening courant label. The sibling pair (1112–1119 with 1200) is kept
    only when it does not cancel. Every other code keeps its category name.
    """
    sia = _rc_label(center) == "Rekening courant SIa"
    buckets: dict[str, Decimal] = {}
    order: list[tuple[int, str]] = []
    sibling = Decimal("0")

    def add(label: str, amount: Decimal, sort: int) -> None:
        if label not in buckets:
            buckets[label] = Decimal("0")
            order.append((sort, label))
        buckets[label] += amount

    for local_code, label, amount in rows:
        if amount == 0:
            continue
        code = int(local_code) if local_code is not None else None
        if code == 1125 or (not sia and unit_code is not None and code == unit_code):
            add("Rekening courant SIb", amount, 0)
        elif code == 1126 or (sia and unit_code is not None and code == unit_code):
            add("Rekening courant SIa", amount, 0)
        elif code == 1200 or (code is not None and 1112 <= code <= 1119):
            sibling += amount
        else:
            name = (label or "").strip() or (str(code) if code is not None else "Overige")
            add(name, amount, code if code is not None else 99999)
    if sibling != 0:
        add("Kruisposten", sibling, 1)
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
    unit_code: int | None,
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
        f"SELECT d.local_code, MIN(d.label), SUM(t.amount) FROM {table} t "
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
    rows: list[tuple[int | None, str, Decimal]] = []
    for local_code, label, amount in fetched:
        if amount is None:
            continue
        try:
            value = Decimal(str(amount))
        except (TypeError, ValueError):
            continue
        code = int(local_code) if local_code is not None else None
        rows.append((code, str(label or ""), value))
    return _fold_cash_extras(rows, unit_code=unit_code, center=center)


def _rc_balance(
    country_id: int,
    year: int,
    account_id: int | None,
    local_code: int,
    cutoff: date | None,
) -> Decimal:
    """Balance-sheet amount of ``local_code`` on one account.

    Activa codes keep the sheet sign (``-X``), so a unit outflow stored as
    ``-18500`` on 1114 contributes ``+18500``.
    """
    table = _transaction_table(country_id)
    with connect() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT TOP 1 category_id, category_role FROM dbo.dim_category "
            "WHERE country_id = ? AND local_code = ? ORDER BY category_id",
            country_id,
            local_code,
        )
        row = cur.fetchone()
        if not row or row[0] is None:
            return Decimal("0")
        cat_id = int(row[0])
        role = row[1]
        cur.execute(
            "SELECT amount FROM dbo.balance_opening WHERE category_id = ? AND year = ?",
            cat_id,
            year,
        )
        opened = cur.fetchone()
        total = (
            Decimal(str(opened[0]))
            if opened and opened[0] is not None
            else Decimal("0")
        )
        if table is not None:
            sql = (
                f"SELECT SUM(t.amount) FROM {table} t "
                "JOIN dbo.dim_category d ON d.category_id = t.category_id "
                "AND d.country_id = ? "
                "WHERE t.year = ? AND t.bank_id IS NULL "
                "AND d.local_code = ? "
                "AND (d.category_role IS NULL OR d.category_role IN "
                "(N'remainder', N'mirror'))"
            )
            params: list[object] = [country_id, year, local_code]
            if account_id is not None:
                sql += " AND t.account_id = ?"
                params.append(account_id)
            if cutoff is not None:
                sql += " AND t.booked_on <= ?"
                params.append(cutoff.isoformat())
            cur.execute(sql, *params)
            summed = cur.fetchone()
            raw = (
                Decimal(str(summed[0]))
                if summed and summed[0] is not None
                else Decimal("0")
            )
            signed = booking_signed_amount(local_code, raw, role)
            if signed is not None:
                total += signed
        total += _journal_effect(country_id, year, cur, as_of=cutoff).get(
            cat_id, Decimal("0")
        )
        cur.execute("SELECT OBJECT_ID(N'dbo.transaction_mirror', N'U')")
        if cur.fetchone()[0] is not None:
            total += _journal_balances(country_id, year, cur, as_of=cutoff).get(
                cat_id, Decimal("0")
            )
    return total


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
    amounts = _amounts(
        country_id,
        year,
        person=person,
        center=center,
        account=account,
        cutoff=cutoff,
    )
    accounts = _load_accounts(country_id)
    unit_level = _is_unit_level(unit, account)
    login_account: _BankAccount | None = None
    sibling: _BankAccount | None = None
    kind = ""
    named_banks = False
    if unit_level:
        login_account = _resolve_unit_account(accounts, login, account)
        if login_account is not None:
            kind = _unit_kind(login_account, login)
            sibling = _sibling_for(login_account, accounts, kind, login)
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
    kosten: list[dict[str, Any]] = []
    opbrengsten: list[dict[str, Any]] = []
    for cat_id, local_code, label in _categories(country_id):
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

    uitgaven = total(kosten)
    inkomsten = total(opbrengsten)
    if kind == "hd" and sibling is not None:
        digits = _unit_xx0x(sibling.role)
        if digits is None:
            digits = _unit_xx0x(sibling.unit_username)
        if digits is not None:
            inkomsten += _rc_balance(
                country_id, year, sibling.account_id, digits + 10, cutoff
            )
    if kind == "hd":
        inkomsten = -inkomsten
    cash = None
    if unit_level:
        opening_day = date(year, 1, 1)
        present_day = _present_day(year, cutoff)
        if named_banks and login_account is not None and sibling is not None:
            bank_rows = [login_account, sibling]
        elif login_account is not None:
            bank_rows = [login_account]
        else:
            bank_rows = _scoped_accounts(
                accounts, person=person, center=center, account=account
            )
        unit_code = (
            _unit_digits(login_account.role) if login_account is not None else None
        )
        rc_lines = _cross_cash_lines(
            country_id,
            [item.account_id for item in bank_rows],
            opening_day,
            present_day,
            unit_code=unit_code,
            center=login_account.center if login_account is not None else center,
        )
        cash = build_cash_table(
            _balances_at(country_id, bank_rows, opening_day, present_day),
            named=named_banks,
            inkomsten=inkomsten,
            uitgaven=uitgaven,
            opening_day=opening_day,
            present_day=present_day,
            extras=rc_lines,
        )

    return {
        "year": year,
        "country_id": country_id,
        "as_of": cutoff.isoformat() if cutoff is not None else None,
        "activa": kosten,
        "passiva": opbrengsten,
        "total_activa": float(uitgaven),
        "total_passiva": float(total(opbrengsten)),
        "balanced": False,
        "subadministratie": {"local_codes": [], "rows": []},
        "afschrijvingen": {"from_codes": [], "journals": []},
        **({"cash": cash} if cash is not None else {}),
    }

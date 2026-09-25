"""Mark internal transfers between registered accounts as cross-postings.

Any country with ``dbo.country.has_balance`` can run it. Only statements
on a country bank are read.
A booking is kept when that bank's counterparty is another of those banks
and the other bank books the negated amount on the same day.

The outgoing leg decides the category, and only these pairs are written:

* SIb ``NL46INGB0001726568`` is local 1100 and SIa ``NL84INGB0002801129``
  is local 1099. Each statement keeps its own sign. SIa wiring 1000 to
  SIb is +1000 on 1100 and −1000 on 1099. SIb wiring 500 to SIa is −500
  on 1100 and +500 on 1099.
* a ``source`` account against a ``unitNNNN`` account in its own center
  is local NNNN, on both statements
* an ``hd`` account against a ``unitNNNN`` account, in any center, is
  local 1200 (category 11200), on both statements
* ``NL46INGB0001726568`` (category 11020) against its spaarrekening
  (category 11021), or ``NL84INGB0002801129`` (category 11010) against its
  spaarrekening (category 11019), is local 1200 (category 11200)

The value stored on the booking is the category id. Balance countries are
taken in ``country_id`` order. The first stores the local code. Each later
country with ``has_balance`` adds another 10000, so country 5 is
``local_code + 10000`` and the next balance country is
``local_code + 20000``. A ``dim_category`` row for the local code supplies
the id when one exists. Every other pair is left uncategorized, and a
previous cross-posting category on such a row is released.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Sequence

CROSS_POSTING_COUNTRY_ID = 5
# Country 5 (the second balance country): local_code + 10000. Local 1200 is 11200.
# The next country with has_balance adds another 10000. See category_id_offset.
_CATEGORY_BASE = 10000
_LOCAL_SIB_TO_SIA = 1099
_LOCAL_SIA_TO_SIB = 1100
_LOCAL_CROSS_POSTING = 1200
CROSS_POSTING_CATEGORY_ID = _CATEGORY_BASE + _LOCAL_CROSS_POSTING
_IBAN_NL46 = "NL46INGB0001726568"
_IBAN_NL84 = "NL84INGB0002801129"
_SOURCE_IBANS = frozenset({_IBAN_NL46, _IBAN_NL84})
# NL46 is category 11020, its spaarrekening 11021.
# NL84 is category 11010, its spaarrekening 11019.
_SPAAR_CATEGORY_BY_IBAN = {_IBAN_NL46: 11021, _IBAN_NL84: 11019}
_ANCHOR_CATEGORY_IDS = frozenset({11010, 11019, 11020, 11021})
_USER_ROLE = re.compile(r"^(?:user|unit)(\d{4})$")
_COUNTRY_BANK_PREFIXES = ("unit", "source", "funds")
_MONEY = Decimal("0.01")


def _money(value: Any) -> Decimal:
    return Decimal(str(value)).quantize(_MONEY)


def _day(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if len(text) >= 10:
        try:
            return date.fromisoformat(text[:10])
        except ValueError:
            return None
    return None


def _iban_key(value: Any) -> str:
    return "".join(str(value or "").split()).upper()


def between_registered_accounts(
    rows: list[tuple[int, int, Any, Any, Any]],
    iban_to_accounts: dict[str, list[int]],
) -> list[tuple[int, int, date, Decimal, int]]:
    """Bookings whose counterparty IBAN is another registered account.

    ``rows`` are ``(transaction_id, account_id, booked_on, amount, counterparty_iban)``.
    The result is ``(transaction_id, account_id, day, amount, counterparty_account_id)``.
    """
    kept: list[tuple[int, int, date, Decimal, int]] = []
    for transaction_id, account_id, booked_on, amount, counterparty_iban in rows:
        day = _day(booked_on)
        if day is None:
            continue
        money = _money(amount)
        if money == 0:
            continue
        own = int(account_id)
        other = _counterparty_account(own, counterparty_iban, iban_to_accounts)
        if other is None:
            continue
        kept.append((int(transaction_id), own, day, money, other))
    return kept


def _counterparty_account(
    own_account_id: int,
    counterparty_iban: Any,
    iban_to_accounts: dict[str, list[int]],
) -> int | None:
    for account_id in iban_to_accounts.get(_iban_key(counterparty_iban), ()):
        if account_id != own_account_id:
            return account_id
    return None


def matching_transaction_ids(
    rows: list[tuple[int, int, Any, Any, int | None]],
) -> set[int]:
    """Ids kept from the registered-account list, plus their counterpart booking.

    ``rows`` are ``(transaction_id, account_id, booked_on, amount, counterparty_account_id)``.
    ``counterparty_account_id`` is set only when the statement IBAN is in
    ``dbo.account`` and is a different account. A row in that list is rejected
    unless that account books the negated amount on the same calendar day.
    If that booking itself names a registered account, it must be this one.
    Each booking is used once.
    """
    return {
        transaction_id
        for left_id, _left_account, right_id, _right_account in matching_pairs(rows)
        for transaction_id in (left_id, right_id)
    }


def matching_pairs(
    rows: list[tuple[int, int, Any, Any, int | None]],
) -> list[tuple[int, int, int, int]]:
    """Pairs ``(id, account_id, counterpart_id, counterpart_account_id)``."""
    parsed: list[tuple[int, int, date, Decimal, int | None]] = []
    for transaction_id, account_id, booked_on, amount, counterparty_account_id in rows:
        day = _day(booked_on)
        if day is None:
            continue
        money = _money(amount)
        if money == 0:
            continue
        own = int(account_id)
        other = None if counterparty_account_id is None else int(counterparty_account_id)
        if other == own:
            other = None
        parsed.append((int(transaction_id), own, day, money, other))

    by_account_day: dict[tuple[int, date, Decimal], list[int]] = {}
    named: dict[int, int | None] = {}
    for transaction_id, account_id, day, amount, other in parsed:
        by_account_day.setdefault((account_id, day, amount), []).append(transaction_id)
        named[transaction_id] = other

    used: set[int] = set()
    pairs: list[tuple[int, int, int, int]] = []
    for transaction_id, account_id, day, amount, other in parsed:
        if other is None or transaction_id in used:
            continue
        for other_id in by_account_day.get((other, day, -amount), ()):
            if other_id in used or other_id == transaction_id:
                continue
            named_back = named[other_id]
            if named_back is not None and named_back != account_id:
                continue
            used.add(transaction_id)
            used.add(other_id)
            pairs.append((transaction_id, account_id, other_id, other))
            break
    return pairs


def _role_text(role: object) -> str:
    return str(role or "").strip().lower()


def center_side(name: object) -> str | None:
    """``sia`` or ``sib`` when the center username is that center."""
    text = str(name or "").strip().lower()
    if text in ("sia", "center_sia") or text.endswith("_sia"):
        return "sia"
    if text in ("sib", "center_sib") or text.endswith("_sib"):
        return "sib"
    return None


def is_country_bank_role(role: object) -> bool:
    """True for ``unit``/``source``/``funds``, and for ``user`` or ``unit`` plus four digits."""
    if user_digits(role) is not None:
        return True
    text = _role_text(role)
    return any(text.startswith(prefix) for prefix in _COUNTRY_BANK_PREFIXES)


def user_digits(role: object) -> int | None:
    """Four digits after ``user`` or ``unit``, as in ``unit1108``."""
    match = _USER_ROLE.fullmatch(_role_text(role))
    if not match:
        return None
    return int(match.group(1))


def category_id_offset(
    country_id: int,
    balance_country_ids: Sequence[int] | None = None,
) -> int:
    """Block added to a local code when it is stored as ``category_id``.

    ``balance_country_ids`` is every ``dbo.country.country_id`` with
    ``has_balance`` set, in ``country_id`` order. The earliest stores the
    local code. Each later balance country adds 10000. Beheer (4) is 0
    and Instudo (5) is 10000. A country that is not in the list stores
    the local code. When the list is omitted, only country 5 is treated
    as the second balance country.
    """
    cid = int(country_id)
    if balance_country_ids is None:
        if cid == CROSS_POSTING_COUNTRY_ID:
            return _CATEGORY_BASE
        return 0
    ordered = sorted({int(item) for item in balance_country_ids})
    try:
        rank = ordered.index(cid)
    except ValueError:
        return 0
    return rank * _CATEGORY_BASE


def category_id_for_local_code(
    local_code: int,
    country_id: int = CROSS_POSTING_COUNTRY_ID,
    balance_country_ids: Sequence[int] | None = None,
) -> int:
    """Stored ``category_id`` for a local code when no ``dim_category`` row wins."""
    return category_id_offset(country_id, balance_country_ids) + int(local_code)


def stored_category_id(
    local_code: int,
    by_local: dict[int, int] | None = None,
    country_id: int = CROSS_POSTING_COUNTRY_ID,
    balance_country_ids: Sequence[int] | None = None,
) -> int:
    """Category id written on the booking.

    A ``dim_category`` row for this local code wins. Otherwise the id is
    the local code plus ``category_id_offset`` for this country.
    """
    code = int(local_code)
    if by_local is not None and code in by_local:
        return int(by_local[code])
    return category_id_for_local_code(code, country_id, balance_country_ids)


def transfer_local_code(
    from_iban: object,
    to_iban: object,
    from_center: str | None = None,
    to_center: str | None = None,
    from_role: object = "",
    to_role: object = "",
    from_category_id: int | None = None,
    to_category_id: int | None = None,
) -> int | None:
    """Local code for one same-day opposite pair, or ``None`` to leave it.

    ``from_*`` is the outgoing booking (negative amount).
    ``NL46INGB0001726568`` → ``NL84INGB0002801129`` is 1099 and the reverse
    is 1100. A ``source`` account against ``unitNNNN`` in its own center is
    NNNN. An ``hd`` account against ``unitNNNN``, in any center, is 1200.
    ``NL46`` against category 11021, or
    ``NL84`` against category 11019, is 1200. Anything else is left
    uncategorized.
    """
    source = _iban_key(from_iban)
    dest = _iban_key(to_iban)
    if source == _IBAN_NL46 and dest == _IBAN_NL84:
        return _LOCAL_SIB_TO_SIA
    if source == _IBAN_NL84 and dest == _IBAN_NL46:
        return _LOCAL_SIA_TO_SIB
    if _hd_unit(from_role, to_role):
        return _LOCAL_CROSS_POSTING
    digits = _same_center_user_digits(source, dest, from_center, to_center, from_role, to_role)
    if digits is not None:
        return digits
    if _spaar_pair(
        source,
        dest,
        from_category_id,
        to_category_id,
        from_role,
        to_role,
        from_center,
        to_center,
    ):
        return _LOCAL_CROSS_POSTING
    return None


def _same_center_user_digits(
    source: str,
    dest: str,
    from_center: str | None,
    to_center: str | None,
    from_role: object,
    to_role: object,
) -> int | None:
    """Four digits when ``source`` meets ``unitNNNN`` or ``userNNNN`` in its center."""
    source_hit = _is_source_account(source, from_role)
    dest_hit = _is_source_account(dest, to_role)
    if source_hit and not dest_hit:
        source_center, other_center, other_role = from_center, to_center, to_role
    elif dest_hit and not source_hit:
        source_center, other_center, other_role = to_center, from_center, from_role
    else:
        return None
    if not _centers_match(source_center, other_center):
        return None
    return user_digits(other_role)


def _hd_unit(from_role: object, to_role: object) -> bool:
    """True when ``hd`` meets ``unitNNNN``, whatever the centers."""
    left, right = _role_text(from_role), _role_text(to_role)
    if left == "hd":
        other = right
    elif right == "hd":
        other = left
    else:
        return False
    return other.startswith("unit") and user_digits(other) is not None


def _is_source_account(iban: str, role: object) -> bool:
    """The two Instudo source IBANs, or any account whose role starts with ``source``."""
    if iban in _SOURCE_IBANS:
        return True
    return _role_text(role).startswith("source")


def _centers_match(left: str | None, right: str | None) -> bool:
    """Same center: ``sia``/``sib`` when the name encodes that, otherwise the username."""
    a = center_side(left) or str(left or "").strip().lower()
    b = center_side(right) or str(right or "").strip().lower()
    return bool(a) and a == b


def _spaar_pair(
    source: str,
    dest: str,
    from_category_id: int | None,
    to_category_id: int | None,
    from_role: object = "",
    to_role: object = "",
    from_center: str | None = None,
    to_center: str | None = None,
) -> bool:
    """A source account against its spaarrekening, in either direction.

    Instudo names these as NL46 against category 11021 and NL84 against
    category 11019. Any other balance country pairs a ``source`` role with
    a ``mirror`` role in the same center.
    """
    for iban, spaar_id in _SPAAR_CATEGORY_BY_IBAN.items():
        if source == iban and to_category_id is not None and int(to_category_id) == spaar_id:
            return True
        if dest == iban and from_category_id is not None and int(from_category_id) == spaar_id:
            return True
    roles = (_role_text(from_role), _role_text(to_role))
    if "mirror" in roles and any(role.startswith("source") for role in roles):
        return _centers_match(from_center, to_center)
    return False


def leg_local_code(iban: object) -> int | None:
    """Local code for this account's statement on an SIa↔SIb transfer.

    SIb (``NL46INGB0001726568``) is 1100. SIa (``NL84INGB0002801129``) is
    1099. The statement keeps its own sign, so the two totals are opposites.
    """
    key = _iban_key(iban)
    if key == _IBAN_NL46:
        return _LOCAL_SIA_TO_SIB
    if key == _IBAN_NL84:
        return _LOCAL_SIB_TO_SIA
    return None


def transfer_category(
    from_iban: object,
    to_iban: object,
    from_center: str | None = None,
    to_center: str | None = None,
    from_role: object = "",
    to_role: object = "",
    from_category_id: int | None = None,
    to_category_id: int | None = None,
) -> int | None:
    """Category id for one pair on country 5, or ``None`` when it stays uncategorized."""
    local = transfer_local_code(
        from_iban,
        to_iban,
        from_center,
        to_center,
        from_role,
        to_role,
        from_category_id,
        to_category_id,
    )
    if local is None:
        return None
    return category_id_for_local_code(local)


def managed_category_ids(
    by_local: dict[int, int] | None,
    digit_codes: set[int],
    bank_category_ids: set[int] | None = None,
    country_id: int = CROSS_POSTING_COUNTRY_ID,
    balance_country_ids: Sequence[int] | None = None,
) -> set[int]:
    """Category ids this routine writes, so a later run can release the rest.

    A four-digit code that is itself a live bank category is not released.
    """
    banks = bank_category_ids or set()
    codes = {_LOCAL_SIB_TO_SIA, _LOCAL_SIA_TO_SIB, _LOCAL_CROSS_POSTING, *digit_codes}
    found: set[int] = set()
    for code in codes:
        stored = stored_category_id(code, by_local, country_id, balance_country_ids)
        if code not in (_LOCAL_SIB_TO_SIA, _LOCAL_SIA_TO_SIB, _LOCAL_CROSS_POSTING) and stored in banks:
            continue
        found.add(stored)
        if code not in banks:
            found.add(code)
    return found


def apply_cross_postings(center: str) -> dict[str, int]:
    """Write category ids and ``modification`` 1 on matched pairs.

    The country is the one that owns ``center``. Countries without
    ``has_balance`` are left unchanged.
    """
    from app import user_store
    from app.sql_catalog import coerce_center, country_for_center
    from shared.balance_values import country_has_balance, require_remainder_row, transaction_table

    if not user_store.database_url():
        raise RuntimeError("SQL Server is not configured")
    user_store.init_user_store()
    conn = user_store._sql_connect()
    cursor = conn.cursor()
    country_name = country_for_center(coerce_center(center))
    if not country_name:
        raise RuntimeError(f"Unknown country for center {center!r}")
    cursor.execute(
        """
        SELECT country_id FROM dbo.country
        WHERE username = ? COLLATE Latin1_General_CI_AI
        """,
        (country_name,),
    )
    found = cursor.fetchone()
    if found is None or found[0] is None:
        raise RuntimeError(f"Unknown country {country_name!r}")
    country_id = int(found[0])
    if not country_has_balance(country_id, cursor):
        return {"updated": 0, "released": 0}
    cursor.execute(
        "SELECT country_id FROM dbo.country WHERE has_balance = 1 ORDER BY country_id"
    )
    balance_ids = [int(row[0]) for row in cursor.fetchall() if row[0] is not None]
    table = transaction_table(country_id, cursor)
    if not table:
        raise RuntimeError(f"country {country_id} has no transaction table")
    cursor.execute(f"SELECT OBJECT_ID(N'{table}', N'U')")
    if cursor.fetchone()[0] is None:
        raise RuntimeError(f"{table} does not exist")

    by_local = _category_ids_by_local_code(cursor, country_id)
    bank_ids = _country_bank_accounts(cursor, country_id)
    iban_to_accounts = _registered_accounts(cursor, bank_ids)
    iban_of = {
        account_id: iban
        for iban, account_ids in iban_to_accounts.items()
        for account_id in account_ids
    }
    center_of = _account_centers(cursor, country_id)
    role_of = _user_roles(cursor, country_id)
    account_category = _account_categories(cursor, country_id)
    digit_codes = {
        digits
        for role in role_of.values()
        if (digits := user_digits(role)) is not None
    }
    managed = managed_category_ids(
        by_local, digit_codes, set(account_category.values()), country_id, balance_ids
    )
    fetched = _load_candidates(cursor, table, bank_ids, managed)
    pair_rows = [
        (
            int(transaction_id),
            int(account_id),
            booked_on,
            amount,
            _counterparty_account(int(account_id), counterparty_iban, iban_to_accounts),
        )
        for transaction_id, _person_id, _year, account_id, booked_on, amount, counterparty_iban, _category_id, _modification in fetched
        if account_id is not None and int(account_id) in bank_ids
    ]
    amount_of = {transaction_id: _money(amount) for transaction_id, _account, _day, amount, _other in pair_rows}
    pairs = matching_pairs(pair_rows)
    category_of: dict[int, int] = {}
    for left_id, left_account, right_id, right_account in pairs:
        if amount_of[left_id] < 0:
            from_account, to_account = left_account, right_account
            from_id, to_id = left_id, right_id
        else:
            from_account, to_account = right_account, left_account
            from_id, to_id = right_id, left_id
        local = transfer_local_code(
            iban_of.get(from_account, ""),
            iban_of.get(to_account, ""),
            center_of.get(from_account),
            center_of.get(to_account),
            role_of.get(from_account, ""),
            role_of.get(to_account, ""),
            account_category.get(from_account),
            account_category.get(to_account),
        )
        if local is None:
            continue
        if local in (_LOCAL_SIB_TO_SIA, _LOCAL_SIA_TO_SIB):
            for tid, account in ((from_id, from_account), (to_id, to_account)):
                leg = leg_local_code(iban_of.get(account, ""))
                if leg is None:
                    continue
                category_of[tid] = stored_category_id(leg, by_local, country_id, balance_ids)
            continue
        category = stored_category_id(local, by_local, country_id, balance_ids)
        category_of[to_id] = category
        category_of[from_id] = category
    remainder_id, _remainder_code = require_remainder_row(country_id, cursor)
    by_category: dict[int, list[int]] = {}
    to_release: list[int] = []
    changed_persons: set[tuple[int, int]] = set()
    for transaction_id, person_id, year, _account_id, _booked_on, _amount, _iban, category_id, modification in fetched:
        tid = int(transaction_id)
        current = int(category_id or 0)
        person_year = (int(person_id), int(year))
        if tid in category_of:
            target = category_of[tid]
            by_category.setdefault(target, []).append(tid)
            if current != target or int(modification or 0) != 1:
                changed_persons.add(person_year)
            continue
        if current in managed:
            to_release.append(tid)
            changed_persons.add(person_year)
    if not any(by_category.values()) and not to_release:
        return {"updated": 0, "released": 0}

    for category_id, ids in by_category.items():
        _update_ids(cursor, table, ids, category_id, 1)
    _update_ids(cursor, table, to_release, remainder_id, -1)
    conn.commit()
    try:
        _refresh_category_totals(cursor, table, changed_persons, country_id)
        conn.commit()
    except Exception as exc:  # noqa: BLE001
        print(f"cross-postings: category totals were not refreshed: {exc}")
    updated = sum(len(ids) for ids in by_category.values())
    return {"updated": updated, "released": len(to_release)}


def _account_centers(cursor: Any, country_id: int) -> dict[int, str]:
    """account_id → center username (``sia``/``sib`` when the name encodes that)."""
    cursor.execute(
        """
        SELECT a.account_id, n.username
        FROM dbo.account a
        JOIN dbo.person p ON p.id = a.person_id
        JOIN dbo.center n ON n.center_id = p.center_id
        WHERE n.country_id = ?
        """,
        (int(country_id),),
    )
    out: dict[int, str] = {}
    for account_id, username in cursor.fetchall():
        if account_id is None:
            continue
        side = center_side(username) or str(username or "").strip().lower()
        if side:
            out[int(account_id)] = side
    return out


def _country_bank_accounts(cursor: Any, country_id: int) -> set[int]:
    """Country banks, the two source IBANs, and their spaarrekening categories."""
    cursor.execute(
        """
        SELECT m.account_id, d.category_role
        FROM dbo.dim_category d
        JOIN dbo.mapping_banks m
          ON m.category_id = d.category_id AND m.country_id = d.country_id
        WHERE d.country_id = ?
          AND (
            LOWER(LTRIM(RTRIM(d.category_role))) LIKE N'unit%'
            OR LOWER(LTRIM(RTRIM(d.category_role))) = N'hd'
            OR LOWER(LTRIM(RTRIM(d.category_role))) LIKE N'source%'
            OR LOWER(LTRIM(RTRIM(d.category_role))) LIKE N'funds%'
            OR LOWER(LTRIM(RTRIM(d.category_role))) LIKE N'user[0-9][0-9][0-9][0-9]'
            OR LOWER(LTRIM(RTRIM(d.category_role))) = N'mirror'
          )
        """,
        (int(country_id),),
    )
    out: set[int] = set()
    for account_id, role in cursor.fetchall():
        if account_id is None:
            continue
        if not is_country_bank_role(role) and _role_text(role) not in ("mirror", "hd"):
            continue
        out.add(int(account_id))
    marks = ",".join("?" * len(_ANCHOR_CATEGORY_IDS))
    cursor.execute(
        f"""
        SELECT account_id
        FROM dbo.mapping_banks
        WHERE country_id = ? AND category_id IN ({marks})
        """,
        (int(country_id), *sorted(_ANCHOR_CATEGORY_IDS)),
    )
    for (account_id,) in cursor.fetchall():
        if account_id is not None:
            out.add(int(account_id))
    cursor.execute(
        """
        SELECT a.account_id
        FROM dbo.account a
        JOIN dbo.person p ON p.id = a.person_id
        JOIN dbo.center n ON n.center_id = p.center_id
        WHERE n.country_id = ?
          AND REPLACE(UPPER(LTRIM(RTRIM(a.iban))), N' ', N'') IN (?, ?)
        """,
        (int(country_id), _IBAN_NL46, _IBAN_NL84),
    )
    for (account_id,) in cursor.fetchall():
        if account_id is not None:
            out.add(int(account_id))
    return out


def _account_categories(cursor: Any, country_id: int) -> dict[int, int]:
    """account_id → category_id from ``dbo.mapping_banks``."""
    cursor.execute(
        """
        SELECT account_id, category_id
        FROM dbo.mapping_banks
        WHERE country_id = ?
        """,
        (int(country_id),),
    )
    out: dict[int, int] = {}
    for account_id, category_id in cursor.fetchall():
        if account_id is None or category_id is None:
            continue
        aid = int(account_id)
        cid = int(category_id)
        current = out.get(aid)
        if current is None or cid in _ANCHOR_CATEGORY_IDS:
            out[aid] = cid
    return out


def _user_roles(cursor: Any, country_id: int) -> dict[int, str]:
    """account_id → role text for ``hd``, ``unitNNNN``, ``userNNNN``, ``source`` and ``mirror``."""
    cursor.execute(
        """
        SELECT m.account_id, d.category_role
        FROM dbo.dim_category d
        JOIN dbo.mapping_banks m
          ON m.category_id = d.category_id AND m.country_id = d.country_id
        WHERE d.country_id = ?
          AND (
            LOWER(LTRIM(RTRIM(d.category_role))) = N'hd'
            OR LOWER(LTRIM(RTRIM(d.category_role))) LIKE N'user[0-9][0-9][0-9][0-9]'
            OR LOWER(LTRIM(RTRIM(d.category_role))) LIKE N'unit[0-9][0-9][0-9][0-9]'
            OR LOWER(LTRIM(RTRIM(d.category_role))) LIKE N'source%'
            OR LOWER(LTRIM(RTRIM(d.category_role))) = N'mirror'
          )
        """,
        (int(country_id),),
    )
    out: dict[int, str] = {}
    for account_id, role in cursor.fetchall():
        if account_id is None or not str(role or "").strip():
            continue
        out[int(account_id)] = _role_text(role)
    return out


def _registered_accounts(cursor: Any, bank_ids: set[int]) -> dict[str, list[int]]:
    """IBAN → account ids, limited to the country banks."""
    if not bank_ids:
        return {}
    marks = ",".join("?" * len(bank_ids))
    cursor.execute(
        f"SELECT account_id, iban FROM dbo.account WHERE account_id IN ({marks})",
        tuple(sorted(bank_ids)),
    )
    out: dict[str, list[int]] = {}
    for account_id, iban in cursor.fetchall():
        key = _iban_key(iban)
        if not key or account_id is None:
            continue
        bucket = out.setdefault(key, [])
        aid = int(account_id)
        if aid not in bucket:
            bucket.append(aid)
    return out


def _category_ids_by_local_code(cursor: Any, country_id: int) -> dict[int, int]:
    """local_code → category_id for country 5."""
    cursor.execute(
        """
        SELECT local_code, category_id
        FROM dbo.dim_category
        WHERE country_id = ?
        """,
        (int(country_id),),
    )
    out: dict[int, int] = {}
    for local_code, category_id in cursor.fetchall():
        if local_code is None or category_id is None:
            continue
        out[int(local_code)] = int(category_id)
    return out


def _load_candidates(
    cursor: Any, table: str, bank_ids: set[int], category_ids: set[int]
) -> list[Any]:
    ids = sorted(category_ids)
    id_marks = ",".join("?" * len(ids))
    if bank_ids:
        marks = ",".join("?" * len(bank_ids))
        where = f"t.account_id IN ({marks}) OR t.category_id IN ({id_marks})"
        params: list[Any] = [*sorted(bank_ids), *ids]
    else:
        where = f"t.category_id IN ({id_marks})"
        params = list(ids)
    cursor.execute(
        f"""
        SELECT t.transaction_id, t.person_id, t.year, t.account_id, t.booked_on,
               t.amount, t.counterparty_iban, t.category_id, t.modification
        FROM {table} t
        WHERE {where}
        """,
        params,
    )
    return list(cursor.fetchall())


def _update_ids(cursor: Any, table: str, ids: list[int], category_id: int, modification: int) -> None:
    for start in range(0, len(ids), 400):
        chunk = ids[start : start + 400]
        marks = ",".join("?" * len(chunk))
        cursor.execute(
            f"""
            UPDATE {table}
            SET category_id = ?, modification = ?
            WHERE transaction_id IN ({marks})
            """,
            [category_id, modification, *chunk],
        )


def _refresh_category_totals(
    cursor: Any, table: str, persons: set[tuple[int, int]], country_id: int
) -> None:
    if not persons:
        return
    from shared.balance_values import spaar_source_exclude_clause

    exclude_sql, exclude_params = spaar_source_exclude_clause(
        int(country_id), cursor=cursor
    )
    for person_id, year in sorted(persons):
        cursor.execute(
            "DELETE FROM dbo.category_total "
            "WHERE person_id = ? AND year = ? AND bank_id IS NULL",
            (person_id, year),
        )
        cursor.execute(
            f"""
            INSERT INTO dbo.category_total (person_id, year, bank_id, category_id, amount)
            SELECT t.person_id, ?, NULL, t.category_id, SUM(CAST(t.amount AS decimal(19,2)))
            FROM {table} t
            WHERE t.person_id = ? AND t.year = ?{exclude_sql}
            GROUP BY t.person_id, t.category_id
            """,
            (year, person_id, year, *exclude_params),
        )

"""Mark internal transfers between registered accounts as cross-postings.

Any country with ``dbo.country.has_balance`` can run it. Every account
in that country with an IBAN is read. A booking is kept when its
counterparty is another of those accounts and that account books the
negated amount on the same day or one day apart.

Each leg of a pair is written on its own. Every fixed leg is the
``dbo.dim_category`` row with that ``category_role``, read on each run:

* Centrale SIa against Centrale SIb: SIb is the ``cp`` row and SIa is the
  ``siasib`` row.
* Centrale SIa against ``unitNNNN`` in center SIa: SIa is local NNNN
  (category 1NNNN) and the unit is the ``sia`` row.
* Centrale SIb against ``unitNNNN`` in center SIb: SIb is local NNNN
  (category 1NNNN) and the unit is the ``sib`` row.
* ``unitXX0X`` against the ``hd`` account in the same center: the unit is
  local XX1X (category 1XX1X) and the sibling is the ``cp`` row.
  ``unit1108`` writes the unit to 11118. When ``assoc_category_id`` names
  that pair, the work-unit booking is the ``rc`` row that points at the HD
  category and the HD booking is still ``cp``.

A country without a row for a role leaves that leg uncategorized.

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
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Sequence

CROSS_POSTING_COUNTRY_ID = 5
# Country 5 (the second balance country): local_code + 10000. Local 1200 is 11200.
# The next country with has_balance adds another 10000. See category_id_offset.
_CATEGORY_BASE = 10000
_UNIT_ROLE = re.compile(r"^unit(\d{4})$")
_IBAN_NL46 = "NL46INGB0001726568"
_IBAN_NL84 = "NL84INGB0002801129"
_ANCHOR_CATEGORY_IDS = frozenset({11010, 11019, 11020, 11021})
_USER_ROLE = re.compile(r"^(?:user|unit)(\d{4})$")
_COUNTRY_BANK_PREFIXES = ("unit", "source", "funds")
_MONEY = Decimal("0.01")


@dataclass(frozen=True)
class PairLegs:
    """Local codes of the fixed legs, read from ``dbo.dim_category`` by role.

    ``cp`` is the kruisposten row, ``siasib`` the SIa leg of a SIa–SIb pair,
    ``sia`` / ``sib`` the unit leg of a Centrale SIa / SIb pair. ``None``
    leaves that leg uncategorized.
    """

    cp: int | None = None
    siasib: int | None = None
    sia: int | None = None
    sib: int | None = None

    def codes(self) -> set[int]:
        return {code for code in (self.cp, self.siasib, self.sia, self.sib) if code is not None}


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
    ``dbo.account`` and is a different account. Both bookings must name each
    other, and the amounts must be opposite to the cent. The booking dates
    are the same day or differ by one day. Each booking is used once.
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
        # Same day first, then the day before and the day after.
        for candidate in (day, day - timedelta(days=1), day + timedelta(days=1)):
            found = False
            for other_id in by_account_day.get((other, candidate, -amount), ()):
                if other_id in used or other_id == transaction_id:
                    continue
                if named[other_id] != account_id:
                    continue
                used.add(transaction_id)
                used.add(other_id)
                pairs.append((transaction_id, account_id, other_id, other))
                found = True
                break
            if found:
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


def unit_digits(role: object) -> int | None:
    """Four digits of ``unitNNNN``. ``userNNNN`` is not a unit."""
    match = _UNIT_ROLE.fullmatch(_role_text(role))
    if not match:
        return None
    return int(match.group(1))


def unit_xx0x_digits(role: object) -> int | None:
    """Four digits of ``unitXX0X`` (the third digit is 0)."""
    digits = unit_digits(role)
    if digits is None or (digits // 10) % 10 != 0:
        return None
    return digits


def hd_sibling_local_code(unit_code: int) -> int:
    """Local code written on the unit leg of a unit–HD pair.

    ``XX0X`` plus 10 is ``XX1X``. ``1102`` is ``1112``, category 11112.
    This number is only the category the pair is written to. A category is
    ``rc`` when ``dbo.dim_category.category_role`` says so.
    """
    return int(unit_code) + 10


def _is_centrale_sib(iban: object) -> bool:
    return _iban_key(iban) == _IBAN_NL46


def _is_centrale_sia(iban: object) -> bool:
    return _iban_key(iban) == _IBAN_NL84


def pair_local_codes(
    from_iban: object,
    to_iban: object,
    from_center: str | None = None,
    to_center: str | None = None,
    from_role: object = "",
    to_role: object = "",
    *,
    legs: PairLegs | None = None,
) -> tuple[int | None, int | None]:
    """Local codes for the outgoing leg and the incoming leg.

    ``None`` leaves that leg uncategorized. Centrale SIa against Centrale
    SIb is ``legs.siasib`` on SIa and ``legs.cp`` on SIb. Centrale SIa
    against a SIa ``unitNNNN`` is NNNN on SIa and ``legs.sia`` on the unit.
    Centrale SIb against a SIb ``unitNNNN`` is NNNN on SIb and ``legs.sib``
    on the unit. A ``unitXX0X`` against the ``hd`` account in the same
    center is XX1X on the unit and ``legs.cp`` on the sibling. Every leg in
    ``legs`` is a ``dim_category`` row found by its ``category_role``.
    """
    fixed = legs or PairLegs()
    from_sib = _is_centrale_sib(from_iban)
    to_sib = _is_centrale_sib(to_iban)
    from_sia = _is_centrale_sia(from_iban)
    to_sia = _is_centrale_sia(to_iban)
    if (from_sib and to_sia) or (from_sia and to_sib):
        if from_sib:
            return (fixed.cp, fixed.siasib)
        return (fixed.siasib, fixed.cp)

    from_unit = unit_digits(from_role)
    to_unit = unit_digits(to_role)
    if from_sia and to_unit is not None and center_side(to_center) == "sia":
        return (to_unit, fixed.sia)
    if to_sia and from_unit is not None and center_side(from_center) == "sia":
        return (fixed.sia, from_unit)
    if from_sib and to_unit is not None and center_side(to_center) == "sib":
        return (to_unit, fixed.sib)
    if to_sib and from_unit is not None and center_side(from_center) == "sib":
        return (fixed.sib, from_unit)

    from_xx0x = unit_xx0x_digits(from_role)
    to_xx0x = unit_xx0x_digits(to_role)
    from_hd = _role_text(from_role) == "hd"
    to_hd = _role_text(to_role) == "hd"
    if from_xx0x is not None and to_hd and _centers_match(from_center, to_center):
        return (hd_sibling_local_code(from_xx0x), fixed.cp)
    if to_xx0x is not None and from_hd and _centers_match(from_center, to_center):
        return (fixed.cp, hd_sibling_local_code(to_xx0x))
    return (None, None)


@dataclass(frozen=True)
class CategoryLink:
    """One ``dbo.dim_category`` row used by the assoc lookup.

    ``account_id`` is the bank link. ``assoc_category_id`` is the other
    category this row names. ``None`` on either column means this row does
    not take part in that half of the lookup.
    """

    category_id: int
    local_code: int
    role: str
    account_id: int | None = None
    assoc_category_id: int | None = None


def _link_role(role: object) -> str:
    return _role_text(role)


def _is_unit_role(role: str) -> bool:
    return role == "unit" or unit_digits(role) is not None


def _bank_link(links: Sequence[CategoryLink], account_id: int) -> CategoryLink | None:
    """The bank category of this account. Cash on the same account is skipped."""
    hits: list[CategoryLink] = []
    for link in links:
        if link.account_id != int(account_id):
            continue
        role = link.role
        if role in ("cash", "rc", "cp", "mirror"):
            continue
        if role in ("hd", "source", "bank") or _is_unit_role(role):
            hits.append(link)
    if not hits:
        return None
    hits.sort(key=lambda link: (0 if link.role == "hd" else 1 if _is_unit_role(link.role) else 2, link.category_id))
    return hits[0]


def _rc_for_hd(links: Sequence[CategoryLink], hd_category_id: int) -> CategoryLink | None:
    """The ``rc`` row whose assoc is this HD category. Lowest local code wins."""
    found = [
        link
        for link in links
        if link.role == "rc" and link.assoc_category_id == int(hd_category_id)
    ]
    if not found:
        return None
    found.sort(key=lambda link: (link.local_code, link.category_id))
    return found[0]


def assoc_pair_local_codes(
    links: Sequence[CategoryLink],
    from_account: int,
    to_account: int,
    from_center: str | None = None,
    to_center: str | None = None,
    cp_local: int | None = None,
) -> tuple[int, int] | None:
    """Local codes for a work-unit against its HD, or ``None`` if unresolved.

    The HD row's ``assoc_category_id`` is the work-unit bank. The ``rc`` row
    whose assoc is that HD category is written on the work-unit booking. The
    HD booking is written to ``cp``. That is the same leg the digit rule
    writes to ``cp``. An ``rc`` row such as 1101 points at its own work-unit
    bank, not at the source. The source is the country's ``source`` row. A
    unit against that source is not decided here, so that booking is not
    newly written to ``cp``.
    """
    if cp_local is None or not _centers_match(from_center, to_center):
        return None
    left = _bank_link(links, from_account)
    right = _bank_link(links, to_account)
    if left is None or right is None:
        return None
    if left.role == "hd" and _is_unit_role(right.role) and left.assoc_category_id == right.category_id:
        register = _rc_for_hd(links, left.category_id)
        if register is None:
            return None
        return (int(cp_local), int(register.local_code))
    if right.role == "hd" and _is_unit_role(left.role) and right.assoc_category_id == left.category_id:
        register = _rc_for_hd(links, right.category_id)
        if register is None:
            return None
        return (int(register.local_code), int(cp_local))
    return None


def assoc_register_locals(links: Sequence[CategoryLink]) -> set[int]:
    """Local codes written on the work-unit leg, so a later run can release them."""
    hd_ids = {
        link.category_id
        for link in links
        if link.role == "hd" and link.assoc_category_id is not None
    }
    return {
        int(link.local_code)
        for link in links
        if link.role == "rc" and link.assoc_category_id in hd_ids
    }


def _activa_sheet_amount(local_code: int, amount: Decimal) -> Decimal | None:
    """Activa sign for a cross-posting leg.

    1000–1999 reverse the statement amount. 2000–2999 keep it. The
    ``category_role`` is not read here.
    """
    code = int(local_code)
    if 1000 <= code <= 1999:
        return -amount
    if 2000 <= code <= 2999:
        return amount
    return None


def _sheet_pair_opposed(
    from_local: int,
    from_amount: Decimal,
    to_local: int,
    to_amount: Decimal,
) -> bool:
    """True when the two legs cancel after the activa sign.

    Stored amounts already sum to zero. Both legs of a written pair sit on
    activa, so both reverse and the pair still cancels. The ``rc`` role is
    a separate read of ``dbo.dim_category`` and does not decide this.
    """
    left = _activa_sheet_amount(int(from_local), from_amount)
    right = _activa_sheet_amount(int(to_local), to_amount)
    if left is None or right is None:
        return False
    return left + right == 0


def _centers_match(left: str | None, right: str | None) -> bool:
    """Same center: ``sia``/``sib`` when the name encodes that, otherwise the username."""
    a = center_side(left) or str(left or "").strip().lower()
    b = center_side(right) or str(right or "").strip().lower()
    return bool(a) and a == b


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
    """Local code of the outgoing leg, or ``None`` when that leg is not written."""
    del from_category_id, to_category_id
    from_local, _to_local = pair_local_codes(
        from_iban, to_iban, from_center, to_center, from_role, to_role
    )
    return from_local


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
    role_codes: set[int] | None = None,
) -> set[int]:
    """Category ids this routine writes, so a later run can release the rest.

    ``role_codes`` are the local codes of the ``cp`` / ``siasib`` / ``sia`` /
    ``sib`` rows. A four-digit code that is itself a live bank category is
    not released.
    """
    banks = bank_category_ids or set()
    fixed = set(role_codes or ())
    codes = set(fixed)
    codes.update(digit_codes)
    found: set[int] = set()
    for code in codes:
        stored = stored_category_id(code, by_local, country_id, balance_country_ids)
        if code not in fixed and stored in banks:
            continue
        found.add(stored)
        if code not in banks:
            found.add(code)
    return found


def apply_cross_postings(
    center: str,
    *,
    source_ids: set[str] | None = None,
    only_uncalculated: bool = False,
) -> dict[str, int]:
    """Write category ids and ``modification`` 1 on matched pairs.

    A menu run writes rows at -1 or 0. A download run (``only_uncalculated``)
    writes only -1. A hand row (``modification`` 2, 3, or 4) is left
    as it is, category and description included. A row already at 1 is left
    as it is.

    The country is the one that owns ``center``. Countries without
    ``has_balance`` are left unchanged.

    When ``source_ids`` is set, only pairs that include one of those newly
    stored statements are considered. The other leg is written only when its
    own ``modification`` is open for this run. Statements outside those pairs
    are left as they are.
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
    from app.cash_on_hand import assign_cash_on_hand

    assign_cash_on_hand(
        cursor,
        table,
        country_id,
        source_ids=source_ids,
    )
    cursor.execute(f"SELECT OBJECT_ID(N'{table}', N'U')")
    if cursor.fetchone()[0] is None:
        raise RuntimeError(f"{table} does not exist")

    by_local = _category_ids_by_local_code(cursor, country_id)
    legs = _pair_legs(cursor, country_id)
    bank_ids = _country_registered_accounts(cursor, country_id)
    iban_to_accounts = _registered_accounts(cursor, bank_ids)
    iban_of = {
        account_id: iban
        for iban, account_ids in iban_to_accounts.items()
        for account_id in account_ids
    }
    center_of = _account_centers(cursor, country_id)
    role_of = _user_roles(cursor, country_id)
    account_category = _account_categories(cursor, country_id)
    links = _category_links(cursor, country_id)
    digit_codes = {
        digits
        for role in role_of.values()
        if (digits := user_digits(role)) is not None
    }
    if links:
        digit_codes.update(assoc_register_locals(links))
    digit_codes.update(
        hd_sibling_local_code(digits)
        for role in role_of.values()
        if (digits := unit_xx0x_digits(role)) is not None
    )
    managed = managed_category_ids(
        by_local,
        digit_codes,
        set(account_category.values()),
        country_id,
        balance_ids,
        legs.codes(),
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
    pair_ids: list[frozenset[int]] = []
    for left_id, left_account, right_id, right_account in pairs:
        if amount_of[left_id] < 0:
            from_account, to_account = left_account, right_account
            from_id, to_id = left_id, right_id
        else:
            from_account, to_account = right_account, left_account
            from_id, to_id = right_id, left_id
        from_local, to_local = _pair_locals(
            links,
            from_account,
            to_account,
            center_of.get(from_account),
            center_of.get(to_account),
            legs.cp,
            iban_of.get(from_account, ""),
            iban_of.get(to_account, ""),
            role_of.get(from_account, ""),
            role_of.get(to_account, ""),
            legs,
        )
        if from_local is None or to_local is None:
            continue
        if amount_of[from_id] + amount_of[to_id] != 0:
            continue
        if not _sheet_pair_opposed(
            from_local, amount_of[from_id], to_local, amount_of[to_id]
        ):
            continue
        category_of[from_id] = stored_category_id(
            from_local, by_local, country_id, balance_ids
        )
        category_of[to_id] = stored_category_id(
            to_local, by_local, country_id, balance_ids
        )
        pair_ids.append(frozenset((from_id, to_id)))
    scoped = source_ids is not None
    if scoped:
        only_ids = _transaction_ids_for_sources(cursor, table, source_ids or set())
        keep: set[int] = set()
        for members in pair_ids:
            if members & only_ids:
                keep |= set(members)
        category_of = {tid: cat for tid, cat in category_of.items() if tid in keep}
    remainder_id, _remainder_code = require_remainder_row(country_id, cursor)
    by_category: dict[int, list[int]] = {}
    to_release: list[int] = []
    changed_persons: set[tuple[int, int]] = set()
    for transaction_id, person_id, year, _account_id, _booked_on, _amount, _iban, category_id, modification in fetched:
        tid = int(transaction_id)
        current = int(category_id or 0)
        person_year = (int(person_id), int(year))
        try:
            flag = int(modification)
        except (TypeError, ValueError):
            flag = -1
        open_flags = (-1,) if only_uncalculated else (-1, 0)
        if flag not in open_flags:
            continue
        if tid in category_of:
            target = category_of[tid]
            by_category.setdefault(target, []).append(tid)
            if current != target or flag != 1:
                changed_persons.add(person_year)
            continue
        if scoped:
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


def _pair_locals(
    links: Sequence[CategoryLink] | None,
    from_account: int,
    to_account: int,
    from_center: str | None,
    to_center: str | None,
    cp_local: int | None,
    from_iban: object,
    to_iban: object,
    from_role: object,
    to_role: object,
    legs: PairLegs,
) -> tuple[int | None, int | None]:
    """Assoc lookup first. The digit and Centrale rules run when it does not resolve.

    The assoc lookup writes ``cp`` on the HD booking. The digit rule writes
    ``cp`` on that same booking. A unit against ``source`` stays on the digit
    rule, which leaves it uncategorized, so that booking is not written to ``cp``.
    """
    if links:
        found = assoc_pair_local_codes(
            links,
            from_account,
            to_account,
            from_center,
            to_center,
            cp_local,
        )
        if found is not None:
            return found
    return pair_local_codes(
        from_iban,
        to_iban,
        from_center,
        to_center,
        from_role,
        to_role,
        legs=legs,
    )


def _category_links(cursor: Any, country_id: int) -> list[CategoryLink] | None:
    """Rows for the assoc lookup, or ``None`` when the columns are not there yet."""
    cursor.execute(
        """
        SELECT COL_LENGTH(N'dbo.dim_category', N'account_id'),
               COL_LENGTH(N'dbo.dim_category', N'assoc_category_id')
        """
    )
    widths = cursor.fetchone()
    if widths is None or widths[0] is None or widths[1] is None:
        return None
    cursor.execute(
        """
        SELECT category_id, local_code, category_role, account_id, assoc_category_id
        FROM dbo.dim_category
        WHERE country_id = ?
        """,
        (int(country_id),),
    )
    rows: list[CategoryLink] = []
    for category_id, local_code, role, account_id, assoc_id in cursor.fetchall():
        if category_id is None or local_code is None:
            continue
        rows.append(
            CategoryLink(
                int(category_id),
                int(local_code),
                _link_role(role),
                None if account_id is None else int(account_id),
                None if assoc_id is None else int(assoc_id),
            )
        )
    return rows


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


def _country_registered_accounts(cursor: Any, country_id: int) -> set[int]:
    """Every ``dbo.account`` in the country that has an IBAN."""
    cursor.execute(
        """
        SELECT a.account_id
        FROM dbo.account a
        JOIN dbo.person p ON p.id = a.person_id
        JOIN dbo.center n ON n.center_id = p.center_id
        WHERE n.country_id = ?
          AND a.iban IS NOT NULL
          AND LTRIM(RTRIM(a.iban)) <> N''
        """,
        (int(country_id),),
    )
    return {int(row[0]) for row in cursor.fetchall() if row[0] is not None}


def _account_categories(cursor: Any, country_id: int) -> dict[int, int]:
    """account_id → category_id from ``dbo.mapping`` (no counterparty)."""
    cursor.execute(
        """
        SELECT account_id, category_id
        FROM dbo.mapping
        WHERE country_id = ?
          AND counterparty_account_id IS NULL
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
        JOIN dbo.mapping m
          ON m.category_id = d.category_id AND m.country_id = d.country_id
         AND m.counterparty_account_id IS NULL
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


def _pair_legs(cursor: Any, country_id: int) -> PairLegs:
    """Fixed legs by ``category_role``: ``cp``, ``siasib``, ``sia``, ``sib``.

    A role without a row leaves that leg ``None``, and pairs that need it
    stay uncategorized.
    """
    cursor.execute(
        """
        SELECT LOWER(LTRIM(RTRIM(category_role))), MIN(local_code)
        FROM dbo.dim_category
        WHERE country_id = ?
          AND LOWER(LTRIM(RTRIM(category_role))) IN (N'cp', N'siasib', N'sia', N'sib')
          AND local_code IS NOT NULL
        GROUP BY LOWER(LTRIM(RTRIM(category_role)))
        """,
        (int(country_id),),
    )
    found: dict[str, int] = {}
    for role, local_code in cursor.fetchall():
        if role is None or local_code is None:
            continue
        found[str(role)] = int(local_code)
    return PairLegs(
        cp=found.get("cp"),
        siasib=found.get("siasib"),
        sia=found.get("sia"),
        sib=found.get("sib"),
    )


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


def _transaction_ids_for_sources(cursor: Any, table: str, source_ids: set[str]) -> set[int]:
    """Primary keys of statements just stored by a bank download."""
    ids = [source_id for source_id in source_ids if str(source_id).strip()]
    found: set[int] = set()
    for start in range(0, len(ids), 400):
        chunk = ids[start : start + 400]
        marks = ",".join("?" * len(chunk))
        cursor.execute(
            f"SELECT transaction_id FROM {table} WHERE source_id IN ({marks})",
            chunk,
        )
        for row in cursor.fetchall():
            if row[0] is not None:
                found.add(int(row[0]))
    return found


def _load_candidates(
    cursor: Any, table: str, bank_ids: set[int], category_ids: set[int]
) -> list[Any]:
    ids = sorted(category_ids)
    clauses: list[str] = []
    params: list[Any] = []
    if bank_ids:
        marks = ",".join("?" * len(bank_ids))
        clauses.append(f"t.account_id IN ({marks})")
        params.extend(sorted(bank_ids))
    if ids:
        id_marks = ",".join("?" * len(ids))
        clauses.append(f"t.category_id IN ({id_marks})")
        params.extend(ids)
    if not clauses:
        return []
    where = " OR ".join(clauses)
    cursor.execute(
        f"""
        SELECT t.transaction_id, t.person_id, t.year, t.account_id, t.booked_on,
               t.amount, t.counterparty_iban, t.category_id, t.modification
        FROM {table} t
        WHERE ({where})
          AND (t.bank_type IS NULL OR t.bank_type <> N'Geldautomaat')
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

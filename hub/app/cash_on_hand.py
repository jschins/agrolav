"""Write an HD account's Geldautomaat bookings onto that account's cash category.

One booking has one category. The cash category is the ``category_role``
``cash`` post mapped to the same account as the ``hd`` bank. Hand rows
(modification 2, 3, or 4) are left as they are.
"""
from __future__ import annotations

from shared.balance_values import (
    CASH_ON_HAND_ACCOUNT,
    CASH_ON_HAND_BANK_TYPE,
    cash_category_accounts,
)

CASH_COUNTRY_ID = 5


def assign_cash_on_hand(
    cursor: object,
    table: str,
    country_id: int,
    *,
    person_id: int | None = None,
    year: int | None = None,
    account_id: int | None = None,
    source_ids: set[str] | None = None,
) -> int:
    """Set ``category_id`` and ``modification`` 1 on open Geldautomaat rows.

    ``modification`` 1 keeps the later term pass and the cross-posting pass
    off the row. Returns the number of rows the updates matched.
    """
    if not table:
        return 0
    if source_ids is not None and not source_ids:
        return 0
    sources = [str(item).strip() for item in (source_ids or set()) if str(item).strip()]
    pairs = cash_category_accounts(int(country_id), cursor)
    if not pairs and int(country_id) == CASH_COUNTRY_ID:
        pairs = dict(CASH_ON_HAND_ACCOUNT)
    updated = 0
    for category_id, mapped_account in pairs.items():
        if account_id is not None and int(mapped_account) != int(account_id):
            continue
        updated += _assign_account(
            cursor,
            table,
            category_id=int(category_id),
            account_id=int(mapped_account),
            person_id=person_id,
            year=year,
            source_ids=sources if source_ids is not None else None,
        )
    return updated


def assign_bound_cash_on_hand() -> int:
    """Cash write for the person and year bound in ``app.runtime``."""
    from app.sql_replica import _open_bound_scope

    bound = _open_bound_scope()
    if bound is None:
        return 0
    try:
        if bound.country_id is None:
            return 0
        return assign_cash_on_hand(
            bound.cursor,
            bound.table,
            int(bound.country_id),
            person_id=int(bound.person_id),
            year=int(bound.year),
            account_id=bound.account_id,
        )
    finally:
        try:
            bound.conn.close()
        except Exception:
            pass


def _assign_account(
    cursor: object,
    table: str,
    *,
    category_id: int,
    account_id: int,
    person_id: int | None,
    year: int | None,
    source_ids: list[str] | None,
) -> int:
    base = (
        f"UPDATE {table} SET category_id = ?, modification = 1, hit = NULL "
        "WHERE account_id = ? AND bank_id IS NULL AND bank_type = ? "
        "AND modification IN (-1, 0, 1)"
    )
    params: list[object] = [category_id, account_id, CASH_ON_HAND_BANK_TYPE]
    if person_id is not None:
        base += " AND person_id = ?"
        params.append(int(person_id))
    if year is not None:
        base += " AND year = ?"
        params.append(int(year))
    if source_ids is None:
        cursor.execute(base, tuple(params))
        return int(getattr(cursor, "rowcount", 0) or 0)
    updated = 0
    for start in range(0, len(source_ids), 400):
        chunk = source_ids[start : start + 400]
        marks = ",".join("?" * len(chunk))
        cursor.execute(
            f"{base} AND source_id IN ({marks})",
            tuple([*params, *chunk]),
        )
        updated += int(getattr(cursor, "rowcount", 0) or 0)
    return updated

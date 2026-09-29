"""Bookings whose category was set by hand.

A row is written when someone sets a booking's category by hand. The category
totals view uses it to print that category bold. A categorization wipe leaves
``modification`` >= 2 bookings in place, so these rows are not a restore log.
"""
from __future__ import annotations

from typing import Any


def _table_exists(cursor: Any) -> bool:
    cursor.execute("SELECT OBJECT_ID(N'dbo.category_hand', N'U')")
    row = cursor.fetchone()
    return row is not None and row[0] is not None


def _country_id(cursor: Any, person_id: int) -> int | None:
    cursor.execute(
        """
        SELECT n.country_id
        FROM dbo.person p
        JOIN dbo.center n ON n.center_id = p.center_id
        WHERE p.id = ?
        """,
        (int(person_id),),
    )
    row = cursor.fetchone()
    if row is None or row[0] is None:
        return None
    return int(row[0])


def hand_source_ids() -> set[str] | None:
    """Source ids with a hand category for the bound person and year.

    ``None`` when ``dbo.category_hand`` is missing, so callers can keep the
    older styling. An empty set means no hand categories are stored.
    """
    from app.sql_replica import _open_bound_scope

    bound = _open_bound_scope()
    if bound is None or not _table_exists(bound.cursor):
        return None
    country_id = _country_id(bound.cursor, bound.person_id)
    if country_id is None:
        return set()
    bound.cursor.execute(
        """
        SELECT source_id
        FROM dbo.category_hand
        WHERE country_id = ? AND person_id = ? AND year = ?
        """,
        (country_id, int(bound.person_id), int(bound.year)),
    )
    return {str(row[0]) for row in bound.cursor.fetchall() if row and row[0] is not None}


def remember_hand_category(source_id: str, category: object) -> None:
    """Store or clear the hand category for the bound booking.

    ``category`` is the local code the screen saved. The remainder code
    clears the stored row. Missing ``dbo.category_hand`` is ignored so a
    category edit still saves before that table exists.
    """
    from app.sql_replica import _open_bound_scope
    from shared.balance_values import require_remainder_row

    key = str(source_id or "").strip()
    if not key:
        return
    bound = _open_bound_scope()
    if bound is None:
        return
    if not _table_exists(bound.cursor):
        return
    country_id = _country_id(bound.cursor, bound.person_id)
    if country_id is None:
        return
    try:
        code = int(category) if category is not None and str(category).strip() != "" else None
    except (TypeError, ValueError):
        code = None
    remainder_id, remainder_code = require_remainder_row(country_id, bound.cursor)
    if code is None or int(code) == int(remainder_code):
        bound.cursor.execute(
            """
            DELETE FROM dbo.category_hand
            WHERE country_id = ? AND person_id = ? AND year = ? AND source_id = ?
            """,
            (country_id, int(bound.person_id), int(bound.year), key),
        )
        bound.conn.commit()
        return
    bound.cursor.execute(
        """
        SELECT category_id FROM dbo.dim_category
        WHERE country_id = ? AND local_code = ?
        """,
        (country_id, int(code)),
    )
    found = bound.cursor.fetchone()
    if found is None or found[0] is None or int(found[0]) == int(remainder_id):
        return
    category_id = int(found[0])
    bound.cursor.execute(
        """
        UPDATE dbo.category_hand
        SET category_id = ?
        WHERE country_id = ? AND person_id = ? AND year = ? AND source_id = ?
        """,
        (category_id, country_id, int(bound.person_id), int(bound.year), key),
    )
    if int(bound.cursor.rowcount or 0) == 0:
        bound.cursor.execute(
            """
            INSERT INTO dbo.category_hand
                (country_id, person_id, year, source_id, category_id)
            VALUES (?, ?, ?, ?, ?)
            """,
            (country_id, int(bound.person_id), int(bound.year), key, category_id),
        )
    bound.conn.commit()


def forget_wiped_statements(
    cursor: Any,
    country_id: int,
    table: str,
    where_sql: str,
    where_params: tuple[Any, ...],
) -> None:
    """Drop stored hand rows for bookings a statement wipe is about to delete."""
    if not _table_exists(cursor):
        return
    if not where_sql:
        cursor.execute(
            "DELETE FROM dbo.category_hand WHERE country_id = ?",
            (int(country_id),),
        )
        return
    scoped = where_sql.replace(" WHERE ", "", 1)
    scoped = scoped.replace("account_id", "t.account_id").replace("person_id", "t.person_id")
    cursor.execute(
        f"""
        DELETE h
        FROM dbo.category_hand h
        WHERE h.country_id = ?
          AND EXISTS (
            SELECT 1 FROM {table} t
            WHERE t.person_id = h.person_id
              AND t.year = h.year
              AND t.source_id = h.source_id
              AND {scoped}
          )
        """,
        (int(country_id), *where_params),
    )

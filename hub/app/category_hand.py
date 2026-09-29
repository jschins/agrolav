"""Hand-made booking categories that survive a categorization wipe.

A row is written when someone sets a booking's category by hand. Wiping
categories resets ``dbo.transaction_*`` and leaves this table. Applying it
puts those categories back after cross-postings and the term run.
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


def capture_before_wipe(
    cursor: Any,
    country_id: int,
    table: str,
    where_sql: str,
    where_params: tuple[Any, ...],
) -> None:
    """Copy current hand bookings into ``dbo.category_hand`` before a reset.

    A hand row is ``modification`` 2 (and a legacy 3). A cross-posting (1) is
    not stored here. Rows already stored are left as they are. Categories with
    ``category_role`` ``rc``, ``sia``, ``sib``, ``siasib`` or ``cp`` are
    skipped: those are rebuilt by Calculate cross-postings, not by this log.
    """
    if not _table_exists(cursor):
        return
    scope = ""
    if where_sql:
        scoped = where_sql.replace(" WHERE ", "", 1)
        scoped = scoped.replace("account_id", "t.account_id").replace(
            "person_id", "t.person_id"
        )
        scope = f" AND {scoped}"
    cursor.execute(
        f"""
        INSERT INTO dbo.category_hand
            (country_id, person_id, year, source_id, category_id)
        SELECT ?, t.person_id, t.year, t.source_id, t.category_id
        FROM {table} t
        JOIN dbo.dim_category d
          ON d.category_id = t.category_id AND d.country_id = ?
        WHERE t.bank_id IS NULL
          AND t.modification >= 2
          AND (
            d.category_role IS NULL
            OR LOWER(LTRIM(RTRIM(d.category_role))) NOT IN
               (N'cp', N'rc', N'sia', N'sib', N'siasib', N'bank', N'no_hit',
                N'source', N'remainder', N'equity', N'never', N'profit',
                N'balance', N'last_booked')
          )
          AND NOT EXISTS (
            SELECT 1 FROM dbo.category_hand h
            WHERE h.country_id = ?
              AND h.person_id = t.person_id
              AND h.year = t.year
              AND h.source_id = t.source_id
          )
          {scope}
        """,
        (int(country_id), int(country_id), int(country_id), *where_params),
    )


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


def apply_hand_categorizations(center: str) -> dict[str, int]:
    """Write stored hand categories back onto the country's bookings."""
    from app import user_store
    from app.cross_postings import _refresh_category_totals
    from app.sql_catalog import coerce_center, country_for_center
    from shared.balance_values import transaction_table

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
    if not _table_exists(cursor):
        raise RuntimeError("dbo.category_hand is missing")
    table = transaction_table(country_id, cursor)
    if not table:
        raise RuntimeError(f"country {country_id} has no transaction table")
    cursor.execute(
        f"""
        SELECT DISTINCT t.person_id, t.year
        FROM {table} t
        JOIN dbo.category_hand h
          ON h.country_id = ?
         AND h.person_id = t.person_id
         AND h.year = t.year
         AND h.source_id = t.source_id
        """,
        (country_id,),
    )
    persons = {
        (int(person_id), int(year))
        for person_id, year in cursor.fetchall()
        if person_id is not None and year is not None
    }
    cursor.execute(
        f"""
        UPDATE t
        SET t.category_id = h.category_id,
            t.hit = NULL,
            t.modification = 2
        FROM {table} t
        JOIN dbo.category_hand h
          ON h.country_id = ?
         AND h.person_id = t.person_id
         AND h.year = t.year
         AND h.source_id = t.source_id
        """,
        (country_id,),
    )
    updated = int(cursor.rowcount or 0)
    if persons:
        _refresh_category_totals(cursor, table, persons, country_id)
    conn.commit()
    return {"updated": updated}

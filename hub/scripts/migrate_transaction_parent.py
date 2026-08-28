"""Add parent_source_id on every dbo.transaction_* table.

Does not DROP DATABASE. Stop is not required; hub can keep running.

  cd hub
  uv run python scripts/migrate_transaction_parent.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_TABLE = re.compile(r"^transaction_[A-Za-z][A-Za-z0-9_]*$")

HUB_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HUB_ROOT))
sys.path.insert(0, str(HUB_ROOT.parent / "shared"))


def _connect():
    from app import user_store

    if not user_store.database_url():
        raise SystemExit("Set HUB_DATABASE_URL (see hub/.env.example)")
    user_store.init_user_store()
    return user_store._sql_connect()


def main() -> None:
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT t.name
        FROM sys.tables t
        INNER JOIN sys.schemas s ON s.schema_id = t.schema_id
        WHERE s.name = N'dbo' AND t.name LIKE N'transaction[_]%'
        ORDER BY t.name
        """
    )
    tables = [str(row[0]) for row in cursor.fetchall()]
    if not tables:
        print("no dbo.transaction_* tables")
        return
    for name in tables:
        if not _TABLE.fullmatch(name):
            continue
        full = f"dbo.{name}"
        cursor.execute(f"SELECT COL_LENGTH(N'{full}', N'parent_source_id')")
        row = cursor.fetchone()
        if row and row[0]:
            print(f"{full}: parent_source_id already present")
            continue
        cursor.execute(f"ALTER TABLE {full} ADD parent_source_id NVARCHAR(128) NULL")
        conn.commit()
        print(f"{full}: added parent_source_id")
    print("migrate_transaction_parent complete")


if __name__ == "__main__":
    main()

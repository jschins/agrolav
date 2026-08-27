"""Add ``title`` on dbo.country and dbo.center; fill display titles.

Stop the hub first.

  cd hub
  uv run python scripts/add_login_title.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

HUB_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HUB_ROOT))
sys.path.insert(0, str(HUB_ROOT.parent / "shared"))

from app.user_store import display_title  # noqa: E402

SCHEMA_PATH = HUB_ROOT / "sql" / "add_login_title.sql"
_GO = re.compile(r"^\s*GO\s*$", re.I)
_USE = re.compile(r"^\s*USE\s+\w+\s*;?\s*$", re.I)


def _connect():
    from app import user_store

    if not user_store.database_url():
        raise SystemExit("Set HUB_DATABASE_URL (see hub/.env.example)")
    return user_store._sql_connect()


def _batches(sql: str) -> list[str]:
    current: list[str] = []
    out: list[str] = []
    for line in sql.splitlines():
        if _GO.fullmatch(line):
            text = "\n".join(current).strip()
            if text:
                out.append(text)
            current = []
            continue
        if _USE.fullmatch(line):
            continue
        current.append(line)
    text = "\n".join(current).strip()
    if text:
        out.append(text)
    return out


def _is_executable(batch: str) -> bool:
    for line in batch.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("--"):
            return True
    return False


def _pretty_titles(cursor) -> int:
    updated = 0
    specs = (
        ("country", "country_id"),
        ("center", "center_id"),
        ("person", "id"),
    )
    for table, key in specs:
        cursor.execute(
            f"""
            SELECT CASE WHEN OBJECT_ID(N'dbo.{table}', N'U') IS NULL THEN 0 ELSE 1 END
            """
        )
        if int(cursor.fetchone()[0]) == 0:
            continue
        cursor.execute(f"SELECT COL_LENGTH(N'dbo.{table}', N'title')")
        if cursor.fetchone()[0] is None:
            continue
        cursor.execute(f"SELECT {key}, username, title FROM dbo.{table}")
        rows = cursor.fetchall()
        for ident, username, title in rows:
            wanted = display_title(str(username or ""))
            current = str(title or "").strip()
            if not wanted or current == wanted:
                continue
            if current and current.casefold() != str(username or "").strip().casefold():
                continue
            cursor.execute(
                f"UPDATE dbo.{table} SET title = ? WHERE {key} = ?",
                wanted,
                int(ident),
            )
            updated += 1
    return updated


def main() -> None:
    sql = SCHEMA_PATH.read_text(encoding="utf-8")
    conn = _connect()
    cursor = conn.cursor()
    try:
        for i, batch in enumerate(_batches(sql), start=1):
            if not _is_executable(batch):
                continue
            cursor.execute(batch)
            while cursor.nextset():
                pass
            conn.commit()
            print(f"batch {i} ok")
        pretty = _pretty_titles(cursor)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    cursor.execute("SELECT country_id, username, title FROM dbo.country ORDER BY country_id")
    print("countries:")
    for row in cursor.fetchall():
        print(f"  {row[0]} {row[1]} -> {row[2]}")
    cursor.execute("SELECT center_id, username, title FROM dbo.center ORDER BY center_id")
    print("centers:")
    for row in cursor.fetchall():
        print(f"  {row[0]} {row[1]} -> {row[2]}")
    print(f"pretty titles updated: {pretty}")
    print("add_login_title complete")


if __name__ == "__main__":
    main()

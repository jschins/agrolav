"""Add enable_connection.person_id so a PEM can be stored before accounts exist.

  cd hub
  uv run python scripts/migrate_enable_connection_person.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

HUB_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HUB_ROOT))
sys.path.insert(0, str(HUB_ROOT.parent / "shared"))

SCHEMA_PATH = HUB_ROOT / "sql" / "migrate_enable_connection_person.sql"
_GO = re.compile(r"^\s*GO\s*$", re.I)
_USE = re.compile(r"^\s*USE\s+\w+\s*;?\s*$", re.I)


def _connect():
    from app import user_store

    if not user_store.database_url():
        raise SystemExit("Set HUB_DATABASE_URL (see hub/.env.example)")
    user_store.init_user_store()
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


def main() -> None:
    sql = SCHEMA_PATH.read_text(encoding="utf-8")
    conn = _connect()
    cursor = conn.cursor()
    try:
        for i, batch in enumerate(_batches(sql), start=1):
            if not _is_executable(batch):
                continue
            try:
                cursor.execute(batch)
                while cursor.nextset():
                    pass
            except Exception:
                print(f"migrate_enable_connection_person failed in batch {i}")
                raise
            conn.commit()
            print(f"batch {i} ok")
    except Exception:
        conn.rollback()
        raise
    cursor.execute(
        """
        SELECT
          SUM(CASE WHEN person_id IS NOT NULL THEN 1 ELSE 0 END),
          SUM(CASE WHEN pem IS NOT NULL THEN 1 ELSE 0 END),
          COUNT(*)
        FROM dbo.enable_connection
        """
    )
    owned, with_pem, total = cursor.fetchone()
    print(f"enable_connection: {int(total or 0)} (person_id set: {int(owned or 0)}, pem: {int(with_pem or 0)})")
    print("migrate_enable_connection_person complete")


if __name__ == "__main__":
    main()

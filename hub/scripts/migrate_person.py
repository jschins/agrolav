"""In-place migrate: dbo.app_user -> dbo.person (preserves bookings).

Stop the hub first. Run once per SQL instance (laptop, then VPS — or
BACKUP after the laptop run and restore on the VPS).

  cd hub
  uv run python scripts/migrate_person.py

Do not run load_phase_c.py on live data after this.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

HUB_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HUB_ROOT))
sys.path.insert(0, str(HUB_ROOT.parent / "shared"))

SCHEMA_PATH = HUB_ROOT / "sql" / "migrate_person.sql"
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
                print(f"migrate_person failed in batch {i}")
                raise
            conn.commit()
            print(f"batch {i} ok")
    except Exception:
        conn.rollback()
        raise
    cursor.execute("SELECT COUNT(*) FROM dbo.country")
    print(f"countries: {cursor.fetchone()[0]}")
    cursor.execute("SELECT COUNT(*) FROM dbo.center")
    print(f"centers: {cursor.fetchone()[0]}")
    cursor.execute("SELECT COUNT(*) FROM dbo.person")
    print(f"people: {cursor.fetchone()[0]}")
    cursor.execute("SELECT COUNT(*) FROM dbo.account")
    print(f"accounts: {cursor.fetchone()[0]}")
    cursor.execute("SELECT COUNT(*) FROM dbo.transaction_nederland")
    print(f"transactions_nederland: {cursor.fetchone()[0]}")
    cursor.execute("SELECT COUNT(*) FROM dbo.transaction_uk")
    print(f"transactions_uk: {cursor.fetchone()[0]}")
    print("migrate_person complete")


if __name__ == "__main__":
    main()

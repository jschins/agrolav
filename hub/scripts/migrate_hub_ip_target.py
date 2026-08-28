"""Add dbo.hub_ip.target (existing rows → 'B'). Stop the hub first.

  cd hub
  uv run python scripts/migrate_hub_ip_target.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

HUB_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HUB_ROOT))
sys.path.insert(0, str(HUB_ROOT.parent / "shared"))

SCHEMA_PATH = HUB_ROOT / "sql" / "migrate_hub_ip_target.sql"
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
                print(f"migrate_hub_ip_target failed in batch {i}")
                raise
            conn.commit()
            print(f"batch {i} ok")
    except Exception:
        conn.rollback()
        raise
    cursor.execute(
        "SELECT target, COUNT(*) FROM dbo.hub_ip GROUP BY target ORDER BY target"
    )
    print("hub_ip by target:")
    for target, n in cursor.fetchall():
        print(f"  {target}: {n}")
    print("migrate_hub_ip_target complete")


if __name__ == "__main__":
    main()

"""Fill dbo.person.password_hash from the default formula password.

Does not ALTER tables. Run after password_hash exists.

  cd hub
  uv run python scripts/backfill_person_password_hashes.py
"""
from __future__ import annotations

import sys
from pathlib import Path

HUB_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HUB_ROOT))
sys.path.insert(0, str(HUB_ROOT.parent / "shared"))

from app.user_store import default_password_hash  # noqa: E402


def main() -> None:
    from app import user_store

    if not user_store.database_url():
        raise SystemExit("Set HUB_DATABASE_URL (see hub/.env.example)")
    user_store.init_user_store()
    conn = user_store._sql_connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT username FROM dbo.person
        WHERE password_hash IS NULL OR LTRIM(RTRIM(password_hash)) = N''
        """
    )
    names = [str(row[0] or "").strip() for row in cursor.fetchall() if row[0]]
    if not names:
        print("no person rows need a password_hash")
        return
    updated = 0
    for name in names:
        cursor.execute(
            """
            UPDATE dbo.person SET password_hash = ?
            WHERE username = ? COLLATE Latin1_General_CI_AI
              AND (password_hash IS NULL OR LTRIM(RTRIM(password_hash)) = N'')
            """,
            (default_password_hash(name), name),
        )
        updated += cursor.rowcount
    conn.commit()
    print(f"wrote password_hash for {updated} person(s)")


if __name__ == "__main__":
    main()

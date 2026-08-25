"""Copy SQLite users.db into SQL Server dbo.app_user (run after SQL is up)."""
from __future__ import annotations

import sys
from pathlib import Path

HUB_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HUB_ROOT))
sys.path.insert(0, str(HUB_ROOT.parent / "shared"))


def main() -> None:
    from app import user_store

    if not user_store.database_url():
        raise SystemExit("Set HUB_DATABASE_URL (see hub/.env.example)")
    label = user_store.init_user_store()
    users = user_store.list_users()
    print(label)
    print(f"{len(users)} login(s):")
    for user in users:
        print(
            f"  {user['username']} access={user.get('access')} "
            f"country={user.get('country')!r} center={user.get('center')!r} "
            f"person={user.get('person')!r}"
        )


if __name__ == "__main__":
    main()

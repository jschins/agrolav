"""Stamp ``secret/*.pem`` onto ``dbo.enable_connection.pem``.

Connections are those already linked from ``dbo.account``. Run after
accounts have ``connection_id`` set (migrate or load_json_independence).

  cd hub
  uv run python scripts/load_private_keys.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

HUB_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HUB_ROOT))
sys.path.insert(0, str(HUB_ROOT.parent / "shared"))

from app.runtime import app_id_from_profile_data  # noqa: E402
from app.runtime import country_folder, data_root  # noqa: E402
from app.yearpath import has_person_layout  # noqa: E402

IGNORE_DIRS = frozenset(
    {
        "secret",
        "app",
        "frontend",
        "dist",
        "build",
        ".venv",
        "venv",
        "scripts",
        "node_modules",
        "__pycache__",
        ".git",
    }
)


class LoadError(RuntimeError):
    pass


def _connect():
    from app import user_store

    if not user_store.database_url():
        raise SystemExit("Set HUB_DATABASE_URL (see hub/.env.example)")
    user_store.init_user_store()
    return user_store._sql_connect()


def _dirs(path: Path) -> list[Path]:
    if not path.is_dir():
        return []
    return sorted(
        child
        for child in path.iterdir()
        if child.is_dir()
        and not child.name.startswith(".")
        and child.name not in IGNORE_DIRS
    )


def _read_profile(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _read_pem(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = path.read_bytes().decode("ascii", errors="strict")
    except OSError as exc:
        raise LoadError(f"Cannot read PEM: {path}: {exc}") from exc
    if "PRIVATE KEY" not in text:
        raise LoadError(f"File does not look like an RSA private key PEM: {path}")
    return text.strip() + "\n"


def _resolve_pem(secret_dir: Path) -> tuple[str, str] | None:
    """Return (app_id, pem_text) for the person pack, or None when no key."""
    pem_files = sorted(secret_dir.glob("*.pem"))
    if not pem_files:
        return None
    profile = _read_profile(secret_dir / "profile.json")
    app_id = app_id_from_profile_data(profile)
    if app_id:
        candidate = secret_dir / f"{app_id}.pem"
        if candidate.is_file():
            return app_id, _read_pem(candidate)
    if len(pem_files) == 1:
        path = pem_files[0]
        return path.stem.strip(), _read_pem(path)
    names = ", ".join(path.name for path in pem_files)
    raise LoadError(
        f"Expected one .pem in {secret_dir} (or a profile app_id match), found: {names}."
    )


def load_private_keys(cursor, root: Path) -> int:
    cursor.execute("SELECT OBJECT_ID(N'dbo.enable_connection', N'U')")
    if cursor.fetchone()[0] is None:
        raise LoadError("dbo.enable_connection missing.")
    cursor.execute("SELECT COL_LENGTH(N'dbo.enable_connection', N'pem')")
    if cursor.fetchone()[0] is None:
        raise LoadError("dbo.enable_connection.pem missing. Run migrate_enable_onto_account.py first.")

    cursor.execute(
        """
        SELECT id, username
        FROM dbo.person
        """
    )
    users: dict[str, int] = {}
    for person_id, username in cursor.fetchall():
        users[str(username)] = int(person_id)

    updated = 0
    skipped_people: list[str] = []

    cursor.execute("SELECT country_id, username FROM dbo.country")
    countries = [(int(cid), str(name)) for cid, name in cursor.fetchall()]
    for _country_id, country_name in countries:
        folder = country_folder(country_name) or country_name
        country_dir = root / folder
        if not country_dir.is_dir():
            continue
        for center_dir in _dirs(country_dir):
            for person_dir in _dirs(center_dir):
                if not has_person_layout(person_dir):
                    continue
                secret = person_dir / "secret"
                resolved = _resolve_pem(secret) if secret.is_dir() else None
                if resolved is None:
                    continue
                app_id, pem = resolved
                if not app_id:
                    raise LoadError(f"{secret}: PEM filename stem (Application ID) is empty")
                found = users.get(person_dir.name)
                if found is None:
                    skipped_people.append(str(secret))
                    continue
                cursor.execute(
                    """
                    UPDATE dbo.enable_connection
                    SET pem = ?, app_id = COALESCE(NULLIF(LTRIM(RTRIM(app_id)), N''), ?)
                    WHERE connection_id IN (
                        SELECT DISTINCT connection_id
                        FROM dbo.account
                        WHERE person_id = ? AND connection_id IS NOT NULL
                    )
                    """,
                    (pem, app_id, found),
                )
                updated += cursor.rowcount or 0

    if skipped_people:
        print(f"skipped (no person): {len(skipped_people)}")
        for item in skipped_people:
            print(f"  {item}")
    return updated


def main() -> None:
    root = data_root()
    conn = _connect()
    cursor = conn.cursor()
    try:
        count = load_private_keys(cursor, root)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    cursor.execute("SELECT COUNT(*) FROM dbo.enable_connection WHERE pem IS NOT NULL")
    stored = int(cursor.fetchone()[0])
    print(f"enable_connection pem updates: {count}")
    print(f"dbo.enable_connection rows with pem: {stored}")


if __name__ == "__main__":
    main()

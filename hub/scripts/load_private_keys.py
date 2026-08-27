"""Load ``secret/*.pem`` into ``dbo.private_key``.

Does not drop tables. Run after ``load_phase_c.py`` so ``dbo.person`` exists,
and after ``hub/sql/json_independence.sql`` so ``dbo.private_key`` exists.

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

from app.paths import app_id_from_profile_data  # noqa: E402
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
    cursor.execute("SELECT OBJECT_ID(N'dbo.private_key', N'U')")
    if cursor.fetchone()[0] is None:
        raise LoadError("dbo.private_key missing. Run hub/sql/json_independence.sql first.")

    cursor.execute(
        """
        SELECT id, username
        FROM dbo.person
        """
    )
    users: dict[str, int] = {}
    for person_id, username in cursor.fetchall():
        users[str(username)] = int(person_id)

    rows: list[tuple[int, str, str]] = []
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
                rows.append((found, app_id, pem))

    cursor.execute("DELETE FROM dbo.private_key")
    if rows:
        cursor.fast_executemany = True
        cursor.executemany(
            """
            INSERT INTO dbo.private_key (person_id, app_id, pem)
            VALUES (?, ?, ?)
            """,
            rows,
        )
        cursor.fast_executemany = False

    if skipped_people:
        print(f"skipped (no person): {len(skipped_people)}")
        for item in skipped_people:
            print(f"  {item}")
    return len(rows)


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
    cursor.execute("SELECT COUNT(*) FROM dbo.private_key")
    stored = int(cursor.fetchone()[0])
    print(f"private_key rows inserted: {count}")
    print(f"dbo.private_key rows now: {stored}")


if __name__ == "__main__":
    main()

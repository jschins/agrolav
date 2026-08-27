"""Load ``personal_categories.json`` into ``dbo.category_term`` (person_id set).

Does not drop tables or reload general (catalog) terms. Run after
``load_phase_c.py`` so ``dbo.person`` and ``dbo.dim_category`` exist.

  cd hub
  uv run python scripts/load_personal_categories.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

HUB_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HUB_ROOT))
sys.path.insert(0, str(HUB_ROOT.parent / "shared"))

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
_LOCAL_CODE = re.compile(r"^(\d{2})\b")


class LoadError(RuntimeError):
    pass


def _read_json_object(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LoadError(f"Invalid JSON: {path}: {exc}") from exc
    return data if isinstance(data, dict) else {}


def _category_map(data: dict[str, Any]) -> dict[str, list[str]]:
    nested = data.get("categories")
    raw = nested if isinstance(nested, dict) else data
    out: dict[str, list[str]] = {}
    for label, terms in raw.items():
        if label in ("table_header_terms", "abbreviations", "typerules"):
            continue
        if isinstance(terms, list):
            out[str(label)] = [str(term) for term in terms]
    return out


def _local_code(label: str) -> int | None:
    match = _LOCAL_CODE.match(str(label).strip())
    if match:
        return int(match.group(1))
    try:
        return int(str(label)[:2])
    except ValueError:
        return None


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


def _category_id(
    *,
    country_id: int,
    label: str,
    by_label: dict[tuple[int, str], int],
    by_code: dict[tuple[int, int], int],
) -> int | None:
    found = by_label.get((country_id, label))
    if found is not None:
        return found
    code = _local_code(label)
    if code is None:
        return None
    return by_code.get((country_id, code))


def load_personal_terms(cursor, root: Path) -> int:
    cursor.execute("SELECT OBJECT_ID(N'dbo.category_term', N'U')")
    if cursor.fetchone()[0] is None:
        raise LoadError("dbo.category_term missing. Run load_phase_c.py first.")

    cursor.execute(
        """
        SELECT d.country_id, d.category_id, d.label, d.local_code
        FROM dbo.dim_category d
        """
    )
    by_label: dict[tuple[int, str], int] = {}
    by_code: dict[tuple[int, int], int] = {}
    for country_id, category_id, label, local_code in cursor.fetchall():
        by_label[(int(country_id), str(label))] = int(category_id)
        by_code[(int(country_id), int(local_code))] = int(category_id)

    cursor.execute(
        """
        SELECT id, username, country_id
        FROM dbo.person
        """
    )
    users: dict[str, tuple[int, int]] = {}
    for person_id, username, country_id in cursor.fetchall():
        users[str(username)] = (int(person_id), int(country_id))

    rows: list[tuple[int, int, str, int]] = []
    skipped_people: list[str] = []
    skipped_labels: list[str] = []

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
                path = person_dir / "secret" / "personal_categories.json"
                payload = _category_map(_read_json_object(path))
                if not payload:
                    continue
                found = users.get(person_dir.name)
                if found is None:
                    skipped_people.append(str(path))
                    continue
                person_id, user_country_id = found
                for label, terms in payload.items():
                    category_id = _category_id(
                        country_id=user_country_id,
                        label=label,
                        by_label=by_label,
                        by_code=by_code,
                    )
                    if category_id is None:
                        skipped_labels.append(f"{person_dir.name}: {label}")
                        continue
                    sort_order = 0
                    for raw in terms:
                        text = str(raw).strip()
                        if not text:
                            continue
                        if len(text) > 256:
                            raise LoadError(
                                f"{path}: term exceeds 256 characters: {text[:40]!r}…"
                            )
                        rows.append((category_id, person_id, text, sort_order))
                        sort_order += 1

    cursor.execute("DELETE FROM dbo.category_term WHERE person_id IS NOT NULL")
    if rows:
        cursor.fast_executemany = True
        cursor.executemany(
            """
            INSERT INTO dbo.category_term (category_id, person_id, term, sort_order)
            VALUES (?, ?, ?, ?)
            """,
            rows,
        )
        cursor.fast_executemany = False

    if skipped_people:
        print(f"skipped (no person): {len(skipped_people)}")
        for item in skipped_people:
            print(f"  {item}")
    if skipped_labels:
        print(f"skipped (unknown category): {len(skipped_labels)}")
        for item in skipped_labels:
            print(f"  {item}")
    return len(rows)


def main() -> None:
    root = data_root()
    conn = _connect()
    cursor = conn.cursor()
    try:
        count = load_personal_terms(cursor, root)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    cursor.execute(
        "SELECT COUNT(*) FROM dbo.category_term WHERE person_id IS NOT NULL"
    )
    stored = int(cursor.fetchone()[0])
    print(f"personal category_term rows inserted: {count}")
    print(f"dbo.category_term personal rows now: {stored}")


if __name__ == "__main__":
    main()

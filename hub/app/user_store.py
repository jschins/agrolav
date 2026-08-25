"""SQLite-backed login users."""
from __future__ import annotations

import os
import sqlite3
import threading
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from shared.user_access import ACCESS_REGIONAL_ADMIN, enrich_user_record, parse_centers

from app.runtime import data_root

USERS_DB_FILENAME = "users.db"
_LOCK = threading.RLock()
_CONN: sqlite3.Connection | None = None

FORMAT_SECRET = "secret"
FORMAT_MULTIPLE = "multiple"

# Stable upload-grant token (legacy scrypt string still accepted by /upload?t=…).
DEFAULT_UPLOAD_TOKEN = (
    "scrypt$16384$8$1$DqM8xC0un6VYeM0i4FwKcQ$sUhw7V7Wfd4Rz0PB9RoWEHVIVcNpNId2GM5QIU-8_fQ"
)

_TABLE_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL COLLATE NOCASE UNIQUE,
    title TEXT,
    country TEXT,
    center TEXT,
    person TEXT,
    format TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


def users_db_path() -> Path:
    env = os.environ.get("HUB_USERS_DB", "").strip()
    if env:
        return Path(env).resolve()
    return (data_root() / USERS_DB_FILENAME).resolve()


def password_for_username(username: str) -> str:
    """Login password is identical to the username (temporary hard-coded rule)."""
    return str(username or "").strip()


def is_single_bank_format(fmt: str | None) -> bool:
    """True when ``format`` is a concrete bank CSV layout (not empty/secret/multiple)."""
    value = str(fmt or "").strip().lower()
    if not value or value in (FORMAT_SECRET, FORMAT_MULTIPLE):
        return False
    from app.core.bank_csv import is_csv_bank_format

    return is_csv_bank_format(value)


def as_date_only(value: str | None) -> str | None:
    """Normalize a date/datetime string to ``YYYY-MM-DD``, or ``None`` if unusable."""
    text = str(value or "").strip()
    if not text:
        return None
    # ISO datetime / date
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        candidate = text[:10]
        try:
            date.fromisoformat(candidate)
            return candidate
        except ValueError:
            pass
    # App transaction dates DD-MM-YYYY
    if len(text) >= 10 and text[2] == "-" and text[5] == "-":
        day, month, year = text[0:2], text[3:5], text[6:10]
        candidate = f"{year}-{month}-{day}"
        try:
            date.fromisoformat(candidate)
            return candidate
        except ValueError:
            pass
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed.date().isoformat()
    except ValueError:
        return None


def latest_transaction_date(transactions: Iterable[Any]) -> str | None:
    """Latest ``date`` among transaction dicts, as ``YYYY-MM-DD``."""
    best: str | None = None
    for item in transactions:
        if not isinstance(item, dict):
            continue
        iso = as_date_only(str(item.get("date") or ""))
        if iso and (best is None or iso > best):
            best = iso
    return best


def _utc_today() -> str:
    """Calendar date in UTC as ``YYYY-MM-DD`` (for ``created_at`` on insert)."""
    return datetime.now(timezone.utc).date().isoformat()


def _row_to_user(row: sqlite3.Row) -> dict[str, Any]:
    keys = set(row.keys())
    center = ""
    if "center" in keys and row["center"] is not None:
        center = str(row["center"])
    elif "workspace" in keys and row["workspace"] is not None:
        center = str(row["workspace"])
    country = str(row["country"] or "") if "country" in keys and row["country"] is not None else ""
    return {
        "id": int(row["id"]),
        "username": str(row["username"] or ""),
        "title": str(row["title"] or "") if "title" in keys else "",
        "country": country,
        "center": center,
        "person": str(row["person"]) if row["person"] is not None else "",
        "format": (
            str(row["format"]).strip()
            if "format" in keys and row["format"] is not None
            else ""
        ),
    }


def _public_user(user: dict[str, Any]) -> dict[str, Any]:
    rec = enrich_user_record(user)
    if rec["access"] == ACCESS_REGIONAL_ADMIN and not rec["centers"] and rec["country"]:
        from app.store import list_centers

        rec["centers"] = list_centers(rec["country"])
        if rec["centers"] and not rec["center"]:
            rec["center"] = rec["centers"][0]
    return rec


def _strip_timestamps_to_dates(conn: sqlite3.Connection) -> None:
    """Keep ``created_at`` / ``updated_at`` as date-only (``YYYY-MM-DD``)."""
    conn.execute(
        """
        UPDATE users
        SET created_at = substr(created_at, 1, 10)
        WHERE created_at IS NOT NULL AND length(created_at) > 10
        """
    )
    conn.execute(
        """
        UPDATE users
        SET updated_at = substr(updated_at, 1, 10)
        WHERE updated_at IS NOT NULL AND length(updated_at) > 10
        """
    )


def _table_columns(conn: sqlite3.Connection) -> set[str]:
    return {str(row[1]) for row in conn.execute("PRAGMA table_info(users)")}


def _migrate_schema(conn: sqlite3.Connection) -> None:
    cols = _table_columns(conn)
    if not cols:
        return
    if "workspace" in cols and "center" not in cols:
        conn.execute("ALTER TABLE users RENAME COLUMN workspace TO center")
        cols = _table_columns(conn)
    if "center" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN center TEXT")
    if "country" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN country TEXT")
    conn.execute("DROP INDEX IF EXISTS idx_users_person_workspace")
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_users_person_center
        ON users(person COLLATE NOCASE, center COLLATE NOCASE)
        """
    )


def _csv_cell(row: dict[str, str], *keys: str) -> str:
    for key in keys:
        if key in row and row[key] is not None:
            return str(row[key]).strip()
    return ""


def _import_users_csv(conn: sqlite3.Connection) -> None:
    """Load ``users.csv`` next to ``users.db`` when present (exported layout)."""
    import csv

    path = users_db_path().parent / "users.csv"
    if not path.is_file():
        return
    today = _utc_today()
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for raw in reader:
            name = _csv_cell(raw, "username")
            if not name:
                continue
            country = _csv_cell(raw, "country") or None
            center = _csv_cell(raw, "center", "workspace") or None
            person = _csv_cell(raw, "person") or None
            fmt = _csv_cell(raw, "format") or None
            created = _csv_cell(raw, "created_at") or today
            updated = _csv_cell(raw, "updated_at") or created
            row = conn.execute(
                "SELECT id FROM users WHERE username = ? COLLATE NOCASE",
                (name,),
            ).fetchone()
            if row:
                conn.execute(
                    """
                    UPDATE users
                    SET country = ?, center = ?, person = ?, format = ?,
                        created_at = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        country,
                        center,
                        person,
                        fmt,
                        created[:10],
                        updated[:10],
                        int(row["id"]),
                    ),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO users
                        (username, title, country, center, person, format, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        name,
                        _csv_cell(raw, "title") or None,
                        country,
                        center,
                        person,
                        fmt,
                        created[:10],
                        updated[:10],
                    ),
                )


def _connect() -> sqlite3.Connection:
    global _CONN
    if _CONN is not None:
        return _CONN
    path = users_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    # Table only: an existing users.db may still have ``workspace``. Creating
    # idx_users_person_center here would fail before the rename migration.
    conn.executescript(_TABLE_SCHEMA)
    _migrate_schema(conn)
    _import_users_csv(conn)
    _strip_timestamps_to_dates(conn)
    conn.commit()
    _CONN = conn
    return conn


def init_user_store() -> Path:
    """Open the database and ensure schema exists."""
    with _LOCK:
        _connect()
        return users_db_path()


def find_user(username: str) -> dict[str, Any] | None:
    needle = (username or "").strip()
    if not needle:
        return None
    with _LOCK:
        init_user_store()
        row = _connect().execute(
            "SELECT * FROM users WHERE username = ? COLLATE NOCASE",
            (needle,),
        ).fetchone()
    return _row_to_user(row) if row else None


def authenticate(username: str, password: str) -> dict[str, Any] | None:
    user = find_user(username)
    if user is None:
        return None
    expected = password_for_username(str(user.get("username") or ""))
    if str(password or "") != expected:
        return None
    return user


def authenticate_public(username: str, password: str) -> dict[str, Any] | None:
    user = authenticate(username, password)
    return _public_user(user) if user else None


def list_users() -> list[dict[str, Any]]:
    with _LOCK:
        init_user_store()
        rows = _connect().execute(
            "SELECT * FROM users ORDER BY username COLLATE NOCASE"
        ).fetchall()
    return [_public_user(_row_to_user(row)) for row in rows]


def upsert_user(
    *,
    username: str,
    title: str = "",
    center: str = "",
    country: str = "",
    person: str = "",
) -> dict[str, Any]:
    """Insert or update a user. Does not change ``format`` or ``updated_at`` on update."""
    name = (username or "").strip()
    if not name:
        raise ValueError("username is required")
    title_s = (title or "").strip() or None
    center_s = (center or "").strip() or None
    country_s = (country or "").strip() or None
    person_s = (person or "").strip() or None
    today = _utc_today()
    with _LOCK:
        init_user_store()
        conn = _connect()
        row = conn.execute(
            "SELECT id FROM users WHERE username = ? COLLATE NOCASE",
            (name,),
        ).fetchone()
        if row:
            conn.execute(
                """
                UPDATE users
                SET title = ?, country = ?, center = ?, person = ?
                WHERE id = ?
                """,
                (title_s, country_s, center_s, person_s, int(row["id"])),
            )
        else:
            conn.execute(
                """
                INSERT INTO users
                    (username, title, country, center, person, format, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, NULL, ?, ?)
                """,
                (name, title_s, country_s, center_s, person_s, today, today),
            )
        conn.commit()
    user = find_user(name)
    if user is None:
        raise RuntimeError(f"failed to upsert user {name!r}")
    return _public_user(user)


def upsert_personal_login(
    *,
    center: str,
    person: str,
    country: str = "",
) -> dict[str, Any]:
    folder = (person or "").strip()
    ws = (center or "").strip()
    if not folder or not ws:
        raise ValueError("center and person are required")
    from app.runtime import active_country, resolve_country_for_center

    country_s = (country or active_country() or resolve_country_for_center(ws) or "").strip()
    return upsert_user(
        username=folder,
        center=ws,
        country=country_s,
        person=folder,
    )


def set_user_format(*, username: str, format: str) -> dict[str, Any] | None:
    """Set ``format`` for an existing user (does not change ``updated_at``)."""
    name = (username or "").strip()
    fmt = (format or "").strip()
    if not name or not fmt:
        return None
    with _LOCK:
        init_user_store()
        conn = _connect()
        row = conn.execute(
            "SELECT id FROM users WHERE username = ? COLLATE NOCASE",
            (name,),
        ).fetchone()
        if not row:
            return None
        conn.execute(
            "UPDATE users SET format = ? WHERE id = ?",
            (fmt, int(row["id"])),
        )
        conn.commit()
    user = find_user(name)
    return _public_user(user) if user else None


def set_user_updated_at(*, username: str, date: str | None) -> dict[str, Any] | None:
    """Set ``updated_at`` to a date-only value after a successful refresh/upload."""
    name = (username or "").strip()
    iso = as_date_only(date)
    if not name or not iso:
        return None
    with _LOCK:
        init_user_store()
        conn = _connect()
        row = conn.execute(
            "SELECT id FROM users WHERE username = ? COLLATE NOCASE",
            (name,),
        ).fetchone()
        if not row:
            return None
        conn.execute(
            "UPDATE users SET updated_at = ? WHERE id = ?",
            (iso, int(row["id"])),
        )
        conn.commit()
    user = find_user(name)
    return _public_user(user) if user else None


def upload_token_by_person_center() -> dict[tuple[str, str], str]:
    """Map ``(person, center)`` → upload token for personal users."""
    with _LOCK:
        init_user_store()
        rows = _connect().execute(
            """
            SELECT person, center
            FROM users
            WHERE person IS NOT NULL AND person != ''
              AND center IS NOT NULL AND center != ''
            """
        ).fetchall()
    out: dict[tuple[str, str], str] = {}
    for row in rows:
        person = str(row["person"] or "").strip()
        raw_ws = str(row["center"] or "").strip()
        if not person:
            continue
        for center in parse_centers(raw_ws) or ([raw_ws] if raw_ws else []):
            if center:
                out[(person, center)] = DEFAULT_UPLOAD_TOKEN
    return out

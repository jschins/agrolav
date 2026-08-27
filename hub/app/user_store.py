"""Login users: SQL Server country / center / person when ``HUB_DATABASE_URL`` is set, else SQLite."""
from __future__ import annotations

import os
import re
import sqlite3
import threading
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from shared.user_access import ACCESS_COUNTRY, deduce_access, enrich_user_record, parse_centers

from app.runtime import data_root

USERS_DB_FILENAME = "users.db"
_LOCK = threading.RLock()
_SQLITE: sqlite3.Connection | None = None
_SQL = None  # pyodbc connection

FORMAT_SECRET = "secret"
FORMAT_MULTIPLE = "multiple"

# Stable upload-grant token (legacy scrypt string still accepted by /upload?t=…).
DEFAULT_UPLOAD_TOKEN = (
    "scrypt$16384$8$1$DqM8xC0un6VYeM0i4FwKcQ$sUhw7V7Wfd4Rz0PB9RoWEHVIVcNpNId2GM5QIU-8_fQ"
)

_SQLITE_SCHEMA = """
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

_SQL_PERSON_SELECT = """
SELECT
    p.id,
    p.username COLLATE Latin1_General_CI_AI AS username,
    p.title,
    p.number_of_accounts,
    c.username COLLATE Latin1_General_CI_AI AS country,
    n.username COLLATE Latin1_General_CI_AI AS center,
    p.username COLLATE Latin1_General_CI_AI AS person
FROM dbo.person p
INNER JOIN dbo.country c ON c.country_id = p.country_id
INNER JOIN dbo.center n ON n.center_id = p.center_id
"""

_SQL_CENTER_SELECT = """
SELECT
    n.center_id AS id,
    n.username COLLATE Latin1_General_CI_AI AS username,
    n.username COLLATE Latin1_General_CI_AI AS title,
    CAST(NULL AS INT) AS number_of_accounts,
    c.username COLLATE Latin1_General_CI_AI AS country,
    n.username COLLATE Latin1_General_CI_AI AS center,
    CAST(N'' AS NVARCHAR(128)) COLLATE Latin1_General_CI_AI AS person
FROM dbo.center n
INNER JOIN dbo.country c ON c.country_id = n.country_id
"""

_SQL_COUNTRY_SELECT = """
SELECT
    c.country_id AS id,
    c.username COLLATE Latin1_General_CI_AI AS username,
    c.username COLLATE Latin1_General_CI_AI AS title,
    CAST(NULL AS INT) AS number_of_accounts,
    c.username COLLATE Latin1_General_CI_AI AS country,
    CAST(NULL AS NVARCHAR(64)) COLLATE Latin1_General_CI_AI AS center,
    CAST(N'' AS NVARCHAR(128)) COLLATE Latin1_General_CI_AI AS person
FROM dbo.country c
"""

_SQL_USER_SELECT = f"""
{_SQL_PERSON_SELECT}
UNION ALL
{_SQL_CENTER_SELECT}
UNION ALL
{_SQL_COUNTRY_SELECT}
"""


def _load_dotenv() -> None:
    path = Path(__file__).resolve().parents[1] / ".env"
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#") or "=" not in raw:
            continue
        key, _, val = raw.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val


_load_dotenv()


def database_url() -> str:
    return os.environ.get("HUB_DATABASE_URL", "").strip()


def _use_sqlserver() -> bool:
    return bool(database_url())


def users_db_path() -> Path:
    env = os.environ.get("HUB_USERS_DB", "").strip()
    if env:
        return Path(env).resolve()
    return (data_root() / USERS_DB_FILENAME).resolve()


def store_label() -> str:
    if _use_sqlserver():
        return "sqlserver:dbo.person"
    return str(users_db_path())


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
    if isinstance(value, date) and not isinstance(value, datetime):
        return value.isoformat()
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        candidate = text[:10]
        try:
            date.fromisoformat(candidate)
            return candidate
        except ValueError:
            pass
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
    return datetime.now(timezone.utc).date().isoformat()


def _empty_to_null(value: str | None) -> str | None:
    text = str(value or "").strip()
    return text or None


def _cell(row: Any, key: str) -> Any:
    if isinstance(row, dict):
        return row.get(key)
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):
        return None


def _row_to_user(row: Any) -> dict[str, Any]:
    center_raw = _cell(row, "center")
    if center_raw is None:
        center_raw = _cell(row, "workspace")
    country_raw = _cell(row, "country")
    title_raw = _cell(row, "title")
    format_raw = _cell(row, "format")
    ident = _cell(row, "id")
    username = str(_cell(row, "username") or "")
    person_raw = _cell(row, "person")
    accounts_raw = _cell(row, "number_of_accounts")
    if person_raw is not None and str(person_raw).strip():
        person = str(person_raw).strip()
    elif accounts_raw is not None:
        person = username
    else:
        person = ""
    return {
        "id": int(ident) if ident is not None else 0,
        "username": username,
        "title": str(title_raw or ""),
        "country": str(country_raw or ""),
        "center": str(center_raw or ""),
        "person": person,
        "format": str(format_raw or "").strip(),
        "number_of_accounts": (
            int(accounts_raw) if accounts_raw is not None else None
        ),
    }


def _public_user(user: dict[str, Any]) -> dict[str, Any]:
    rec = enrich_user_record(user)
    from app.runtime import country_folder
    from app.store import list_centers, list_countries

    folder = country_folder(rec.get("country") or "")
    if not folder:
        guessed = country_folder(rec.get("username") or "")
        known = {name.lower() for name in list_countries()}
        if guessed and guessed.lower() in known:
            folder = guessed
    if folder:
        rec["country"] = folder
        rec["access"] = deduce_access(
            person=rec["person"], center=rec["center"], country=folder
        )
    if rec["access"] == ACCESS_COUNTRY and rec["country"]:
        rec["centers"] = list_centers(rec["country"])
    return rec


def _master_url(url: str) -> str:
    if re.search(r"DATABASE=", url, flags=re.I):
        return re.sub(r"DATABASE=[^;]*", "DATABASE=master", url, count=1, flags=re.I)
    return url.rstrip(";") + ";DATABASE=master"


def _database_name(url: str) -> str:
    match = re.search(r"DATABASE=([^;]+)", url, flags=re.I)
    name = (match.group(1) if match else "agrolav").strip()
    return name or "agrolav"


def _pyodbc():
    import pyodbc

    return pyodbc


def _connect_urls(url: str) -> list[str]:
    """Prefer Driver 18; fall back if that driver is not installed yet."""
    urls = [url]
    if "ODBC Driver 18" in url:
        urls.append(url.replace("ODBC Driver 18 for SQL Server", "ODBC Driver 17 for SQL Server"))
        urls.append(url.replace("DRIVER={ODBC Driver 18 for SQL Server}", "DRIVER={SQL Server}"))
    return urls


def _sql_connect():
    global _SQL
    if _SQL is not None:
        return _SQL
    pyodbc = _pyodbc()
    url = database_url()
    db_name = _database_name(url)
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", db_name):
        raise ValueError(f"Invalid SQL Server database name: {db_name!r}")
    last_err: Exception | None = None
    conn = None
    for _attempt in range(24):
        for candidate in _connect_urls(url):
            try:
                master = pyodbc.connect(_master_url(candidate), autocommit=True, timeout=8)
                try:
                    master.cursor().execute(
                        f"IF DB_ID(N'{db_name}') IS NULL CREATE DATABASE [{db_name}]"
                    )
                finally:
                    master.close()
                conn = pyodbc.connect(candidate, autocommit=False, timeout=8)
                break
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                conn = None
        if conn is not None:
            break
        time.sleep(5)
    if conn is None:
        raise RuntimeError(
            "Could not connect to SQL Server. Start Docker Desktop, then "
            "`docker compose -f docker-compose.sqlserver.yml up -d`, "
            "and install ODBC Driver 18. Last error: "
            f"{last_err}"
        ) from last_err
    _SQL = conn
    _copy_sqlite_into_sqlserver_if_empty()
    return conn


def _sql_cursor_row(cursor, raw: Any) -> dict[str, Any]:
    cols = [item[0] for item in cursor.description]
    return dict(zip(cols, raw))


def _sql_country_id(cursor, folder: str) -> int | None:
    from app.runtime import country_folder

    name = country_folder(folder) or (folder or "").strip()
    if not name:
        return None
    cursor.execute(
        "SELECT country_id FROM dbo.country WHERE username = ? COLLATE Latin1_General_CI_AI",
        (name,),
    )
    row = cursor.fetchone()
    return int(row[0]) if row else None


def _sql_center_id(cursor, country_id: int, folder: str) -> int | None:
    name = (folder or "").strip()
    if not name:
        return None
    cursor.execute(
        """
        SELECT center_id FROM dbo.center
        WHERE country_id = ? AND username = ? COLLATE Latin1_General_CI_AI
        """,
        (country_id, name),
    )
    row = cursor.fetchone()
    return int(row[0]) if row else None


def _sql_username_taken(cursor, username: str, *, except_person_id: int | None = None) -> bool:
    name = (username or "").strip()
    if not name:
        return False
    cursor.execute(
        "SELECT 1 FROM dbo.country WHERE username = ? COLLATE Latin1_General_CI_AI",
        (name,),
    )
    if cursor.fetchone():
        return True
    cursor.execute(
        "SELECT 1 FROM dbo.center WHERE username = ? COLLATE Latin1_General_CI_AI",
        (name,),
    )
    if cursor.fetchone():
        return True
    if except_person_id is None:
        cursor.execute(
            "SELECT 1 FROM dbo.person WHERE username = ? COLLATE Latin1_General_CI_AI",
            (name,),
        )
    else:
        cursor.execute(
            """
            SELECT 1 FROM dbo.person
            WHERE username = ? COLLATE Latin1_General_CI_AI AND id <> ?
            """,
            (name, except_person_id),
        )
    return cursor.fetchone() is not None


def _sqlite_open_readonly() -> sqlite3.Connection | None:
    path = users_db_path()
    if not path.is_file():
        return None
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _copy_sqlite_into_sqlserver_if_empty() -> int:
    cursor = _SQL.cursor()
    cursor.execute("SELECT OBJECT_ID(N'dbo.person', N'U')")
    if cursor.fetchone()[0] is None:
        return 0
    count = int(cursor.execute("SELECT COUNT(*) FROM dbo.person").fetchone()[0])
    if count:
        return 0
    src = _sqlite_open_readonly()
    if src is None:
        return 0
    try:
        cols = {str(row[1]) for row in src.execute("PRAGMA table_info(users)")}
        if not cols:
            return 0
        inserted = 0
        for row in src.execute("SELECT * FROM users"):
            keys = set(row.keys())
            username = str(row["username"] or "").strip()
            if not username:
                continue
            center = ""
            if "center" in keys and row["center"] is not None:
                center = str(row["center"])
            elif "workspace" in keys and row["workspace"] is not None:
                center = str(row["workspace"])
            country = str(row["country"] or "") if "country" in keys else ""
            person = str(row["person"] or "") if "person" in keys else ""
            title = str(row["title"] or "") if "title" in keys else ""
            created = as_date_only(str(row["created_at"] or "")) or _utc_today()
            updated = as_date_only(str(row["updated_at"] or "")) or created
            country_id = _sql_country_id(cursor, country or username)
            if country_id is None:
                continue
            center_id = _sql_center_id(cursor, country_id, center) if center else None
            if not person or center_id is None:
                continue
            cursor.execute(
                """
                INSERT INTO dbo.person
                    (username, title, country_id, center_id, number_of_accounts, created_at, updated_at)
                VALUES (?, ?, ?, ?, 0, ?, ?)
                """,
                (
                    username,
                    title.strip() or username,
                    country_id,
                    center_id,
                    created,
                    updated,
                ),
            )
            inserted += 1
        _SQL.commit()
        print(f"copied {inserted} person(s) from SQLite into dbo.person")
        return inserted
    finally:
        src.close()


def _sqlite_connect() -> sqlite3.Connection:
    global _SQLITE
    if _SQLITE is not None:
        return _SQLITE
    path = users_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SQLITE_SCHEMA)
    _migrate_sqlite_schema(conn)
    _import_users_csv(conn)
    _strip_sqlite_timestamps(conn)
    conn.commit()
    _SQLITE = conn
    return conn


def _strip_sqlite_timestamps(conn: sqlite3.Connection) -> None:
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


def _sqlite_columns(conn: sqlite3.Connection) -> set[str]:
    return {str(row[1]) for row in conn.execute("PRAGMA table_info(users)")}


def _migrate_sqlite_schema(conn: sqlite3.Connection) -> None:
    cols = _sqlite_columns(conn)
    if not cols:
        return
    if "workspace" in cols and "center" not in cols:
        conn.execute("ALTER TABLE users RENAME COLUMN workspace TO center")
        cols = _sqlite_columns(conn)
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


def init_user_store() -> str:
    """Open the user store (SQL Server or SQLite) and ensure schema exists."""
    with _LOCK:
        if _use_sqlserver():
            conn = _sql_connect()
            cursor = conn.cursor()
            cursor.execute("SELECT OBJECT_ID(N'dbo.person', N'U')")
            if cursor.fetchone()[0] is None:
                raise RuntimeError(
                    "dbo.person missing. Stop the hub and run "
                    "`uv run python scripts/migrate_person.py` from hub/ "
                    "(fresh empty DB: load_phase_c.py)."
                )
        else:
            _sqlite_connect()
        return store_label()


def find_user(username: str) -> dict[str, Any] | None:
    needle = (username or "").strip()
    if not needle:
        return None
    with _LOCK:
        init_user_store()
        if _use_sqlserver():
            cursor = _SQL.cursor()
            row = None
            for sql in (
                _SQL_PERSON_SELECT + " WHERE p.username = ? COLLATE Latin1_General_CI_AI",
                _SQL_CENTER_SELECT + " WHERE n.username = ? COLLATE Latin1_General_CI_AI",
                _SQL_COUNTRY_SELECT + " WHERE c.username = ? COLLATE Latin1_General_CI_AI",
            ):
                cursor.execute(sql, (needle,))
                raw = cursor.fetchone()
                if raw:
                    row = _sql_cursor_row(cursor, raw)
                    break
        else:
            row = _SQLITE.execute(
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
        if _use_sqlserver():
            cursor = _SQL.cursor()
            cursor.execute(
                "SELECT * FROM (" + _SQL_USER_SELECT + ") u ORDER BY u.username"
            )
            rows = [_sql_cursor_row(cursor, raw) for raw in cursor.fetchall()]
        else:
            rows = _SQLITE.execute(
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
    title_s = _empty_to_null(title)
    center_s = _empty_to_null(center)
    country_s = _empty_to_null(country)
    person_s = _empty_to_null(person)
    today = _utc_today()
    with _LOCK:
        init_user_store()
        if _use_sqlserver():
            cursor = _SQL.cursor()
            if not person_s:
                raise ValueError("SQL Server person login requires a person folder")
            country_id = _sql_country_id(cursor, country_s or name)
            if country_id is None:
                raise ValueError(f"Unknown country {country_s or name!r}")
            center_id = _sql_center_id(cursor, country_id, center_s or "") if center_s else None
            if center_id is None:
                raise ValueError(f"Unknown center {center_s!r} for country_id={country_id}")
            cursor.execute(
                "SELECT id FROM dbo.person WHERE username = ? COLLATE Latin1_General_CI_AI",
                (name,),
            )
            row = cursor.fetchone()
            person_id = int(row[0]) if row else None
            if _sql_username_taken(cursor, name, except_person_id=person_id):
                raise ValueError(f"Username already used: {name}")
            title_value = (title_s or name)
            if person_id is not None:
                cursor.execute(
                    """
                    UPDATE dbo.person
                    SET title = ?, country_id = ?, center_id = ?
                    WHERE id = ?
                    """,
                    (title_value, country_id, center_id, person_id),
                )
            else:
                cursor.execute(
                    """
                    INSERT INTO dbo.person
                        (username, title, country_id, center_id, number_of_accounts, created_at, updated_at)
                    VALUES (?, ?, ?, ?, 0, ?, ?)
                    """,
                    (name, title_value, country_id, center_id, today, today),
                )
            _SQL.commit()
        else:
            conn = _SQLITE
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
    name = (username or "").strip()
    fmt = (format or "").strip()
    if not name or not fmt:
        return None
    with _LOCK:
        init_user_store()
        if _use_sqlserver():
            cursor = _SQL.cursor()
            cursor.execute(
                "SELECT id FROM dbo.person WHERE username = ? COLLATE Latin1_General_CI_AI",
                (name,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            cursor.execute(
                "UPDATE dbo.account SET format = ? WHERE person_id = ?",
                (fmt, int(row[0])),
            )
            _SQL.commit()
        else:
            conn = _SQLITE
            row = conn.execute(
                "SELECT id FROM users WHERE username = ? COLLATE NOCASE",
                (name,),
            ).fetchone()
            if not row:
                return None
            conn.execute("UPDATE users SET format = ? WHERE id = ?", (fmt, int(row["id"])))
            conn.commit()
    user = find_user(name)
    return _public_user(user) if user else None


def set_user_updated_at(*, username: str, date: str | None) -> dict[str, Any] | None:
    name = (username or "").strip()
    iso = as_date_only(date)
    if not name or not iso:
        return None
    with _LOCK:
        init_user_store()
        if _use_sqlserver():
            cursor = _SQL.cursor()
            cursor.execute(
                "SELECT id FROM dbo.person WHERE username = ? COLLATE Latin1_General_CI_AI",
                (name,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            cursor.execute(
                "UPDATE dbo.person SET updated_at = ? WHERE id = ?",
                (iso, int(row[0])),
            )
            _SQL.commit()
        else:
            conn = _SQLITE
            row = conn.execute(
                "SELECT id FROM users WHERE username = ? COLLATE NOCASE",
                (name,),
            ).fetchone()
            if not row:
                return None
            conn.execute("UPDATE users SET updated_at = ? WHERE id = ?", (iso, int(row["id"])))
            conn.commit()
    user = find_user(name)
    return _public_user(user) if user else None


def list_accounts_for_username(username: str) -> list[dict[str, str]]:
    """IBANs (and balances) for a person pack."""
    name = (username or "").strip()
    if not name or not _use_sqlserver():
        return []
    with _LOCK:
        init_user_store()
        cursor = _SQL.cursor()
        cursor.execute(
            """
            SELECT a.iban, a.balance
            FROM dbo.account a
            JOIN dbo.person u ON u.id = a.person_id
            WHERE u.username = ? COLLATE Latin1_General_CI_AI
            ORDER BY a.account_id
            """,
            (name,),
        )
        return [
            {"iban": str(row[0] or "").strip(), "balance": str(row[1] if row[1] is not None else "0")}
            for row in cursor.fetchall()
        ]


def upload_token_by_person_center() -> dict[tuple[str, str], str]:
    """Map ``(person, center)`` → upload token for personal users."""
    with _LOCK:
        init_user_store()
        if _use_sqlserver():
            cursor = _SQL.cursor()
            cursor.execute(
                """
                SELECT p.username, n.username
                FROM dbo.person p
                JOIN dbo.center n ON n.center_id = p.center_id
                """
            )
            rows = cursor.fetchall()
            pairs = [(str(r[0] or "").strip(), str(r[1] or "").strip()) for r in rows]
        else:
            raw_rows = _SQLITE.execute(
                """
                SELECT person, center
                FROM users
                WHERE person IS NOT NULL AND person != ''
                  AND center IS NOT NULL AND center != ''
                """
            ).fetchall()
            pairs = [(str(r["person"] or "").strip(), str(r["center"] or "").strip()) for r in raw_rows]
    out: dict[tuple[str, str], str] = {}
    for person, raw_ws in pairs:
        if not person:
            continue
        for center in parse_centers(raw_ws) or ([raw_ws] if raw_ws else []):
            if center:
                out[(person, center)] = DEFAULT_UPLOAD_TOKEN
    return out

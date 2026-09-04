"""Login users come from SQL Server (agrolav-sql): ``dbo.person`` / ``dbo.center`` / ``dbo.country``."""
from __future__ import annotations

import os
import re
import threading
import time
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable

from shared.passwords import hash_password, verify_password
from shared.user_access import ACCESS_COUNTRY, deduce_access, enrich_user_record, parse_centers

_LOCK = threading.RLock()
_SQL = None  # last pyodbc connection (readiness flag; do not share across threads)
_SQL_TLS = threading.local()
_WORKING_URL: str | None = None
_STORE_READY = False

FORMAT_SECRET = "secret"
FORMAT_MULTIPLE = "multiple"

# Stable upload-grant token (legacy scrypt string still accepted by /upload?t=…).
DEFAULT_UPLOAD_TOKEN = (
    "scrypt$16384$8$1$DqM8xC0un6VYeM0i4FwKcQ$sUhw7V7Wfd4Rz0PB9RoWEHVIVcNpNId2GM5QIU-8_fQ"
)

_SQL_PERSON_SELECT = """
SELECT
    p.id,
    p.username COLLATE Latin1_General_CI_AI AS username,
    p.title AS title,
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
    n.title AS title,
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
    c.title AS title,
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
    here = Path(__file__).resolve()
    candidates = [
        here.parents[1] / ".env",
        here.parents[2] / ".env" if len(here.parents) > 2 else None,
    ]
    seen: set[Path] = set()
    for path in candidates:
        if path is None or path in seen or not path.is_file():
            continue
        seen.add(path)
        for line in path.read_text(encoding="utf-8").splitlines():
            raw = line.strip()
            if not raw or raw.startswith("#") or "=" not in raw:
                continue
            key, _, val = raw.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key and not str(os.environ.get(key) or "").strip():
                os.environ[key] = val


_load_dotenv()


def database_url() -> str:
    return os.environ.get("HUB_DATABASE_URL", "").strip()


def store_label() -> str:
    return "sqlserver:dbo.person"


PASSWORD_PREFIX = "!@#$%^&*()_"


def password_for_username(username: str) -> str:
    """Login password is the shift-row prefix plus the username."""
    name = str(username or "").strip()
    if not name:
        return ""
    return PASSWORD_PREFIX + name


def default_password_hash(username: str) -> str:
    """Scrypt of the formula password for a newly created person."""
    return hash_password(password_for_username(username))


_E164 = re.compile(r"^\+[1-9]\d{7,14}$")


def normalize_mobile_phone(value: str | None) -> str | None:
    """E.164 (``+`` then 8–15 digits) or ``None`` if empty. Raises ``ValueError``.

    Also accepts ``0031…`` and a Dutch national ``06…`` (stored as ``+316…``).
    """
    text = str(value or "").strip().replace(" ", "").replace("-", "")
    if not text:
        return None
    if text.startswith("00"):
        text = "+" + text[2:]
    elif text.startswith("06") and text[2:].isdigit() and 8 <= len(text) <= 10:
        text = "+31" + text[1:]
    if not _E164.fullmatch(text):
        raise ValueError("Mobile phone must be international, e.g. +31612345678")
    return text


def credentials_match(
    password: str,
    *,
    username: str,
    is_person: bool,
    password_hash: str | None,
) -> bool:
    """Person: stored scrypt hash, or formula if hash is still NULL. Others: formula only."""
    plain = str(password or "")
    name = str(username or "").strip()
    if not name:
        return False
    formula = password_for_username(name)
    if not is_person:
        return plain == formula
    stored = str(password_hash or "").strip()
    if stored:
        return verify_password(plain, stored)
    return plain == formula


def _is_person_user(user: dict[str, Any] | None) -> bool:
    if not user:
        return False
    return bool(str(user.get("person") or "").strip())


def _person_column(username: str, column: str) -> Any:
    name = (username or "").strip()
    if not name:
        return None
    init_user_store()
    cursor = _sql_connect().cursor()
    cursor.execute(
        f"SELECT {column} FROM dbo.person WHERE username = ? COLLATE Latin1_General_CI_AI",
        (name,),
    )
    row = cursor.fetchone()
    if not row:
        return None
    return row[0]


def person_password_hash(username: str) -> str | None:
    raw = _person_column(username, "password_hash")
    text = str(raw or "").strip()
    return text or None


def person_mobile_phone(username: str) -> str | None:
    raw = _person_column(username, "mobile_phone")
    text = str(raw or "").strip()
    return text or None


def display_title(username: str) -> str:
    """Sidebar heading from a login username when no explicit title is stored."""
    text = str(username or "").strip()
    if not text:
        return ""
    if "_" in text or " " in text:
        return " ".join(
            word[:1].upper() + word[1:].lower()
            for word in text.replace("_", " ").split()
            if word
        )
    return text.upper()


def is_single_bank_format(fmt: str | None) -> bool:
    """True when ``format`` is a concrete bank CSV layout (not empty/secret/multiple)."""
    value = str(fmt or "").strip().lower()
    if not value or value in (FORMAT_SECRET, FORMAT_MULTIPLE):
        return False
    from app.core.bank_csv import is_csv_bank_format

    return is_csv_bank_format(value)


def as_date_only(value: str | None) -> str | None:
    """Normalize a date/datetime string to ``YYYY-MM-DD``, or ``None`` if unusable."""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value or "").strip()
    if not text:
        return None
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


def _sql_url_with_mars(url: str) -> str:
    """Allow more than one cursor on a connection (nested catalog queries)."""
    if re.search(r"MARS_Connection\s*=", url, flags=re.I):
        return url
    return url.rstrip(";") + ";MARS_Connection=yes"


def _open_sql_connection():
    """Open a new autocommit connection (one per worker thread)."""
    global _WORKING_URL
    pyodbc = _pyodbc()
    if _WORKING_URL:
        try:
            return pyodbc.connect(
                _sql_url_with_mars(_WORKING_URL), autocommit=True, timeout=8
            )
        except Exception:
            _WORKING_URL = None
    url = database_url()
    db_name = _database_name(url)
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", db_name):
        raise ValueError(f"Invalid SQL Server database name: {db_name!r}")
    last_err: Exception | None = None
    conn = None
    candidate = url
    for _attempt in range(24):
        for candidate in _connect_urls(url):
            try:
                master = pyodbc.connect(
                    _sql_url_with_mars(_master_url(candidate)), autocommit=True, timeout=8
                )
                try:
                    master.cursor().execute(
                        f"IF DB_ID(N'{db_name}') IS NULL CREATE DATABASE [{db_name}]"
                    )
                finally:
                    master.close()
                conn = pyodbc.connect(
                    _sql_url_with_mars(candidate), autocommit=True, timeout=8
                )
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
    _WORKING_URL = candidate
    return conn


def _sql_connect():
    """Return this thread's SQL Server connection."""
    global _SQL
    conn = getattr(_SQL_TLS, "conn", None)
    if conn is not None:
        return conn
    conn = _open_sql_connection()
    _SQL_TLS.conn = conn
    _SQL = conn
    return conn


def reset_sql_connection() -> None:
    """Drop this thread's dead pyodbc connection so the next call reconnects."""
    global _SQL
    conn = getattr(_SQL_TLS, "conn", None)
    _SQL_TLS.conn = None
    if _SQL is conn:
        _SQL = None
    if conn is None:
        return
    try:
        conn.close()
    except Exception:  # noqa: BLE001
        pass


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


def _ensure_login_titles(cursor) -> None:
    """Add country/center title if missing. Does not overwrite existing titles."""
    for table in ("country", "center"):
        cursor.execute(f"SELECT OBJECT_ID(N'dbo.{table}', N'U')")
        if cursor.fetchone()[0] is None:
            continue
        cursor.execute(f"SELECT COL_LENGTH(N'dbo.{table}', N'username')")
        if cursor.fetchone()[0] is None:
            continue
        cursor.execute(f"SELECT COL_LENGTH(N'dbo.{table}', N'title')")
        if cursor.fetchone()[0] is None:
            cursor.execute(f"ALTER TABLE dbo.{table} ADD title NVARCHAR(256) NULL")
            cursor.execute(
                f"UPDATE dbo.{table} SET title = username WHERE title IS NULL"
            )
            cursor.execute(
                f"ALTER TABLE dbo.{table} ALTER COLUMN title NVARCHAR(256) NOT NULL"
            )


def _ensure_consent_pending(cursor) -> None:
    """Create ``dbo.consent_pending`` (state -> person_name) if missing."""
    cursor.execute("SELECT OBJECT_ID(N'dbo.consent_pending', N'U')")
    if cursor.fetchone()[0] is not None:
        return
    cursor.execute(
        """
        CREATE TABLE dbo.consent_pending (
            state NVARCHAR(128) NOT NULL PRIMARY KEY,
            center NVARCHAR(256) NOT NULL,
            person_name NVARCHAR(256) NOT NULL,
            created_at DATETIME2 NOT NULL
        )
        """
    )


def init_user_store() -> str:
    """Open the SQL Server user store and ensure its schema exists."""
    global _STORE_READY
    if _STORE_READY:
        return store_label()
    with _LOCK:
        if _STORE_READY:
            return store_label()
        if not database_url():
            raise RuntimeError(
                "HUB_DATABASE_URL is not set — SQL Server (agrolav-sql) is "
                "required; users.db / SQLite is no longer used."
            )
        conn = _sql_connect()
        cursor = conn.cursor()
        cursor.execute("SELECT OBJECT_ID(N'dbo.person', N'U')")
        if cursor.fetchone()[0] is None:
            raise RuntimeError(
                "dbo.person is missing. Stop the hub; a live agrolav database "
                "already has this table (fresh empty DB: load_phase_c.py)."
            )
        _ensure_login_titles(cursor)
        _ensure_consent_pending(cursor)
        conn.commit()
        _STORE_READY = True
        return store_label()


def find_user(username: str) -> dict[str, Any] | None:
    needle = (username or "").strip()
    if not needle:
        return None
    with _LOCK:
        init_user_store()
        cursor = _sql_connect().cursor()
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
    return _row_to_user(row) if row else None


def authenticate(username: str, password: str) -> dict[str, Any] | None:
    user = find_user(username)
    if user is None:
        return None
    name = str(user.get("username") or "").strip()
    is_person = _is_person_user(user)
    stored = person_password_hash(name) if is_person else None
    if not credentials_match(
        password, username=name, is_person=is_person, password_hash=stored
    ):
        return None
    return user


def authenticate_public(username: str, password: str) -> dict[str, Any] | None:
    user = authenticate(username, password)
    return _public_user(user) if user else None


def list_users() -> list[dict[str, Any]]:
    with _LOCK:
        init_user_store()
        cursor = _sql_connect().cursor()
        cursor.execute(
            "SELECT * FROM (" + _SQL_USER_SELECT + ") u ORDER BY u.username"
        )
        rows = [_sql_cursor_row(cursor, raw) for raw in cursor.fetchall()]
    return [_public_user(_row_to_user(row)) for row in rows]


def upsert_user(
    *,
    username: str,
    title: str = "",
    center: str = "",
    country: str = "",
    person: str = "",
    mobile_phone: str | None = None,
) -> dict[str, Any]:
    """Insert or update a user. Does not change ``format`` or ``password_hash`` on update."""
    name = (username or "").strip()
    if not name:
        raise ValueError("username is required")
    title_s = _empty_to_null(title)
    center_s = _empty_to_null(center)
    country_s = _empty_to_null(country)
    person_s = _empty_to_null(person)
    today = _utc_today()
    mobile = normalize_mobile_phone(mobile_phone)
    with _LOCK:
        init_user_store()
        cursor = _sql_connect().cursor()
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
        title_value = (title_s or "").strip()
        if person_id is not None:
            if title_value:
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
                    UPDATE dbo.person
                    SET country_id = ?, center_id = ?
                    WHERE id = ?
                    """,
                    (country_id, center_id, person_id),
                )
        else:
            cursor.execute(
                """
                INSERT INTO dbo.person
                    (username, title, country_id, center_id, number_of_accounts,
                     created_at, password_hash, mobile_phone)
                VALUES (?, ?, ?, ?, 0, ?, ?, ?)
                """,
                (
                    name,
                    title_value,
                    country_id,
                    center_id,
                    today,
                    default_password_hash(name),
                    mobile,
                ),
            )
        _sql_connect().commit()
    user = find_user(name)
    if user is None:
        raise RuntimeError(f"failed to upsert user {name!r}")
    return _public_user(user)


def upsert_personal_login(
    *,
    center: str,
    person: str,
    country: str = "",
    title: str = "",
    mobile_phone: str | None = None,
) -> dict[str, Any]:
    folder = (person or "").strip()
    ws = (center or "").strip()
    if not folder or not ws:
        raise ValueError("center and person are required")
    from app.runtime import active_country, resolve_country_for_center

    country_s = (country or active_country() or resolve_country_for_center(ws) or "").strip()
    return upsert_user(
        username=folder,
        title=title,
        center=ws,
        country=country_s,
        person=folder,
        mobile_phone=mobile_phone,
    )


def create_manual_person(
    *,
    center: str,
    person: str,
    title: str,
    account_name: str,
    account_number: str,
    initial_balance: str = "0",
    country: str = "",
    mobile_phone: str | None = None,
) -> dict[str, Any]:
    """Create a manual-upload person with a single opening-balance account."""
    name = (person or "").strip()
    ws = (center or "").strip()
    holder = (account_name or "").strip()
    display_name = (title or "").strip()
    iban = (account_number or "").strip()
    balance_s = (initial_balance or "0").strip().replace(",", ".")
    if not name or not ws:
        raise ValueError("center and person are required")
    if not display_name:
        raise ValueError("Name is required")
    if not holder:
        raise ValueError("account holder name is required")
    if not iban:
        raise ValueError("account number is required")
    try:
        balance = Decimal(balance_s)
    except Exception:  # noqa: BLE001
        balance = Decimal("0")
    from app.runtime import active_country, resolve_country_for_center

    country_s = (country or active_country() or resolve_country_for_center(ws) or "").strip()
    today = _utc_today()
    mobile = normalize_mobile_phone(mobile_phone)
    with _LOCK:
        init_user_store()
        cursor = _sql_connect().cursor()
        country_id = _sql_country_id(cursor, country_s)
        if country_id is None:
            raise ValueError(f"Unknown country {country_s or name!r}")
        center_id = _sql_center_id(cursor, country_id, ws)
        if center_id is None:
            raise ValueError(f"Unknown center {ws!r} for country_id={country_id}")
        if _sql_username_taken(cursor, name):
            raise ValueError(f"Username already used: {name}")
        cursor.execute(
            """
            INSERT INTO dbo.person
                (username, title, country_id, center_id, number_of_accounts,
                 created_at, password_hash, mobile_phone)
            OUTPUT INSERTED.id
            VALUES (?, ?, ?, ?, 1, ?, ?, ?)
            """,
            (
                name,
                display_name,
                country_id,
                center_id,
                today,
                default_password_hash(name),
                mobile,
            ),
        )
        person_id = int(cursor.fetchone()[0])
        cursor.execute(
            """
            INSERT INTO dbo.account
                (person_id, iban, account_name, format, balance, last_booked, connection_id, uid)
            VALUES (?, ?, ?, NULL, ?, ?, NULL, NULL)
            """,
            (person_id, iban, holder, balance, today),
        )
        _sql_connect().commit()
    user = find_user(name)
    return {
        "person": name,
        "center": ws,
        "account_name": holder,
        "account_number": iban,
        "initial_balance": f"{balance:.2f}",
        "login": _public_user(user) if user else None,
    }


def set_person_password(
    *,
    username: str,
    current: str,
    new: str,
    confirm: str,
) -> dict[str, Any]:
    """Replace ``dbo.person.password_hash``. Person logins only."""
    name = (username or "").strip()
    user = find_user(name)
    if user is None or not _is_person_user(user):
        raise ValueError("Only a person login can set a password")
    if str(new or "") != str(confirm or ""):
        raise ValueError("New password and confirmation do not match")
    if not str(new or "").strip():
        raise ValueError("New password is required")
    stored = person_password_hash(name)
    if not credentials_match(
        current, username=name, is_person=True, password_hash=stored
    ):
        raise ValueError("Current password is incorrect")
    hashed = hash_password(str(new))
    with _LOCK:
        init_user_store()
        cursor = _sql_connect().cursor()
        cursor.execute(
            """
            UPDATE dbo.person SET password_hash = ?
            WHERE username = ? COLLATE Latin1_General_CI_AI
            """,
            (hashed, name),
        )
        if cursor.rowcount == 0:
            raise ValueError("Unknown person")
        _sql_connect().commit()
    return {"ok": True}


def set_person_mobile(*, username: str, mobile_phone: str | None) -> dict[str, Any]:
    """Store or clear ``dbo.person.mobile_phone``. Person logins only."""
    name = (username or "").strip()
    user = find_user(name)
    if user is None or not _is_person_user(user):
        raise ValueError("Only a person login can set a mobile phone")
    mobile = normalize_mobile_phone(mobile_phone)
    with _LOCK:
        init_user_store()
        cursor = _sql_connect().cursor()
        cursor.execute(
            """
            UPDATE dbo.person SET mobile_phone = ?
            WHERE username = ? COLLATE Latin1_General_CI_AI
            """,
            (mobile, name),
        )
        if cursor.rowcount == 0:
            raise ValueError("Unknown person")
        _sql_connect().commit()
    return {"ok": True, "mobile_phone": mobile or ""}


def set_user_format(*, username: str, format: str) -> dict[str, Any] | None:
    name = (username or "").strip()
    fmt = (format or "").strip()
    if not name or not fmt:
        return None
    with _LOCK:
        init_user_store()
        cursor = _sql_connect().cursor()
        cursor.execute(
            "SELECT id FROM dbo.person WHERE username = ? COLLATE Latin1_General_CI_AI",
            (name,),
        )
        row = cursor.fetchone()
        if not row:
            return None
        cursor.execute(
            "UPDATE dbo.account SET format = ? WHERE person_id = ? AND connection_id IS NULL",
            (fmt, int(row[0])),
        )
        _sql_connect().commit()
    user = find_user(name)
    return _public_user(user) if user else None


def account_last_booked(username: str) -> date | None:
    """Latest ``dbo.account.last_booked`` for the person, or ``None``."""
    name = (username or "").strip()
    if not name:
        return None
    init_user_store()
    cursor = _sql_connect().cursor()
    cursor.execute(
        """
        SELECT MAX(a.last_booked)
        FROM dbo.account a
        JOIN dbo.person p ON p.id = a.person_id
        WHERE p.username = ? COLLATE Latin1_General_CI_AI
        """,
        (name,),
    )
    row = cursor.fetchone()
    if not row:
        return None
    iso = as_date_only(row[0])
    return date.fromisoformat(iso) if iso else None


def set_account_last_booked(*, username: str, date: str | None) -> dict[str, Any] | None:
    """Stamp ``dbo.account.last_booked`` on every account for this person."""
    name = (username or "").strip()
    iso = as_date_only(date)
    if not name or not iso:
        return None
    with _LOCK:
        init_user_store()
        cursor = _sql_connect().cursor()
        cursor.execute(
            "SELECT id FROM dbo.person WHERE username = ? COLLATE Latin1_General_CI_AI",
            (name,),
        )
        row = cursor.fetchone()
        if not row:
            return None
        cursor.execute(
            "UPDATE dbo.account SET last_booked = ? WHERE person_id = ?",
            (iso, int(row[0])),
        )
        _sql_connect().commit()
    user = find_user(name)
    return _public_user(user) if user else None


def list_accounts_for_username(username: str) -> list[dict[str, str]]:
    """IBANs (and balances) for a person pack."""
    name = (username or "").strip()
    if not name:
        return []
    init_user_store()
    cursor = _sql_connect().cursor()
    cursor.execute(
        """
        SELECT a.iban, a.balance, a.account_name
        FROM dbo.account a
        JOIN dbo.person u ON u.id = a.person_id
        WHERE u.username = ? COLLATE Latin1_General_CI_AI
        ORDER BY a.account_id
        """,
        (name,),
    )
    return [
        {
            "iban": str(row[0] or "").strip(),
            "balance": str(row[1] if row[1] is not None else "0"),
            "account_name": str(row[2] or "").strip(),
        }
        for row in cursor.fetchall()
    ]


def upload_token_by_person_center() -> dict[tuple[str, str], str]:
    """Map ``(person, center)`` → upload token for personal users."""
    with _LOCK:
        init_user_store()
        cursor = _sql_connect().cursor()
        cursor.execute(
            """
            SELECT p.username, n.username,
                CASE WHEN EXISTS (
                    SELECT 1
                    FROM dbo.enable_connection ec
                    WHERE ec.person_id = p.id
                      AND ec.pem IS NOT NULL
                      AND LTRIM(RTRIM(ec.pem)) <> N''
                ) THEN 1 ELSE 0 END
            FROM dbo.person p
            JOIN dbo.center n ON n.center_id = p.center_id
            """
        )
        rows = cursor.fetchall()
        pairs = [
            (str(r[0] or "").strip(), str(r[1] or "").strip(), int(r[2] or 0))
            for r in rows
        ]
    out: dict[tuple[str, str], str] = {}
    for person, raw_ws, has_pem in pairs:
        if not person:
            continue
        if has_pem:
            continue
        for center in parse_centers(raw_ws) or ([raw_ws] if raw_ws else []):
            if center:
                out[(person, center)] = DEFAULT_UPLOAD_TOKEN
    return out

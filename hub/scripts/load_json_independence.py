"""Load JSON leftovers into the tables from ``hub/sql/json_independence.sql``.

Run after ``load_phase_c.py`` and after executing ``json_independence.sql``:

  cd hub
  uv run python scripts/load_json_independence.py

Reloads (delete + insert) json_independence tables. Enable PEM and account
uids go on ``dbo.enable_connection`` / ``dbo.account``.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

HUB_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HUB_ROOT))
sys.path.insert(0, str(HUB_ROOT.parent / "shared"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.core.bank_csv import normalize_upload_format  # noqa: E402
from app.core.single_client import _consent_subset, _migrate_profile  # noqa: E402
from app.runtime import country_folder, data_root  # noqa: E402
from app.upload_acl import _normalize_ip, load_acl_document  # noqa: E402
from app.yearpath import has_person_layout  # noqa: E402
from load_private_keys import _resolve_pem  # noqa: E402

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
TABLES = (
    "table_header_term",
    "type_rule",
    "bank_modality",
    "hub_ip",
    "enable_connection",
    "enable_redirect",
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


def _read_json_object(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LoadError(f"Invalid JSON: {path}: {exc}") from exc
    return data if isinstance(data, dict) else {}


def _local_code(label: str) -> int | None:
    match = _LOCAL_CODE.match(str(label).strip())
    if match:
        return int(match.group(1))
    try:
        return int(str(label)[:2])
    except ValueError:
        return None


def _require_tables(cursor) -> None:
    missing: list[str] = []
    for name in TABLES:
        cursor.execute(f"SELECT OBJECT_ID(N'dbo.{name}', N'U')")
        if cursor.fetchone()[0] is None:
            missing.append(f"dbo.{name}")
    if missing:
        raise LoadError(
            "Missing tables (run hub/sql/json_independence.sql first): "
            + ", ".join(missing)
        )


def _countries(cursor) -> list[tuple[int, str, Path]]:
    root = data_root()
    cursor.execute("SELECT country_id, username FROM dbo.country")
    out: list[tuple[int, str, Path]] = []
    for country_id, name in cursor.fetchall():
        folder = country_folder(str(name)) or str(name)
        out.append((int(country_id), str(name), root / folder))
    return out


def _person_packs(cursor) -> Iterator[tuple[int, Path]]:
    cursor.execute(
        """
        SELECT id, username
        FROM dbo.person
        """
    )
    users = {str(username): int(person_id) for person_id, username in cursor.fetchall()}
    for _country_id, _name, country_dir in _countries(cursor):
        if not country_dir.is_dir():
            continue
        for center_dir in _dirs(country_dir):
            for person_dir in _dirs(center_dir):
                if not has_person_layout(person_dir):
                    continue
                found = users.get(person_dir.name)
                if found is None:
                    continue
                yield found, person_dir


def _parse_dt(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _insert_many(cursor, sql: str, rows: list[tuple[Any, ...]]) -> int:
    if not rows:
        return 0
    cursor.fast_executemany = True
    cursor.executemany(sql, rows)
    cursor.fast_executemany = False
    return len(rows)


def load_table_header_terms(cursor) -> int:
    cursor.execute("DELETE FROM dbo.table_header_term")
    rows: list[tuple[int, str, str]] = []
    for country_id, _name, country_dir in _countries(cursor):
        payload = _read_json_object(country_dir / "categories.json")
        terms = payload.get("table_header_terms")
        if not isinstance(terms, dict):
            continue
        for key, label in terms.items():
            term_key = str(key).strip()
            text = str(label).strip()
            if not term_key or not text:
                continue
            rows.append((country_id, term_key[:64], text[:128]))
    return _insert_many(
        cursor,
        """
        INSERT INTO dbo.table_header_term (country_id, term_key, label)
        VALUES (?, ?, ?)
        """,
        rows,
    )


def load_type_rules(cursor) -> int:
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

    cursor.execute("DELETE FROM dbo.type_rule")
    rows: list[tuple[int, str, int]] = []
    skipped: list[str] = []
    for country_id, _name, country_dir in _countries(cursor):
        payload = _read_json_object(country_dir / "categories.json")
        raw = payload.get("typerules")
        if not isinstance(raw, list):
            continue
        for item in raw:
            if not isinstance(item, dict):
                continue
            bank_type = str(item.get("type") or "").strip()
            category_name = str(item.get("category") or "").strip()
            if not bank_type or not category_name:
                continue
            category_id = by_label.get((country_id, category_name))
            if category_id is None:
                code = _local_code(category_name)
                if code is not None:
                    category_id = by_code.get((country_id, code))
            if category_id is None:
                skipped.append(f"{country_dir.name}: {bank_type} -> {category_name}")
                continue
            rows.append((country_id, bank_type[:64], category_id))
    if skipped:
        print(f"skipped type_rule (unknown category): {len(skipped)}")
        for item in skipped:
            print(f"  {item}")
    return _insert_many(
        cursor,
        """
        INSERT INTO dbo.type_rule (country_id, bank_type, category_id)
        VALUES (?, ?, ?)
        """,
        rows,
    )


def load_bank_modalities(cursor) -> int:
    cursor.execute("SELECT bank_id, file_format FROM dbo.bank")
    by_format: dict[str, int] = {}
    for bank_id, file_format in cursor.fetchall():
        by_format[str(file_format).strip().lower()] = int(bank_id)

    raw = load_acl_document().get("bank modalities")
    if not isinstance(raw, dict):
        raw = {}
    cursor.execute("DELETE FROM dbo.bank_modality")
    rows: list[tuple[str, int]] = []
    skipped: list[str] = []
    for folder, fmt in raw.items():
        folder_name = str(folder or "").strip()
        if not folder_name:
            continue
        normalized = normalize_upload_format(str(fmt or ""))
        bank_id = by_format.get(normalized)
        if bank_id is None:
            skipped.append(f"{folder_name} ({normalized})")
            continue
        rows.append((folder_name[:64], bank_id))
    if skipped:
        print(f"skipped bank_modality (unknown format): {len(skipped)}")
        for item in skipped:
            print(f"  {item}")
    return _insert_many(
        cursor,
        """
        INSERT INTO dbo.bank_modality (folder_name, bank_id)
        VALUES (?, ?)
        """,
        rows,
    )


def load_hub_ips(cursor) -> int:
    raw = load_acl_document().get("hub_ips")
    ips: list[str] = []
    if isinstance(raw, list):
        seen: set[str] = set()
        for item in raw:
            ip = _normalize_ip(str(item))
            if not ip or "x" in ip.lower() or ip in seen:
                continue
            seen.add(ip)
            ips.append(ip[:64])
    cursor.execute("DELETE FROM dbo.hub_ip")
    return _insert_many(
        cursor,
        "INSERT INTO dbo.hub_ip (ip) VALUES (?)",
        [(ip,) for ip in ips],
    )


def _enable_record(person_dir: Path) -> dict[str, Any] | None:
    secret = person_dir / "secret"
    profile_path = secret / "profile.json"
    consent_path = secret / "consent.json"
    if not profile_path.is_file() and not consent_path.is_file():
        return None
    profile, _changed = _migrate_profile(_read_json_object(profile_path), profile_path)
    return _consent_subset(profile)


def _iban_of(acc: dict[str, Any]) -> str:
    return str(acc.get("iban") or "").strip()


def _currency_of(acc: dict[str, Any]) -> str | None:
    text = str(acc.get("currency") or acc.get("balance_currency") or "").strip().upper()
    return text if len(text) == 3 else None


def load_enable(cursor) -> tuple[int, int, int]:
    cursor.execute(
        """
        SELECT account_id, person_id, iban
        FROM dbo.account
        """
    )
    accounts: dict[tuple[int, str], int] = {}
    for account_id, person_id, iban in cursor.fetchall():
        key = (int(person_id), str(iban or "").strip())
        if key[1]:
            accounts[key] = int(account_id)

    cursor.execute(
        """
        UPDATE dbo.account
        SET connection_id = NULL, uid = NULL, identification_hash = NULL
        """
    )
    cursor.execute("DELETE FROM dbo.enable_connection")
    cursor.execute("DELETE FROM dbo.enable_redirect")

    connection_count = 0
    account_count = 0
    redirect_count = 0
    skipped_people: list[str] = []

    for person_id, person_dir in _person_packs(cursor):
        record = _enable_record(person_dir)
        if record is None:
            continue
        connections = record.get("connections")
        if not isinstance(connections, list):
            connections = []
        secret = person_dir / "secret"
        resolved = _resolve_pem(secret) if secret.is_dir() else None
        pem = resolved[1] if resolved else None
        pem_app_id = resolved[0] if resolved else None
        for conn in connections:
            if not isinstance(conn, dict):
                continue
            aspsp = str(conn.get("aspsp") or "").strip()
            if not aspsp:
                skipped_people.append(f"{person_dir.name}: connection missing aspsp")
                continue
            app_id = str(conn.get("app_id") or "").strip() or pem_app_id
            session_id = str(conn.get("session_id") or "").strip() or None
            cursor.execute(
                """
                INSERT INTO dbo.enable_connection (
                    app_id, session_id, valid_until, created_at, pem
                )
                OUTPUT INSERTED.connection_id
                VALUES (?, ?, ?, ?, ?)
                """,
                app_id,
                (session_id[:256] if session_id else None),
                _parse_dt(conn.get("valid_until")),
                _parse_dt(conn.get("created_at")),
                pem,
            )
            connection_id = int(cursor.fetchone()[0])
            connection_count += 1
            for acc in conn.get("accounts") or []:
                if not isinstance(acc, dict):
                    continue
                uid = str(acc.get("uid") or "").strip()
                if not uid:
                    continue
                iban = _iban_of(acc)
                account_id = accounts.get((person_id, iban))
                if account_id is None:
                    continue
                hash_value = str(acc.get("identification_hash") or "").strip() or None
                cursor.execute(
                    """
                    UPDATE dbo.account
                    SET
                        connection_id = ?,
                        uid = ?,
                        identification_hash = ?,
                        format = ?
                    WHERE account_id = ?
                    """,
                    connection_id,
                    uid[:128],
                    (hash_value[:128] if hash_value else None),
                    aspsp[:64],
                    account_id,
                )
                account_count += 1

        redirect_input = record.get("last_redirect_input")
        redirect_code = str(record.get("last_redirect_code") or "").strip() or None
        redirect_at = _parse_dt(record.get("last_redirect_code_at"))
        if redirect_input or redirect_code or redirect_at:
            cursor.execute(
                """
                INSERT INTO dbo.enable_redirect (
                    person_id, last_redirect_input,
                    last_redirect_code, last_redirect_code_at
                )
                VALUES (?, ?, ?, ?)
                """,
                person_id,
                (str(redirect_input) if redirect_input else None),
                (redirect_code[:256] if redirect_code else None),
                redirect_at,
            )
            redirect_count += 1

    if skipped_people:
        print(f"skipped enable_connection: {len(skipped_people)}")
        for item in skipped_people:
            print(f"  {item}")
    return connection_count, account_count, redirect_count


def main() -> None:
    conn = _connect()
    cursor = conn.cursor()
    try:
        _require_tables(cursor)
        header_n = load_table_header_terms(cursor)
        type_n = load_type_rules(cursor)
        modality_n = load_bank_modalities(cursor)
        ip_n = load_hub_ips(cursor)
        conn_n, acc_n, redirect_n = load_enable(cursor)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    print(f"table_header_term: {header_n}")
    print(f"type_rule: {type_n}")
    print(f"bank_modality: {modality_n}")
    print(f"hub_ip: {ip_n}")
    print(f"enable_connection: {conn_n}")
    print(f"account enable links: {acc_n}")
    print(f"enable_redirect: {redirect_n}")


if __name__ == "__main__":
    main()

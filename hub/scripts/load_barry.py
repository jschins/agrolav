"""Load Barry O'Grady (AIB / Ireland) from the single-docker dist pack.

Does not create on-disk center folders. Does not DROP DATABASE. Re-runnable: wipes
only this person, then inserts again. Ireland catalog / center / txn table are
created once.

Source (Enable Banking dist, not a year-folder pack):

  C:\\Coding\\bankingApp\\single-docker\\people\\dist_bog

  cd hub
  uv run python scripts/load_barry.py
"""
from __future__ import annotations

import json
import re
import sys
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

HUB_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HUB_ROOT))
sys.path.insert(0, str(HUB_ROOT.parent / "shared"))

from app.core.categorize import DEFAULT_CATEGORY  # noqa: E402
from app.core.single_client import _consent_subset, _migrate_profile  # noqa: E402
from app.sql_layout import _create_transaction_table, _local_code  # noqa: E402

SOURCE = Path(r"C:\Coding\bankingApp\single-docker\people\dist_bog")
DATA = SOURCE / "data"
SECRET = SOURCE / "secret"

COUNTRY_USERNAME = "ireland"
COUNTRY_TITLE = "Ireland"
CENTER_USERNAME = "ie_aib"
CENTER_TITLE = "AIB"
PERSON_USERNAME = "barry_o_grady"
PERSON_TITLE = "Barry O'Grady"
CURRENCY = "EUR"

_DATE_DMY = re.compile(r"^(\d{2})-(\d{2})-(\d{4})$")
_ACCOUNT_SUFFIX = re.compile(r"_(\d+)$")


class LoadError(RuntimeError):
    pass


def _connect():
    from app import user_store

    if not user_store.database_url():
        raise SystemExit("Set HUB_DATABASE_URL (see hub/.env.example)")
    user_store.init_user_store()
    return user_store._sql_connect()


def _read_json(path: Path) -> Any:
    if not path.is_file():
        raise LoadError(f"Missing file: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LoadError(f"Invalid JSON: {path}: {exc}") from exc


def _read_json_object(path: Path) -> dict[str, Any]:
    data = _read_json(path)
    if not isinstance(data, dict):
        raise LoadError(f"{path}: expected a JSON object")
    return data


def _parse_amount(raw: Any, *, path: Path) -> Decimal:
    text = str(raw or "").strip().replace(",", ".")
    if not text:
        raise LoadError(f"{path}: empty amount")
    try:
        return Decimal(text)
    except InvalidOperation as exc:
        raise LoadError(f"{path}: bad amount {raw!r}") from exc


def _parse_booked_on(raw: Any, *, path: Path) -> date:
    text = str(raw or "").strip()
    match = _DATE_DMY.fullmatch(text)
    if match:
        return date(int(match.group(3)), int(match.group(2)), int(match.group(1)))
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        try:
            return date.fromisoformat(text[:10])
        except ValueError:
            pass
    raise LoadError(f"{path}: bad date {raw!r}")


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


def _account_index(source_id: str) -> int:
    match = _ACCOUNT_SUFFIX.search(source_id)
    if match:
        return int(match.group(1))
    return 0


def _mod_bits(overlay: dict[str, Any] | None) -> int:
    if not overlay:
        return 0
    bits = 0
    if overlay.get("category") is not None:
        bits |= 1
    if overlay.get("description") is not None:
        bits |= 2
    return bits


def _ensure_country(cursor) -> int:
    cursor.execute(
        """
        SELECT country_id FROM dbo.country
        WHERE username = ? COLLATE Latin1_General_CI_AI
        """,
        (COUNTRY_USERNAME,),
    )
    row = cursor.fetchone()
    if row:
        return int(row[0])
    from app import user_store

    if user_store._sql_username_taken(cursor, COUNTRY_USERNAME):
        raise LoadError(f"Username already used: {COUNTRY_USERNAME}")
    cursor.execute("SELECT ISNULL(MAX(country_id), 0) + 1 FROM dbo.country")
    country_id = int(cursor.fetchone()[0])
    cursor.execute(
        """
        INSERT INTO dbo.country (country_id, username, title, currency_default)
        VALUES (?, ?, ?, ?)
        """,
        (country_id, COUNTRY_USERNAME, COUNTRY_TITLE, CURRENCY),
    )
    print(f"country {COUNTRY_USERNAME} id={country_id}")
    return country_id


def _ensure_center(cursor, country_id: int) -> int:
    cursor.execute(
        """
        SELECT center_id FROM dbo.center
        WHERE username = ? COLLATE Latin1_General_CI_AI
        """,
        (CENTER_USERNAME,),
    )
    row = cursor.fetchone()
    if row:
        return int(row[0])
    from app import user_store

    if user_store._sql_username_taken(cursor, CENTER_USERNAME):
        raise LoadError(f"Username already used: {CENTER_USERNAME}")
    from app.sql_layout import _insert_center_row

    center_id = _insert_center_row(
        cursor,
        country_id=country_id,
        username=CENTER_USERNAME,
        title=CENTER_TITLE,
    )
    print(f"center {CENTER_USERNAME} id={center_id}")
    return center_id


def _ensure_categories(cursor, country_id: int) -> dict[int, int]:
    cursor.execute(
        "SELECT local_code, category_id FROM dbo.dim_category WHERE country_id = ?",
        (country_id,),
    )
    by_code = {int(code): int(cid) for code, cid in cursor.fetchall()}
    if by_code:
        return by_code
    catalog = DATA / "categories.json"
    payload = _read_json_object(catalog)
    categories = payload.get("categories")
    if not isinstance(categories, dict) or not categories:
        raise LoadError(f"No categories in {catalog}")
    term_rows: list[tuple[int, str, int]] = []
    abbr_rows: list[tuple[int, str, str]] = []
    by_code = {}
    for index, (label, terms) in enumerate(categories.items()):
        category_id = country_id * 100 + index
        code = _local_code(str(label))
        if code is None:
            raise LoadError(f"{catalog}: expected numbered category, got {label!r}")
        is_remainder = 1 if code == DEFAULT_CATEGORY else 0
        cursor.execute(
            """
            INSERT INTO dbo.dim_category
                (category_id, country_id, local_code, label, is_remainder, matrix_role)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (category_id, country_id, code, str(label), is_remainder, None),
        )
        by_code[code] = category_id
        seen: set[str] = set()
        if isinstance(terms, list):
            sort_order = 0
            for term in terms:
                text = str(term).strip()
                if not text or text in seen:
                    continue
                seen.add(text)
                term_rows.append((category_id, text, sort_order))
                sort_order += 1
    abbreviations = payload.get("abbreviations") or {}
    if isinstance(abbreviations, dict):
        for bank_type, abbreviation in abbreviations.items():
            abbr_rows.append((country_id, str(bank_type), str(abbreviation)[:16]))
    if term_rows:
        cursor.executemany(
            """
            INSERT INTO dbo.category_term (category_id, person_id, term, sort_order)
            VALUES (?, NULL, ?, ?)
            """,
            term_rows,
        )
    if abbr_rows:
        cursor.executemany(
            """
            INSERT INTO dbo.type_abbreviation (country_id, bank_type, abbreviation)
            VALUES (?, ?, ?)
            """,
            abbr_rows,
        )
    if DEFAULT_CATEGORY not in by_code:
        raise LoadError(f"{catalog}: no remainder category {DEFAULT_CATEGORY}")
    print(f"dim_category ireland: {len(by_code)} rows")
    return by_code


def _wipe_person(cursor, person_id: int, table: str) -> None:
    cursor.execute(
        """
        SELECT DISTINCT connection_id
        FROM dbo.account
        WHERE person_id = ? AND connection_id IS NOT NULL
        """,
        (person_id,),
    )
    conn_ids = [int(row[0]) for row in cursor.fetchall()]
    cursor.execute("DELETE FROM dbo.enable_redirect WHERE person_id = ?", (person_id,))
    cursor.execute("DELETE FROM dbo.category_total WHERE person_id = ?", (person_id,))
    cursor.execute("DELETE FROM dbo.category_term WHERE person_id = ?", (person_id,))
    cursor.execute(
        """
        DELETE FROM dbo.account_balance_file
        WHERE account_id IN (SELECT account_id FROM dbo.account WHERE person_id = ?)
        """,
        (person_id,),
    )
    cursor.execute(f"DELETE FROM {table} WHERE person_id = ?", (person_id,))
    cursor.execute("DELETE FROM dbo.account WHERE person_id = ?", (person_id,))
    for connection_id in conn_ids:
        cursor.execute(
            "DELETE FROM dbo.enable_connection WHERE connection_id = ?",
            (connection_id,),
        )
    cursor.execute("DELETE FROM dbo.person WHERE id = ?", (person_id,))
    print(f"wiped existing person_id={person_id}")


def _insert_person(cursor, *, country_id: int, center_id: int, n_accounts: int) -> int:
    from app import user_store

    if user_store._sql_username_taken(cursor, PERSON_USERNAME):
        raise LoadError(f"Username already used: {PERSON_USERNAME}")
    today = date.today()
    cursor.execute(
        """
        INSERT INTO dbo.person
            (username, title, country_id, center_id, number_of_accounts, created_at)
        OUTPUT INSERTED.id
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (PERSON_USERNAME, PERSON_TITLE, country_id, center_id, n_accounts, today),
    )
    return int(cursor.fetchone()[0])


def _accounts_from_consent(consent: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for conn in consent.get("connections") or []:
        if not isinstance(conn, dict):
            continue
        for acc in conn.get("accounts") or []:
            if not isinstance(acc, dict):
                continue
            iban = str(acc.get("iban") or "").strip()
            if not iban:
                continue
            out.append({**acc, "aspsp": str(conn.get("aspsp") or "").strip()})
    if not out:
        raise LoadError("consent has no accounts")
    return out


def _insert_accounts(cursor, person_id: int, raw_accounts: list[dict[str, Any]]) -> list[int]:
    ids: list[int] = []
    for acc in raw_accounts:
        iban = str(acc.get("iban") or "").strip()[:64]
        name = str(acc.get("name") or "").strip()[:64] or iban
        balance = _parse_amount(acc.get("balance") or "0", path=DATA / "bog_consent.json")
        fmt = str(acc.get("aspsp") or "").strip()[:64] or None
        cursor.execute(
            """
            INSERT INTO dbo.account (person_id, iban, account_name, format, balance)
            OUTPUT INSERTED.account_id
            VALUES (?, ?, ?, ?, ?)
            """,
            (person_id, iban, name, fmt, balance),
        )
        ids.append(int(cursor.fetchone()[0]))
    return ids


def _load_transactions(
    cursor,
    *,
    table: str,
    person_id: int,
    account_ids: list[int],
    by_code: dict[int, int],
) -> int:
    path = DATA / "bog_categorized_transactions.json"
    payload = _read_json_object(path)
    records = payload.get("transactions")
    if not isinstance(records, list):
        raise LoadError(f"{path}: transactions must be a list")
    overlays: dict[str, dict[str, Any]] = {}
    raw_mods = payload.get("modifications") or []
    if not isinstance(raw_mods, list):
        raise LoadError(f"{path}: modifications must be a list")
    for item in raw_mods:
        if isinstance(item, dict) and item.get("id") is not None:
            overlays[str(item.get("id"))] = item

    remainder_id = by_code[DEFAULT_CATEGORY]
    rows: list[tuple[Any, ...]] = []
    seen: set[tuple[int, str]] = set()
    skipped_unknown = 0
    for raw in records:
        if not isinstance(raw, dict):
            continue
        source_id = str(raw.get("id") or "").strip()
        if not source_id:
            raise LoadError(f"{path}: transaction missing id")
        overlay = overlays.get(source_id)
        effective = dict(raw)
        if overlay:
            for key in ("category", "description", "amount", "type", "name", "iban", "date"):
                if key in overlay:
                    effective[key] = overlay[key]
        booked = _parse_booked_on(effective.get("date"), path=path)
        year = booked.year
        index = _account_index(source_id)
        if index < 0 or index >= len(account_ids):
            raise LoadError(f"{path}: account index {index} out of range for {source_id}")
        account_id = account_ids[index]
        key = (year, source_id)
        if key in seen:
            continue
        seen.add(key)
        code: int | None
        try:
            code = int(effective.get("category"))
        except (TypeError, ValueError):
            code = None
        category_id = by_code.get(code, remainder_id) if code is not None else remainder_id
        if code is not None and code not in by_code:
            skipped_unknown += 1
            category_id = remainder_id
        hit_raw = effective.get("hit")
        hit = None
        if hit_raw not in (None, ""):
            text = str(hit_raw).strip()
            if text.startswith("P:") or text.startswith("G:"):
                hit = text[:64]
        iban = str(effective.get("iban") or "").strip()[:64] or None
        description = str(effective.get("description") or "") or None
        rows.append(
            (
                person_id,
                account_id,
                year,
                None,
                source_id[:128],
                _parse_amount(effective.get("amount"), path=path),
                (str(effective.get("type") or "")[:64] or None),
                (str(effective.get("name") or "")[:512] or None),
                iban,
                description,
                booked,
                category_id,
                _mod_bits(overlay),
                hit,
            )
        )
    if not rows:
        raise LoadError(f"{path}: no transactions")
    cursor.fast_executemany = False
    cursor.executemany(
        f"""
        INSERT INTO {table} (
            person_id, account_id, year, bank_id, source_id, amount,
            bank_type, counterparty_name, counterparty_iban, description,
            booked_on, category_id, modification, hit
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    if skipped_unknown:
        print(f"unknown category codes mapped to remainder: {skipped_unknown}")
    return len(rows)


def _load_pem(app_id: str) -> tuple[str, str]:
    pem_path = SECRET / f"{app_id}.pem"
    if not pem_path.is_file():
        pems = sorted(SECRET.glob("*.pem"))
        if len(pems) != 1:
            raise LoadError(f"PEM not found for app_id {app_id}")
        pem_path = pems[0]
        app_id = pem_path.stem.strip()
    text = pem_path.read_text(encoding="utf-8")
    if "PRIVATE KEY" not in text:
        raise LoadError(f"Not a PEM private key: {pem_path}")
    return app_id, text.strip() + "\n"


def _load_enable(
    cursor,
    *,
    person_id: int,
    account_ids: list[int],
    raw_accounts: list[dict[str, Any]],
    consent: dict[str, Any],
    app_id: str,
) -> None:
    app_id, pem = _load_pem(app_id)
    by_iban = {
        str(acc.get("iban") or "").strip(): account_id
        for acc, account_id in zip(raw_accounts, account_ids)
    }
    for conn in consent.get("connections") or []:
        if not isinstance(conn, dict):
            continue
        aspsp = str(conn.get("aspsp") or "").strip()
        if not aspsp:
            continue
        session_id = str(conn.get("session_id") or "").strip() or None
        conn_app = str(conn.get("app_id") or "").strip() or app_id
        cursor.execute(
            """
            INSERT INTO dbo.enable_connection (
                person_id, app_id, session_id, valid_until, created_at, pem
            )
            OUTPUT INSERTED.connection_id
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            person_id,
            (conn_app[:128] if conn_app else None),
            (session_id[:256] if session_id else None),
            _parse_dt(conn.get("valid_until")),
            _parse_dt(conn.get("created_at")),
            pem,
        )
        connection_id = int(cursor.fetchone()[0])
        for acc in conn.get("accounts") or []:
            if not isinstance(acc, dict):
                continue
            uid = str(acc.get("uid") or "").strip()
            if not uid:
                continue
            iban = str(acc.get("iban") or "").strip()
            account_id = by_iban.get(iban)
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
                (
                    connection_id,
                    uid[:128],
                    (hash_value[:128] if hash_value else None),
                    aspsp[:64],
                    account_id,
                ),
            )


def _set_last_booked(cursor, table: str, person_id: int) -> None:
    cursor.execute(
        f"""
        UPDATE a
        SET last_booked = x.mx
        FROM dbo.account a
        INNER JOIN (
            SELECT account_id, MAX(booked_on) AS mx
            FROM {table}
            WHERE person_id = ?
            GROUP BY account_id
        ) x ON x.account_id = a.account_id
        WHERE a.person_id = ?
        """,
        (person_id, person_id),
    )


def load(cursor) -> None:
    if not SOURCE.is_dir():
        raise LoadError(f"Source pack not found: {SOURCE}")
    country_id = _ensure_country(cursor)
    center_id = _ensure_center(cursor, country_id)
    table = _create_transaction_table(
        cursor, country=COUNTRY_USERNAME, country_id=country_id
    )
    by_code = _ensure_categories(cursor, country_id)

    cursor.execute(
        "SELECT id FROM dbo.person WHERE username = ? COLLATE Latin1_General_CI_AI",
        (PERSON_USERNAME,),
    )
    existing = cursor.fetchone()
    if existing:
        _wipe_person(cursor, int(existing[0]), table)

    profile_path = SECRET / "bog_profile.json"
    profile_raw = _read_json_object(profile_path)
    consent_path = DATA / "bog_consent.json"
    if consent_path.is_file():
        consent_raw = _read_json_object(consent_path)
        if not profile_raw.get("connections") and isinstance(
            consent_raw.get("connections"), list
        ):
            profile_raw["connections"] = consent_raw["connections"]
    profile, _changed = _migrate_profile(profile_raw, profile_path)
    consent = _consent_subset(profile)
    raw_accounts = _accounts_from_consent(consent)
    person_id = _insert_person(
        cursor,
        country_id=country_id,
        center_id=center_id,
        n_accounts=len(raw_accounts),
    )
    account_ids = _insert_accounts(cursor, person_id, raw_accounts)
    n_tx = _load_transactions(
        cursor,
        table=table,
        person_id=person_id,
        account_ids=account_ids,
        by_code=by_code,
    )
    app_id = ""
    for conn in profile.get("connections") or []:
        if isinstance(conn, dict):
            app_id = str(conn.get("app_id") or "").strip()
            if app_id:
                break
    if not app_id:
        app_id = str(_read_json_object(profile_path).get("app_id") or "").strip()
    if not app_id:
        raise LoadError("profile has no app_id")
    _load_enable(
        cursor,
        person_id=person_id,
        account_ids=account_ids,
        raw_accounts=raw_accounts,
        consent=consent,
        app_id=app_id,
    )
    _set_last_booked(cursor, table, person_id)
    cursor.execute(
        """
        UPDATE dbo.person
        SET number_of_accounts = (SELECT COUNT(*) FROM dbo.account WHERE person_id = ?)
        WHERE id = ?
        """,
        (person_id, person_id),
    )
    print(f"person {PERSON_USERNAME} id={person_id} title={PERSON_TITLE!r}")
    print(f"accounts: {len(account_ids)}")
    print(f"bookings: {n_tx} -> {table}")
    print(
        f"login: {COUNTRY_USERNAME} / {CENTER_USERNAME} / {PERSON_USERNAME}"
    )


def main() -> None:
    conn = _connect()
    cursor = conn.cursor()
    try:
        load(cursor)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    print("load_barry complete")


if __name__ == "__main__":
    main()

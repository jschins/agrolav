"""Replace Barry's bookings with ``bog_downloaded_transactions.json``.

``_account_index`` 0 → credit card (XXXX … 5301)
``_account_index`` 1 → IE62AIBK93353815584066

Deletes only ``dbo.transaction_ireland`` rows for Barry, then inserts the
downloaded file (Enable Banking raw). Does not create on-disk center folders.

  cd hub
  uv run python scripts/reload_barry_downloaded.py
"""
from __future__ import annotations

import json
import sys
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

HUB_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HUB_ROOT))
sys.path.insert(0, str(HUB_ROOT.parent / "shared"))

from app.core.categorize import (  # noqa: E402
    DEFAULT_CATEGORY,
    _category_map,
    categorize_with_hit,
    simplify_transaction,
)
from app.sql_catalog import categories_payload  # noqa: E402

SOURCE = Path(r"C:\Coding\bankingApp\single-docker\people\dist_bog")
DOWNLOADED = SOURCE / "data" / "bog_downloaded_transactions.json"
PERSON_USERNAMES = ("barry_o_grady", "barry_ogrady")
COUNTRY_USERNAME = "ireland"
TABLE = "dbo.transaction_ireland"
CARD_IBAN_MARK = "5301"
CURRENT_IBAN = "IE62AIBK93353815584066"


class LoadError(RuntimeError):
    pass


def _connect():
    from app import user_store

    if not user_store.database_url():
        raise SystemExit("Set HUB_DATABASE_URL (see hub/.env.example)")
    user_store.init_user_store()
    return user_store._sql_connect()


def _parse_amount(raw: Any) -> Decimal:
    text = str(raw or "").strip().replace(",", ".")
    if not text:
        raise LoadError("empty amount")
    try:
        return Decimal(text)
    except InvalidOperation as exc:
        raise LoadError(f"bad amount {raw!r}") from exc


def _parse_booked(raw: Any) -> date:
    text = str(raw or "").strip()
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        return date.fromisoformat(text[:10])
    if len(text) >= 10 and text[2] == "-" and text[5] == "-":
        return date(int(text[6:10]), int(text[3:5]), int(text[0:2]))
    raise LoadError(f"bad date {raw!r}")


def _account_map(cursor, person_id: int) -> dict[int, int]:
    cursor.execute(
        """
        SELECT account_id, iban
        FROM dbo.account
        WHERE person_id = ?
        ORDER BY account_id
        """,
        (person_id,),
    )
    rows = [(int(aid), str(iban or "").replace(" ", "").upper()) for aid, iban in cursor.fetchall()]
    if len(rows) < 2:
        raise LoadError(f"Barry needs two accounts, found {len(rows)}")
    card_id = None
    current_id = None
    compact_current = CURRENT_IBAN.replace(" ", "").upper()
    for account_id, iban in rows:
        if iban.endswith(CARD_IBAN_MARK) or "XXXX" in iban:
            card_id = account_id
        if iban == compact_current or compact_current in iban:
            current_id = account_id
    if card_id is None or current_id is None or card_id == current_id:
        raise LoadError(f"Could not map credit card / current accounts from {rows}")
    cursor.execute(
        "UPDATE dbo.account SET account_name = ? WHERE account_id = ?",
        ("credit card", card_id),
    )
    cursor.execute(
        "UPDATE dbo.account SET account_name = ? WHERE account_id = ?",
        (CURRENT_IBAN, current_id),
    )
    print(f"account 0 credit card -> account_id={card_id}")
    print(f"account 1 {CURRENT_IBAN} -> account_id={current_id}")
    return {0: card_id, 1: current_id}


def _category_ids(cursor, country_id: int) -> dict[int, int]:
    cursor.execute(
        "SELECT local_code, category_id FROM dbo.dim_category WHERE country_id = ?",
        (country_id,),
    )
    by_code = {int(code): int(cid) for code, cid in cursor.fetchall()}
    if DEFAULT_CATEGORY not in by_code:
        raise LoadError("Ireland remainder category 18 missing")
    return by_code


def load(cursor) -> None:
    if not DOWNLOADED.is_file():
        raise LoadError(f"Missing {DOWNLOADED}")
    raw_list = json.loads(DOWNLOADED.read_text(encoding="utf-8"))
    if not isinstance(raw_list, list):
        raise LoadError(f"{DOWNLOADED}: expected a JSON list")

    cursor.execute(
        """
        SELECT p.id, p.country_id, p.username
        FROM dbo.person p
        WHERE p.username IN (?, ?)
        """,
        PERSON_USERNAMES,
    )
    row = cursor.fetchone()
    if row is None:
        raise LoadError(f"Person {PERSON_USERNAMES} is not in the database")
    person_id, country_id, username = int(row[0]), int(row[1]), str(row[2])
    print(f"person {username} id={person_id}")

    cursor.execute(f"SELECT COUNT(*) FROM {TABLE} WHERE person_id = ?", (person_id,))
    before = int(cursor.fetchone()[0])
    cursor.execute(f"DELETE FROM {TABLE} WHERE person_id = ?", (person_id,))
    print(f"deleted {before} bookings")

    accounts = _account_map(cursor, person_id)
    by_code = _category_ids(cursor, country_id)
    remainder_id = by_code[DEFAULT_CATEGORY]
    general = _category_map(categories_payload(COUNTRY_USERNAME))
    personal: dict[str, list[str]] = {}

    rows: list[tuple[Any, ...]] = []
    by_index = {0: 0, 1: 0}
    seen: set[tuple[int, str]] = set()
    for raw in raw_list:
        if not isinstance(raw, dict):
            continue
        try:
            index = int(raw.get("_account_index", 0))
        except (TypeError, ValueError):
            index = 0
        if index not in accounts:
            raise LoadError(f"unexpected _account_index {index}")
        simplified = simplify_transaction(raw)
        source_id = str(simplified.get("id") or "").strip()
        if not source_id:
            raise LoadError("transaction missing id")
        booked = _parse_booked(simplified.get("date") or raw.get("booking_date"))
        key = (booked.year, source_id)
        if key in seen:
            continue
        seen.add(key)
        code, hit = categorize_with_hit(simplified, general, personal)
        category_id = by_code.get(int(code), remainder_id)
        hit_s = str(hit)[:64] if hit not in (None, "") else None
        iban = str(simplified.get("iban") or "").strip()[:64] or None
        rows.append(
            (
                person_id,
                accounts[index],
                booked.year,
                None,
                source_id[:128],
                _parse_amount(simplified.get("amount")),
                (str(simplified.get("type") or "")[:64] or None),
                (str(simplified.get("name") or "")[:512] or None),
                iban,
                (str(simplified.get("description") or "") or None),
                booked,
                category_id,
                0,
                hit_s,
            )
        )
        by_index[index] += 1

    if not rows:
        raise LoadError("no transactions in downloaded file")
    cursor.fast_executemany = False
    cursor.executemany(
        f"""
        INSERT INTO {TABLE} (
            person_id, account_id, year, bank_id, source_id, amount,
            bank_type, counterparty_name, counterparty_iban, description,
            booked_on, category_id, modification, hit
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    cursor.execute(
        f"""
        UPDATE a
        SET last_booked = x.mx
        FROM dbo.account a
        INNER JOIN (
            SELECT account_id, MAX(booked_on) AS mx
            FROM {TABLE}
            WHERE person_id = ?
            GROUP BY account_id
        ) x ON x.account_id = a.account_id
        WHERE a.person_id = ?
        """,
        (person_id, person_id),
    )
    print(f"inserted {len(rows)} bookings (index 0: {by_index[0]}, index 1: {by_index[1]})")


def main() -> None:
    conn = _connect()
    cursor = conn.cursor()
    try:
        load(cursor)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    print("reload_barry_downloaded complete")


if __name__ == "__main__":
    main()

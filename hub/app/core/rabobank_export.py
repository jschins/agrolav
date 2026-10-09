"""Rabobank bookings.

``dbo.account.format`` = Rabobank uses the same Enable Banking fields as ING.
The counterparty IBAN is read from ``debtor_account`` / ``creditor_account``,
because Rabobank does not put it in the remittance text.
"""
from __future__ import annotations

from typing import Any, Callable

TransactionFetch = Callable[[str, str | None, str | None], list[dict[str, Any]]]


def is_rabobank_format(value: object) -> bool:
    return str(value or "").strip().casefold() == "rabobank"


def _iban_key(iban: object) -> str:
    compact = "".join(str(iban or "").split()).upper()
    return f"iban:{compact}" if compact else ""


def load_account_formats(username: str) -> dict[str, str]:
    """``uid:`` and ``iban:`` keys → ``dbo.account.format`` for this person."""
    from app import enable_sql

    cursor = enable_sql._cursor()
    if cursor is None:
        return {}
    person_id = enable_sql._person_id(cursor, username)
    if person_id is None:
        return {}
    cursor.execute(
        """
        SELECT uid, iban, format
        FROM dbo.account
        WHERE person_id = ?
        """,
        (person_id,),
    )
    formats: dict[str, str] = {}
    for uid, iban, fmt in cursor.fetchall():
        text = str(fmt or "").strip()
        if not text:
            continue
        uid_s = str(uid or "").strip()
        if uid_s:
            formats[f"uid:{uid_s}"] = text
        key = _iban_key(iban)
        if key:
            formats[key] = text
    return formats


def format_for_account(account: dict[str, Any], formats: dict[str, str]) -> str:
    uid = str(account.get("uid") or "").strip()
    if uid and f"uid:{uid}" in formats:
        return formats[f"uid:{uid}"]
    key = _iban_key(account.get("iban"))
    if key:
        return formats.get(key, "")
    return ""


def split_accounts(
    accounts: list[dict[str, Any]],
    formats: dict[str, str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Rabobank accounts, then every other format (including ING and empty)."""
    rabobank: list[dict[str, Any]] = []
    other: list[dict[str, Any]] = []
    for account in accounts:
        if not isinstance(account, dict):
            continue
        if is_rabobank_format(format_for_account(account, formats)):
            rabobank.append(account)
        else:
            other.append(account)
    return rabobank, other


def _compact_iban(value: object) -> str:
    return "".join(str(value or "").split()).upper()


def counterparty_iban(transaction: dict[str, Any]) -> str:
    """Other party's IBAN. The account's own IBAN is not a counterparty."""
    from app.core.categorize import _tx_field

    indicator = str(
        _tx_field(transaction, "credit_debit_indicator", "creditDebitIndicator") or ""
    ).strip().upper()
    key = "debtor_account" if indicator == "CRDT" else "creditor_account"
    block = transaction.get(key) or {}
    if not isinstance(block, dict):
        return ""
    iban = _compact_iban(block.get("iban"))
    own = _compact_iban(transaction.get("_own_iban"))
    if not iban or iban == own:
        return ""
    return iban


def simplify_rabobank(transaction: dict[str, Any]) -> dict[str, Any]:
    """ING simplification, then the Rabobank counterparty IBAN when needed."""
    from app.core.categorize import simplify_transaction

    record = simplify_transaction(transaction)
    if not str(record.get("iban") or "").strip():
        record["iban"] = counterparty_iban(transaction)
    return record


def download_transactions(
    accounts: list[dict[str, Any]],
    *,
    date_from: str | None,
    date_to: str | None,
    fetch: TransactionFetch,
    index_by_uid: dict[str, int] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Tagged transaction copies for the requested period. Dates are not clamped."""
    from app.core.enable_banking import EnableBankingError

    indexes = index_by_uid or {}
    tagged: list[dict[str, Any]] = []
    errors: list[str] = []
    for position, account in enumerate(accounts):
        uid = str(account.get("uid") or "").strip()
        label = str(account.get("iban") or account.get("name") or uid or "account")
        if not uid:
            errors.append(f"{label}: no account uid")
            continue
        try:
            batch = fetch(uid, date_from, date_to)
        except EnableBankingError as exc:
            errors.append(f"{label}: {exc}")
            continue
        index = indexes.get(uid, position)
        own = _compact_iban(account.get("iban"))
        for item in batch if isinstance(batch, list) else []:
            if not isinstance(item, dict):
                continue
            copy = dict(item)
            copy["_account_index"] = index
            copy["_account_uid"] = uid
            copy["_own_iban"] = own
            tagged.append(copy)
    if not tagged and errors:
        raise EnableBankingError("; ".join(errors))
    return tagged, errors


def store_transactions(
    raw_transactions: list[dict[str, Any]],
    *,
    inserted_by_uid: dict[str, int] | None = None,
    inserted_source_ids: list[str] | None = None,
    categorize: bool = True,
) -> dict[str, str]:
    """Store Rabobank rows the same way as an ING download."""
    from app.core.categorize import MOD_UNCALCULATED, recategorize_transactions, remainder_category_code
    from app.sql_replica import ingest_bound_transactions

    rows: list[dict[str, Any]] = []
    for transaction in raw_transactions:
        if not isinstance(transaction, dict):
            continue
        record = simplify_rabobank(transaction)
        record["category"] = remainder_category_code() or 0
        record["hit"] = None
        record["modification"] = MOD_UNCALCULATED
        rows.append(record)
    ingest_bound_transactions(
        rows,
        inserted_by_uid=inserted_by_uid,
        inserted_source_ids=inserted_source_ids,
    )
    if not categorize:
        return {}
    return recategorize_transactions()

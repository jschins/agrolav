"""Raw Rabobank download.

``dbo.account.format`` = Rabobank is saved as Enable Banking returns it.
Nothing is simplified and nothing is written to the transaction tables.
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


def collect_raw(
    accounts: list[dict[str, Any]],
    *,
    date_from: str | None,
    date_to: str | None,
    person: str,
    fetch: TransactionFetch,
) -> tuple[dict[str, Any], list[str]]:
    """Transaction objects for each account, with no local tags added."""
    from app.core.enable_banking import EnableBankingError

    exported: list[dict[str, Any]] = []
    errors: list[str] = []
    for account in accounts:
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
        exported.append(
            {
                "uid": uid,
                "iban": str(account.get("iban") or ""),
                "name": str(account.get("name") or ""),
                "transactions": list(batch) if isinstance(batch, list) else [],
            }
        )
    if not exported and errors:
        raise EnableBankingError("; ".join(errors))
    document = {
        "aspsp": "Rabobank",
        "person": person,
        "date_from": date_from or "",
        "date_to": date_to or "",
        "accounts": exported,
    }
    return document, errors

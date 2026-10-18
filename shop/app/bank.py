"""Automatic bank statement download for the Boog account.

Copied from the hub and trimmed to what the shop needs: pull recent money-in
bookings for the De Boog ING account through the Enable Banking API, then hand
back the counterparty IBAN, account holder name, and amount so a payment can be
identified against an invoice.

Credentials live in agrolav: the app id + PEM used to sign the JWT and the
linked account uid. The shop reads them, signs in memory, and never writes to
agrolav.
"""
from __future__ import annotations

import hashlib
import json
from contextvars import ContextVar, Token
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Callable

BASE_URL = "https://api.enablebanking.com"

# country 6 (De Boog), center 9, person 31
DEBOOG_PERSON_ID = 31
DEBOOG_ACCOUNT_IBAN = "NL16INGB0003121192"

TRANSACTIONS_PAGE_LIMIT = 250
DATE_CHUNK_DAYS = 30
MAX_TRANSACTION_PAGES = 500

# Keep the inclusive period within Enable Banking's 90-day look-back limit.
DEFAULT_HISTORY_DAYS = 89

_psu_headers: ContextVar[dict[str, str]] = ContextVar("bank_psu_headers", default={})


class EnableBankingError(RuntimeError):
    """Raised when the Enable Banking API returns an error response."""


def bind_psu(ip: str, user_agent: str) -> Token[dict[str, str]]:
    """Remember the browser that clicked refresh, for this request only."""
    headers: dict[str, str] = {}
    address = str(ip or "").strip()
    agent = str(user_agent or "").strip()
    if address and address.casefold() != "unknown":
        headers["Psu-Ip-Address"] = address
    if agent:
        headers["Psu-User-Agent"] = agent[:512]
    return _psu_headers.set(headers)


def reset_psu(token: Token[dict[str, str]]) -> None:
    _psu_headers.reset(token)


def current_psu() -> dict[str, str]:
    return dict(_psu_headers.get())


class EnableBankingClient:
    def __init__(self, application_id: str, private_key: str | bytes, timeout: float = 30) -> None:
        if not application_id or not private_key:
            raise EnableBankingError("Missing Enable Banking credentials (app id / key).")
        self._app_id = application_id
        self._private_key = private_key if isinstance(private_key, bytes) else private_key.encode()
        self._timeout = timeout
        self._psu_headers: dict[str, str] = {}

    def _jwt(self) -> str:
        import jwt

        now = int(datetime.now().timestamp())
        headers = {"typ": "JWT", "alg": "RS256", "kid": self._app_id}
        payload = {
            "iss": "enablebanking.com",
            "aud": "api.enablebanking.com",
            "iat": now,
            "exp": now + 3600,
        }
        return str(jwt.encode(payload, self._private_key, algorithm="RS256", headers=headers))

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._jwt()}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def use_psu(self, headers: dict[str, str]) -> None:
        """Headers that mark this download as the user sitting at the browser."""
        self._psu_headers = {str(k): str(v) for k, v in headers.items() if str(v).strip()}

    def _request(
        self,
        method: str,
        path: str,
        extra_headers: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> Any:
        import httpx

        url = f"{BASE_URL}{path}"
        headers = self._headers()
        headers.update(self._psu_headers)
        headers.update(current_psu())
        if extra_headers:
            headers.update(extra_headers)
        response = httpx.request(method, url, headers=headers, timeout=self._timeout, **kwargs)
        if response.status_code >= 400:
            raise EnableBankingError(
                f"{method} {path} failed: {response.status_code} {response.text}"
            )
        if not response.content:
            return None
        try:
            return response.json()
        except ValueError as exc:
            raise EnableBankingError(f"{method} {path} returned non-JSON body") from exc

    def get_transaction_page(
        self,
        account_uid: str,
        *,
        date_from: str | None = None,
        date_to: str | None = None,
        continuation_key: str | None = None,
    ) -> dict[str, Any]:
        """One page of ``GET /accounts/{uid}/transactions``."""
        params: dict[str, str] = {}
        if date_from:
            params["date_from"] = date_from
        if date_to:
            params["date_to"] = date_to
        if continuation_key:
            params["continuation_key"] = continuation_key
        resp = self._request("GET", f"/accounts/{account_uid}/transactions", params=params)
        return resp if isinstance(resp, dict) else {}


# --- transaction pagination, date chunking, dedupe -------------------------


def parse_iso_date(value: str) -> date:
    return date.fromisoformat(str(value)[:10])


def date_period_chunks(
    date_from: str, date_to: str, *, chunk_days: int = DATE_CHUNK_DAYS
) -> list[tuple[str, str]]:
    """Split ``[date_from, date_to]`` into contiguous windows of ``chunk_days``."""
    start = parse_iso_date(date_from)
    end = parse_iso_date(date_to)
    if start > end:
        raise EnableBankingError(f"Invalid transaction period: {date_from} > {date_to}")
    chunks: list[tuple[str, str]] = []
    cursor = start
    while cursor <= end:
        chunk_end = min(cursor + timedelta(days=chunk_days - 1), end)
        chunks.append((cursor.isoformat(), chunk_end.isoformat()))
        cursor = chunk_end + timedelta(days=1)
    return chunks


def transaction_key(tx: dict[str, Any]) -> str:
    ref = tx.get("entry_reference") or tx.get("transaction_id") or tx.get("id")
    if ref is not None and str(ref).strip():
        return str(ref).strip()
    return json.dumps(tx, sort_keys=True, default=str)


def dedupe_transactions(transactions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for tx in transactions:
        key = transaction_key(tx)
        if key in seen:
            continue
        seen.add(key)
        unique.append(tx)
    return unique


def _is_aspsp_error(exc: EnableBankingError) -> bool:
    return "ASPSP_ERROR" in str(exc)


def fetch_transactions_pages(
    client: EnableBankingClient,
    account_uid: str,
    date_from: str | None = None,
    date_to: str | None = None,
) -> tuple[list[dict[str, Any]], bool]:
    """Fetch one API period, following ``continuation_key`` until exhausted.

    Returns ``(transactions, was_truncated)``.
    """
    all_transactions: list[dict[str, Any]] = []
    continuation_key: str | None = None
    base_params: dict[str, str] = {}
    if date_from:
        base_params["date_from"] = date_from
    if date_to:
        base_params["date_to"] = date_to

    pages = 0
    last_batch_len = 0
    while True:
        pages += 1
        if pages > MAX_TRANSACTION_PAGES:
            raise EnableBankingError(
                f"Transaction pagination exceeded {MAX_TRANSACTION_PAGES} pages "
                f"for account {account_uid} ({date_from} .. {date_to})."
            )
        params = dict(base_params)
        if continuation_key:
            params["continuation_key"] = continuation_key
        resp = client._request("GET", f"/accounts/{account_uid}/transactions", params=params)
        if not isinstance(resp, dict):
            resp = {}
        batch = resp.get("transactions")
        if not isinstance(batch, list):
            batch = []
        all_transactions.extend(item for item in batch if isinstance(item, dict))
        last_batch_len = len(batch)
        continuation_key = resp.get("continuation_key")
        if not continuation_key:
            break

    truncated = (
        last_batch_len >= TRANSACTIONS_PAGE_LIMIT
        and date_from is not None
        and date_to is not None
        and parse_iso_date(date_from) < parse_iso_date(date_to)
    )
    return all_transactions, truncated


def fetch_transactions_period(
    client: EnableBankingClient,
    account_uid: str,
    date_from: str,
    date_to: str,
) -> list[dict[str, Any]]:
    """Fetch a date range; split recursively on truncation or ASPSP errors."""
    start = parse_iso_date(date_from)
    end = parse_iso_date(date_to)
    try:
        transactions, truncated = fetch_transactions_pages(client, account_uid, date_from, date_to)
    except EnableBankingError as exc:
        if not _is_aspsp_error(exc) or start >= end:
            raise
        midpoint = start + (end - start) // 2
        left = fetch_transactions_period(client, account_uid, date_from, midpoint.isoformat())
        right = fetch_transactions_period(
            client,
            account_uid,
            (midpoint + timedelta(days=1)).isoformat(),
            date_to,
        )
        return dedupe_transactions(left + right)

    if not truncated or start >= end:
        return transactions

    midpoint = start + (end - start) // 2
    left = fetch_transactions_period(client, account_uid, date_from, midpoint.isoformat())
    right = fetch_transactions_period(
        client,
        account_uid,
        (midpoint + timedelta(days=1)).isoformat(),
        date_to,
    )
    return dedupe_transactions(left + right)


# --- reading the account + credentials from agrolav ------------------------


@dataclass(frozen=True)
class AccountIdentity:
    app_id: str
    pem: str
    account_uid: str
    own_iban: str
    account_name: str


def _tx_field(transaction: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in transaction and transaction.get(name) not in (None, ""):
            return transaction.get(name)
    return None


def _compact_iban(value: object) -> str:
    return "".join(str(value or "").split()).upper()


def read_identity() -> AccountIdentity:
    """``app_id``/``pem``/account uid for country 6, center 9, person 31."""
    from app.orders import connect_bookkeeping, one

    conn = connect_bookkeeping()
    try:
        creds = one(
            conn,
            """
            SELECT TOP 1 app_id, pem
            FROM dbo.enable_connection
            WHERE person_id = ?
              AND pem IS NOT NULL
              AND LTRIM(RTRIM(pem)) <> N''
            ORDER BY CASE WHEN app_id IS NULL OR LTRIM(RTRIM(app_id)) = N'' THEN 1 ELSE 0 END,
                     connection_id
            """,
            (DEBOOG_PERSON_ID,),
        )
        account = one(
            conn,
            """
            SELECT TOP 1 uid, iban, account_name
            FROM dbo.account
            WHERE person_id = ?
              AND uid IS NOT NULL
              AND LTRIM(RTRIM(uid)) <> N''
            ORDER BY CASE WHEN iban = ? THEN 0 ELSE 1 END, account_id
            """,
            (DEBOOG_PERSON_ID, DEBOOG_ACCOUNT_IBAN),
        )
    finally:
        conn.close()

    if creds is None:
        raise EnableBankingError("No Enable Banking credentials for person 31 in agrolav.")
    app_id = str(creds["app_id"] or "").strip()
    pem = str(creds["pem"] or "").strip()
    if not app_id or "PRIVATE KEY" not in pem:
        raise EnableBankingError("Enable Banking credentials for person 31 are unusable.")
    if not pem.endswith("\n"):
        pem += "\n"

    if account is None:
        raise EnableBankingError("No linked bank account for person 31 in agrolav.")
    uid = str(account["uid"] or "").strip()
    if not uid:
        raise EnableBankingError("The De Boog account has no Enable Banking uid.")
    return AccountIdentity(
        app_id=app_id,
        pem=pem,
        account_uid=uid,
        own_iban=_compact_iban(account["iban"]),
        account_name=str(account["account_name"] or "").strip(),
    )


# --- normalising a raw booking into a statement ---------------------------


@dataclass(frozen=True)
class Statement:
    """One money-in booking, reduced to what identifies a payment."""

    key: int
    iban: str
    name: str
    amount_cents: int
    booked_on: str
    description: str


def statement_key(tx: dict[str, Any]) -> int:
    """A stable bigint that survives re-downloads, so a booking is applied once."""
    ref = (
        tx.get("entry_reference")
        or tx.get("transaction_id")
        or tx.get("internal_transaction_id")
        or tx.get("id")
    )
    if ref is not None and str(ref).strip():
        raw = str(ref).strip()
    else:
        raw = json.dumps(
            {
                "booking_date": tx.get("booking_date") or tx.get("bookingDate"),
                "amount": tx.get("transaction_amount") or tx.get("transactionAmount"),
                "indicator": tx.get("credit_debit_indicator") or tx.get("creditDebitIndicator"),
                "debtor": tx.get("debtor"),
                "creditor": tx.get("creditor"),
            },
            sort_keys=True,
            default=str,
        )
    digest = hashlib.sha256(raw.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") & ((1 << 63) - 1)


def _credit_debit(tx: dict[str, Any]) -> str:
    return str(
        _tx_field(tx, "credit_debit_indicator", "creditDebitIndicator") or ""
    ).strip().upper()


def counterparty_iban(tx: dict[str, Any], own_iban: str = "") -> str:
    """Other party's IBAN. The account's own IBAN is never a counterparty."""
    indicator = _credit_debit(tx)
    key = "debtor_account" if indicator == "CRDT" else "creditor_account"
    block = tx.get(key) or {}
    if isinstance(block, dict):
        iban = _compact_iban(block.get("iban"))
        if iban and iban != _compact_iban(own_iban):
            return iban
    # Fall back to an IBAN carried in the remittance text.
    remittance = tx.get("remittance_information") or {}
    if isinstance(remittance, dict):
        lines = remittance.get("unstructured") or []
        if isinstance(lines, str):
            lines = [lines]
        for line in lines:
            text = str(line or "")
            for token in text.replace("\n", " ").split():
                compact = _compact_iban(token.strip(",.;:/"))
                if compact.startswith(("NL", "DE", "BE", "GB")) and len(compact) >= 15:
                    if compact != _compact_iban(own_iban):
                        return compact
    return ""


def counterparty_name(tx: dict[str, Any]) -> str:
    """Account holder name on the other side of the booking."""
    indicator = _credit_debit(tx)
    party_key = "creditor" if indicator == "DBIT" else "debtor"
    party = tx.get(party_key) or {}
    if not isinstance(party, dict):
        party = {}
    return str(party.get("name") or "").strip()


def _amount_cents(tx: dict[str, Any]) -> int:
    block = _tx_field(tx, "transaction_amount", "transactionAmount") or {}
    if not isinstance(block, dict):
        block = {}
    raw = str(block.get("amount") or tx.get("amount") or "0").strip()
    try:
        amount = Decimal(raw or "0")
    except Exception:  # noqa: BLE001
        return 0
    if _credit_debit(tx) != "CRDT":
        amount = -amount
    return int((amount * Decimal(100)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _booked_on(tx: dict[str, Any]) -> str:
    raw = str(
        _tx_field(tx, "booking_date", "bookingDate", "value_date", "valueDate") or ""
    ).strip()
    return raw[:10]


def _description(tx: dict[str, Any]) -> str:
    remittance = tx.get("remittance_information") or {}
    if isinstance(remittance, dict):
        lines = remittance.get("unstructured") or []
        if isinstance(lines, str):
            lines = [lines]
        return " ".join(str(line or "") for line in lines).strip()
    return ""


def to_statement(tx: dict[str, Any], own_iban: str = "") -> Statement | None:
    """A money-in booking, or None when it is money out or has no counterparty."""
    if _credit_debit(tx) != "CRDT":
        return None
    amount_cents = _amount_cents(tx)
    if amount_cents <= 0:
        return None
    iban = counterparty_iban(tx, own_iban)
    return Statement(
        key=statement_key(tx),
        iban=iban,
        name=counterparty_name(tx),
        amount_cents=amount_cents,
        booked_on=_booked_on(tx),
        description=_description(tx),
    )


# --- the one call the admin makes -----------------------------------------


@dataclass(frozen=True)
class DownloadResult:
    statements: tuple[Statement, ...]
    account_name: str
    own_iban: str
    date_from: str
    date_to: str
    errors: tuple[str, ...]


def default_range(today: date | None = None) -> tuple[str, str]:
    ref = today or date.today()
    return (ref - timedelta(days=DEFAULT_HISTORY_DAYS)).isoformat(), ref.isoformat()


def download_statements(
    date_from: str | None = None,
    date_to: str | None = None,
    *,
    today: date | None = None,
    fetch: Callable[..., list[dict[str, Any]]] | None = None,
    identity: AccountIdentity | None = None,
) -> DownloadResult:
    """Download recent money-in bookings for the De Boog account."""
    start, end = default_range(today)
    if date_from:
        start = date_from
    if date_to:
        end = date_to
    if parse_iso_date(start) > parse_iso_date(end):
        raise EnableBankingError(f"Invalid period: {start} > {end}")

    ident = identity if identity is not None else read_identity()
    if fetch is None:
        client = EnableBankingClient(ident.app_id, ident.pem)
        raw = fetch_transactions_period(client, ident.account_uid, start, end)
    else:
        raw = fetch(ident.account_uid, start, end)

    statements: list[Statement] = []
    for tx in raw if isinstance(raw, list) else []:
        if not isinstance(tx, dict):
            continue
        statement = to_statement(tx, ident.own_iban)
        if statement is not None:
            statements.append(statement)

    return DownloadResult(
        statements=tuple(statements),
        account_name=ident.account_name,
        own_iban=ident.own_iban,
        date_from=start,
        date_to=end,
        errors=(),
    )

"""Shop rows in the webshop database. This is not the bookkeeping database.

A debtor order is written against its invoice id in the same transaction as the
invoice (see app.ledger). A Mollie buyer has an invoice but no debtor order row.
Editing happens on the invoice, never on the order.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path


def _load_root_env() -> None:
    """The database settings live in the repository root .env, next to shop/.

    The file is authoritative: it is loaded with override so a stale
    HUB_DATABASE_URL left in the shell that launched the server cannot win over
    it. This mirrors app.main.load_root_env.
    """
    root_env = Path(__file__).resolve().parents[2] / ".env"
    if not root_env.is_file():
        return
    try:
        from dotenv import load_dotenv
    except ModuleNotFoundError:
        return
    load_dotenv(root_env, interpolate=False, override=True)


@dataclass(frozen=True)
class OrderItem:
    slug: str
    number_of_copies: int
    price_cents_per_copy: int


@dataclass(frozen=True)
class Address:
    street: str
    number: str
    postalcode: str
    city: str

    def formatted(self) -> str:
        line = f"{self.street} {self.number}".strip()
        town = f"{self.postalcode} {self.city}".strip()
        return ", ".join(part for part in (line, town) if part)


@dataclass(frozen=True)
class Order:
    invoice_id: int
    token: str
    email: str
    status: str
    items: tuple[OrderItem, ...]
    amount_cents: int
    vat_cents: int
    debtor_id: int
    debtor_name: str
    address: Address

    @property
    def invoice_number(self) -> str:
        return f"BDF-{self.invoice_id}"


def _webshop_url() -> str:
    _load_root_env()
    url = os.environ.get("WEBSHOP_DATABASE_URL", "").strip()
    if url:
        return url
    hub = os.environ.get("HUB_DATABASE_URL", "").strip()
    if not hub:
        raise RuntimeError("HUB_DATABASE_URL is not set")
    swapped = re.sub(r"(?i)(\bDATABASE\s*=\s*)[^;]*", r"\1webshop", hub, count=1)
    if swapped == hub:
        raise RuntimeError("HUB_DATABASE_URL has no DATABASE to point at webshop")
    return swapped


def _agrolav_url() -> str:
    _load_root_env()
    url = os.environ.get("HUB_DATABASE_URL", "").strip()
    if not url:
        raise RuntimeError("HUB_DATABASE_URL is not set")
    return url


def _target(url: str) -> str:
    """Server and database from a connection string, with any password left out."""
    wanted = {"server", "data source", "database", "initial catalog"}
    shown = [
        f"{key.strip()}={value}"
        for key, _, value in (piece.partition("=") for piece in url.split(";"))
        if key.strip().casefold() in wanted
    ]
    return " ".join(shown) or "(unknown server)"


def _open(url: str, *, autocommit: bool, which: str):
    try:
        import pyodbc
    except ModuleNotFoundError as exc:
        raise RuntimeError("pyodbc is not installed") from exc
    try:
        return pyodbc.connect(url, autocommit=autocommit, timeout=15)
    except pyodbc.Error as exc:
        raise RuntimeError(f"{which} connection failed at {_target(url)}: {exc}") from exc


def connect(*, autocommit: bool = False):
    """Every shop table lives here."""
    return _open(_webshop_url(), autocommit=autocommit, which="webshop")


def connect_bookkeeping(*, autocommit: bool = False):
    """Read the Boog account in agrolav. The shop never writes there."""
    return _open(_agrolav_url(), autocommit=autocommit, which="agrolav")


def query(conn, sql: str, params: tuple = ()) -> list[dict]:
    cursor = conn.cursor()
    cursor.execute(sql, params) if params else cursor.execute(sql)
    if cursor.description is None:
        return []
    names = [column[0] for column in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


def one(conn, sql: str, params: tuple = ()) -> dict | None:
    found = query(conn, sql, params)
    return found[0] if found else None


def run(conn, sql: str, params: tuple = ()) -> None:
    cursor = conn.cursor()
    cursor.execute(sql, params) if params else cursor.execute(sql)


def insert_id(conn, sql: str, params: tuple = ()) -> int:
    cursor = conn.cursor()
    cursor.execute(sql, params) if params else cursor.execute(sql)
    row = cursor.fetchone()
    if row is None or row[0] is None:
        raise RuntimeError("geen nieuwe sleutel")
    return int(row[0])


def find_address(
    conn,
    *,
    street: str,
    number: str,
    postalcode: str,
    city: str,
) -> int | None:
    """An address is complete with city + street + number, or with postcode + number.
    Only a complete address can match an existing row."""
    if not number:
        return None
    if city and street:
        row = one(
            conn,
            """
            SELECT id FROM dbo.address
            WHERE [number] = ? AND street = ? AND city = ?
            ORDER BY id
            """,
            (number, street, city),
        )
        if row is not None:
            return int(row["id"])
    if postalcode:
        row = one(
            conn,
            """
            SELECT id FROM dbo.address
            WHERE [number] = ? AND postalcode = ?
            ORDER BY id
            """,
            (number, postalcode),
        )
        if row is not None:
            return int(row["id"])
    return None


def save_address(conn, address: Address) -> int | None:
    """Reuse the address already on file, and otherwise store a new one."""
    existing = find_address(
        conn,
        street=address.street,
        number=address.number,
        postalcode=address.postalcode,
        city=address.city,
    )
    if existing is not None:
        run(
            conn,
            "UPDATE dbo.address SET street = ?, [number] = ?, postalcode = ?, city = ? WHERE id = ?",
            (address.street, address.number, address.postalcode, address.city, existing),
        )
        return existing
    if not any((address.street, address.number, address.postalcode, address.city)):
        return None
    return insert_id(
        conn,
        "INSERT INTO dbo.address (street, [number], postalcode, city) OUTPUT INSERTED.id VALUES (?, ?, ?, ?)",
        (address.street, address.number, address.postalcode, address.city),
    )


def address_by_id(conn, address_id: int | None) -> Address:
    if address_id is None:
        return Address("", "", "", "")
    row = one(
        conn,
        "SELECT street, [number], postalcode, city FROM dbo.address WHERE id = ?",
        (int(address_id),),
    )
    if row is None:
        return Address("", "", "", "")
    return Address(
        street=str(row["street"] or ""),
        number=str(row["number"] or ""),
        postalcode=str(row["postalcode"] or ""),
        city=str(row["city"] or ""),
    )


def _lines_for(conn, invoice_id: int) -> tuple[OrderItem, ...]:
    rows = query(
        conn,
        """
        SELECT slug, number_of_copies, price_cents_per_copy
        FROM dbo.orderlines
        WHERE order_id = ?
        ORDER BY id
        """,
        (invoice_id,),
    )
    return tuple(
        OrderItem(
            slug=row["slug"],
            number_of_copies=row["number_of_copies"],
            price_cents_per_copy=row["price_cents_per_copy"],
        )
        for row in rows
    )


def _order_from_row(conn, row: dict) -> Order:
    return Order(
        invoice_id=int(row["invoice_id"]),
        token=str(row["token"] or ""),
        email=row["email"],
        status=row["status"],
        items=_lines_for(conn, int(row["invoice_id"])),
        amount_cents=row["amount_cents"],
        vat_cents=row["vat_cents"],
        debtor_id=int(row["debtor_id"]),
        debtor_name=row["debtor_name"],
        address=address_by_id(conn, row["address_id"]),
    )


_ORDER_SELECT = """
    SELECT o.invoice_id, o.token, o.email, o.status, o.amount_cents, o.vat_cents,
           d.id AS debtor_id, d.name AS debtor_name, d.address_id
    FROM dbo.orders o
    JOIN dbo.debtors d ON d.id = o.debtor_id
"""


def get_order(conn, invoice_id: int | str) -> Order | None:
    try:
        key = int(invoice_id)
    except (TypeError, ValueError):
        return None
    row = one(conn, f"{_ORDER_SELECT} WHERE o.invoice_id = ?", (key,))
    if row is None:
        return None
    return _order_from_row(conn, row)


def get_order_by_token(conn, token: str) -> Order | None:
    """The order page URL carries the random token, not the INT counter."""
    key = str(token or "").strip()
    if not key:
        return None
    row = one(conn, f"{_ORDER_SELECT} WHERE o.token = ?", (key,))
    if row is None:
        return None
    return _order_from_row(conn, row)


def order_number(invoice_id: int) -> str:
    """Human-readable order number, using the invoice id, e.g. DB-100000."""
    return f"DB-{int(invoice_id)}"


def orders_awaiting_send(conn) -> list[Order]:
    """Orders whose linked invoice is still prepared for delivery."""
    rows = query(
        conn,
        f"""
        {_ORDER_SELECT}
        INNER JOIN dbo.invoices i ON i.id = o.invoice_id
        WHERE i.status = N'prepared'
        ORDER BY o.invoice_id
        """,
    )
    return [_order_from_row(conn, row) for row in rows]


def orders_with_sent_invoices(conn) -> list[Order]:
    """Orders with invoices already sent, including those since paid."""
    rows = query(
        conn,
        f"""
        {_ORDER_SELECT}
        INNER JOIN dbo.invoices i ON i.id = o.invoice_id
        WHERE i.sent_at IS NOT NULL
        ORDER BY o.invoice_id
        """,
    )
    return [_order_from_row(conn, row) for row in rows]

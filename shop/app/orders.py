"""Shop rows in the webshop database. This is not the bookkeeping database.

An order is written the moment an account buyer orders on the website, and its
invoice is written in the same breath (see app.ledger); only orders from before
that rule still arrive without one. A Mollie buyer has no order, only an
invoice, paid at checkout. Editing happens on the invoice, never on the order.
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
    id: int
    token: str
    email: str
    status: str
    items: tuple[OrderItem, ...]
    amount_cents: int
    vat_cents: int
    debtor_id: int
    debtor_name: str
    address: Address
    invoice_number: str | None


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


def _lines_for(conn, order_id: int) -> tuple[OrderItem, ...]:
    rows = query(
        conn,
        """
        SELECT slug, number_of_copies, price_cents_per_copy
        FROM dbo.orderlines
        WHERE order_id = ?
        ORDER BY id
        """,
        (order_id,),
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
        id=int(row["id"]),
        token=str(row["token"] or ""),
        email=row["email"],
        status=row["status"],
        items=_lines_for(conn, int(row["id"])),
        amount_cents=row["amount_cents"],
        vat_cents=row["vat_cents"],
        debtor_id=int(row["debtor_id"]),
        debtor_name=row["debtor_name"],
        address=address_by_id(conn, row["address_id"]),
        invoice_number=row["invoice_number"],
    )


_ORDER_SELECT = """
    SELECT o.id, o.token, o.email, o.status, o.amount_cents, o.vat_cents, o.invoice_number,
           d.id AS debtor_id, d.name AS debtor_name, d.address_id
    FROM dbo.orders o
    JOIN dbo.debtors d ON d.id = o.debtor_id
"""


def get_order(conn, order_id: int | str) -> Order | None:
    try:
        key = int(order_id)
    except (TypeError, ValueError):
        return None
    row = one(conn, f"{_ORDER_SELECT} WHERE o.id = ?", (key,))
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


def order_number(order_id: int) -> str:
    """Human-readable order number, e.g. order 100000 -> DB-100000."""
    return f"DB-{int(order_id)}"


def orders_awaiting_send(conn) -> list[Order]:
    """Orders without an invoice and orders whose invoice is still prepared.

    That is an order without an invoice (from before invoices were written at
    ordering time) plus an order whose invoice is still a draft ('prepared').
    Sent and paid invoices appear in orders_with_sent_invoices instead.
    """
    rows = query(
        conn,
        f"""
        {_ORDER_SELECT}
        LEFT JOIN dbo.invoices i
            ON i.id = CASE WHEN o.invoice_number LIKE 'DBF-%'
                           THEN TRY_CONVERT(int, RIGHT(o.invoice_number, LEN(o.invoice_number) - 4)) END
        WHERE o.invoice_number IS NULL OR i.status = N'prepared'
        ORDER BY o.id
        """,
    )
    return [_order_from_row(conn, row) for row in rows]


def orders_with_sent_invoices(conn) -> list[Order]:
    """Orders whose invoice was sent; paid invoices remain in this history list."""
    rows = query(
        conn,
        f"""
        {_ORDER_SELECT}
        INNER JOIN dbo.invoices i
            ON i.id = CASE WHEN o.invoice_number LIKE 'DBF-%'
                           THEN TRY_CONVERT(int, RIGHT(o.invoice_number, LEN(o.invoice_number) - 4)) END
        WHERE i.status IN (N'sent', N'paid')
        ORDER BY o.id
        """,
    )
    return [_order_from_row(conn, row) for row in rows]


def mark_invoiced(conn, order_id: int, invoice_number: str) -> None:
    run(
        conn,
        "UPDATE dbo.orders SET invoice_number = ?, status = 'invoiced' WHERE id = ?",
        (invoice_number, order_id),
    )
    conn.commit()

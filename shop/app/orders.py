"""Shop orders in a local SQLite file. This is not the bookkeeping database."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class OrderItem:
    slug: str
    number_of_copies: int
    price_cents_per_copy: int


@dataclass(frozen=True)
class Address:
    name: str
    street: str
    postcode: str
    city: str


@dataclass(frozen=True)
class Order:
    id: str
    token: str
    email: str
    status: str
    mollie_id: str | None
    items: tuple[OrderItem, ...]
    amount_cents: int
    vat_cents: int
    address: Address


def connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def insert_order(
    conn: sqlite3.Connection,
    *,
    order_id: str,
    token: str,
    email: str,
    address: Address,
    items: list[OrderItem],
    amount_cents: int,
    vat_cents: int,
) -> None:
    posted = {
        "name": address.name,
        "street": address.street,
        "postcode": address.postcode,
        "city": address.city,
    }
    conn.execute(
        """
        INSERT INTO orders
            (id, token, email, status, mollie_id, amount_cents, vat_cents, created_at, address_json)
        VALUES (?, ?, ?, 'open', NULL, ?, ?, ?, ?)
        """,
        (
            order_id,
            token,
            email,
            amount_cents,
            vat_cents,
            datetime.now(timezone.utc).isoformat(),
            json.dumps(posted),
        ),
    )
    conn.executemany(
        """
        INSERT INTO order_lines (order_id, slug, number_of_copies, price_cents_per_copy)
        VALUES (?, ?, ?, ?)
        """,
        [
            (order_id, item.slug, item.number_of_copies, item.price_cents_per_copy)
            for item in items
        ],
    )
    conn.commit()


def attach_payment(conn: sqlite3.Connection, order_id: str, mollie_id: str) -> None:
    conn.execute("UPDATE orders SET mollie_id = ? WHERE id = ?", (mollie_id, order_id))
    conn.commit()


def _address_from_json(raw: object) -> Address:
    data = json.loads(raw) if isinstance(raw, str) and raw else {}
    if not isinstance(data, dict):
        data = {}
    return Address(
        name=str(data.get("name") or ""),
        street=str(data.get("street") or ""),
        postcode=str(data.get("postcode") or ""),
        city=str(data.get("city") or ""),
    )


def _lines_for(conn: sqlite3.Connection, order_id: str) -> tuple[OrderItem, ...]:
    rows = conn.execute(
        """
        SELECT slug, number_of_copies, price_cents_per_copy
        FROM order_lines
        WHERE order_id = ?
        ORDER BY id
        """,
        (order_id,),
    ).fetchall()
    return tuple(
        OrderItem(
            slug=row["slug"],
            number_of_copies=row["number_of_copies"],
            price_cents_per_copy=row["price_cents_per_copy"],
        )
        for row in rows
    )


def _order_from_row(conn: sqlite3.Connection, row: sqlite3.Row) -> Order:
    items = _lines_for(conn, row["id"])
    return Order(
        id=row["id"],
        token=row["token"],
        email=row["email"],
        status=row["status"],
        mollie_id=row["mollie_id"],
        items=items,
        amount_cents=row["amount_cents"],
        vat_cents=row["vat_cents"],
        address=_address_from_json(row["address_json"]),
    )


def get_order(conn: sqlite3.Connection, order_id: str) -> Order | None:
    row = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    if row is None:
        return None
    return _order_from_row(conn, row)


def order_by_payment(conn: sqlite3.Connection, mollie_id: str) -> Order | None:
    row = conn.execute("SELECT * FROM orders WHERE mollie_id = ?", (mollie_id,)).fetchone()
    if row is None:
        return None
    return _order_from_row(conn, row)


def apply_payment(
    conn: sqlite3.Connection,
    order: Order,
    *,
    status: str,
    amount_cents: int,
    order_id_from_provider: str,
) -> str:
    """Record a payment status fetched from Mollie. A paid order is never reopened."""
    if order_id_from_provider != order.id:
        return "order-mismatch"
    if amount_cents != order.amount_cents:
        return "amount-mismatch"
    if order.status == "paid":
        return "paid"
    if status == "paid":
        conn.execute("UPDATE orders SET status = 'paid' WHERE id = ?", (order.id,))
        conn.commit()
        return "paid"
    if status in {"canceled", "expired", "failed"} and order.status == "open":
        conn.execute("UPDATE orders SET status = ? WHERE id = ?", (status, order.id))
        conn.commit()
        return status
    return order.status

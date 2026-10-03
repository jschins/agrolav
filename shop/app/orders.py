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
    title: str
    price_cents: int
    filename: str


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


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS orders (
            id TEXT PRIMARY KEY,
            token TEXT NOT NULL,
            email TEXT NOT NULL,
            status TEXT NOT NULL,
            mollie_id TEXT,
            items_json TEXT NOT NULL,
            amount_cents INTEGER NOT NULL,
            vat_cents INTEGER NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    return conn


def insert_order(
    conn: sqlite3.Connection,
    *,
    order_id: str,
    token: str,
    email: str,
    items: list[OrderItem],
    amount_cents: int,
    vat_cents: int,
) -> None:
    payload = [
        {
            "slug": item.slug,
            "title": item.title,
            "price_cents": item.price_cents,
            "filename": item.filename,
        }
        for item in items
    ]
    conn.execute(
        """
        INSERT INTO orders
            (id, token, email, status, mollie_id, items_json, amount_cents, vat_cents, created_at)
        VALUES (?, ?, ?, 'open', NULL, ?, ?, ?, ?)
        """,
        (
            order_id,
            token,
            email,
            json.dumps(payload),
            amount_cents,
            vat_cents,
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    conn.commit()


def attach_payment(conn: sqlite3.Connection, order_id: str, mollie_id: str) -> None:
    conn.execute("UPDATE orders SET mollie_id = ? WHERE id = ?", (mollie_id, order_id))
    conn.commit()


def _order_from_row(row: sqlite3.Row) -> Order:
    items = tuple(OrderItem(**item) for item in json.loads(row["items_json"]))
    return Order(
        id=row["id"],
        token=row["token"],
        email=row["email"],
        status=row["status"],
        mollie_id=row["mollie_id"],
        items=items,
        amount_cents=row["amount_cents"],
        vat_cents=row["vat_cents"],
    )


def get_order(conn: sqlite3.Connection, order_id: str) -> Order | None:
    row = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    if row is None:
        return None
    return _order_from_row(row)


def order_by_payment(conn: sqlite3.Connection, mollie_id: str) -> Order | None:
    row = conn.execute("SELECT * FROM orders WHERE mollie_id = ?", (mollie_id,)).fetchone()
    if row is None:
        return None
    return _order_from_row(row)


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

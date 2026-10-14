"""Shop orders in agrolav. This is not the bookkeeping database."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone


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


def connect(*, autocommit: bool = False):
    url = os.environ.get("HUB_DATABASE_URL", "").strip()
    if not url:
        raise RuntimeError("HUB_DATABASE_URL is not set")
    try:
        import pyodbc
    except ModuleNotFoundError as exc:
        raise RuntimeError("pyodbc is not installed") from exc
    try:
        return pyodbc.connect(url, autocommit=autocommit, timeout=15)
    except pyodbc.Error as exc:
        raise RuntimeError("agrolav login failed") from exc


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


def identity(conn) -> int:
    row = one(conn, "SELECT CAST(SCOPE_IDENTITY() AS int) AS id")
    if row is None or row["id"] is None:
        raise RuntimeError("geen nieuwe sleutel")
    return int(row["id"])


def insert_order(
    conn,
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
    run(
        conn,
        """
        INSERT INTO dbo.shop_orders
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
    for item in items:
        run(
            conn,
            """
            INSERT INTO dbo.shop_orderlines (order_id, slug, number_of_copies, price_cents_per_copy)
            VALUES (?, ?, ?, ?)
            """,
            (order_id, item.slug, item.number_of_copies, item.price_cents_per_copy),
        )
    conn.commit()


def attach_payment(conn, order_id: str, mollie_id: str) -> None:
    run(conn, "UPDATE dbo.shop_orders SET mollie_id = ? WHERE id = ?", (mollie_id, order_id))
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


def _lines_for(conn, order_id: str) -> tuple[OrderItem, ...]:
    rows = query(
        conn,
        """
        SELECT slug, number_of_copies, price_cents_per_copy
        FROM dbo.shop_orderlines
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


def get_order(conn, order_id: str) -> Order | None:
    row = one(
        conn,
        """
        SELECT id, token, email, status, mollie_id, amount_cents, vat_cents, address_json
        FROM dbo.shop_orders WHERE id = ?
        """,
        (order_id,),
    )
    if row is None:
        return None
    return _order_from_row(conn, row)


def order_by_payment(conn, mollie_id: str) -> Order | None:
    row = one(
        conn,
        """
        SELECT id, token, email, status, mollie_id, amount_cents, vat_cents, address_json
        FROM dbo.shop_orders WHERE mollie_id = ?
        """,
        (mollie_id,),
    )
    if row is None:
        return None
    return _order_from_row(conn, row)


def apply_payment(
    conn,
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
        run(conn, "UPDATE dbo.shop_orders SET status = 'paid' WHERE id = ?", (order.id,))
        conn.commit()
        return "paid"
    if status in {"canceled", "expired", "failed"} and order.status == "open":
        run(conn, "UPDATE dbo.shop_orders SET status = ? WHERE id = ?", (status, order.id))
        conn.commit()
        return status
    return order.status

"""Load shop/bestellingen.json into webshop invoices + orders.

Fills: invoices, invoicelines, orders, orderlines.

``invoice_id`` = WooCommerce ``id`` + 1_000_000, so public numbers are
``DB-{id}`` / ``DBF-{id}`` and never collide with live shop ids from 100000.

Every WooCommerce order becomes a debtor order+invoice. Guests
(``customer_id`` 0) share debtor id 0. Registered customers keep their
WooCommerce customer_id as ``debtors.id``. Billing email/address from the
JSON are stored when present.

From the repo root (needs pyodbc + HUB_DATABASE_URL or WEBSHOP_DATABASE_URL):

  shop\\.venv\\Scripts\\python.exe scripts\\load_bestellingen.py

  # or:
  cd shop
  uv run python ../scripts/load_bestellingen.py

Replaces existing rows in the four tables (and upserts the debtors used).
"""
from __future__ import annotations

import json
import os
import re
import secrets
import sys
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHOP = ROOT / "shop"
ENV_PATH = ROOT / ".env"
SHOP_VENV_PYTHON = SHOP / ".venv" / "Scripts" / "python.exe"
SOURCE = SHOP / "bestellingen.json"

GUEST_DEBTOR_ID = 0
INVOICE_ID_OFFSET = 1_000_000
ACCOUNT_DUE_DAYS = 14
PLACEHOLDER_EMAIL = "import-{id}@invalid.local"
PLACEHOLDER_VAT = "-"
PLACEHOLDER_CODE = "IMPORT-{id}"


def load_env() -> None:
    if not ENV_PATH.is_file():
        return
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ[key.strip()] = value.strip()


def connection_url() -> str:
    url = os.environ.get("WEBSHOP_DATABASE_URL", "").strip()
    if url:
        return url
    hub = os.environ.get("HUB_DATABASE_URL", "").strip()
    if not hub:
        raise SystemExit("HUB_DATABASE_URL is not set")
    swapped = re.sub(r"(?i)(\bDATABASE\s*=\s*)[^;]*", r"\1webshop", hub, count=1)
    if swapped == hub:
        raise SystemExit("HUB_DATABASE_URL has no DATABASE to point at webshop")
    return swapped


def connect():
    try:
        import pyodbc
    except ModuleNotFoundError as exc:
        raise SystemExit(
            "pyodbc is not installed in this Python.\n"
            f"Use the shop venv instead, e.g.:\n"
            f"  {SHOP_VENV_PYTHON} scripts\\load_bestellingen.py"
        ) from exc
    return pyodbc.connect(connection_url(), autocommit=False, timeout=60)


def money_cents(value: object) -> int:
    text = str(value if value is not None else "").strip().replace(",", ".")
    if not text:
        return 0
    amount = Decimal(text).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return int(amount * 100)


def parse_when(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def fmt_stamp(when: datetime) -> str:
    return when.strftime("%Y-%m-%d %H:%M")


def cell(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def debtor_display_name(billing: dict, customer_id: int) -> str:
    company = cell(billing.get("company"))
    last_name = cell(billing.get("last_name"))
    first_name = cell(billing.get("first_name"))
    if company:
        return company
    full = " ".join(part for part in (first_name, last_name) if part)
    if full:
        return full
    if customer_id > 0:
        return f"Klant {customer_id}"
    return "Gast (WooCommerce)"


def slug_for(product_id: object) -> str:
    return f"woo-{cell(product_id) or '0'}"


def split_street(billing: dict) -> tuple[str, str, str, str] | None:
    """Return (street, number, postalcode, city) or None if too incomplete."""
    street = cell(billing.get("address_1"))
    number = cell(billing.get("house_number"))
    postal = cell(billing.get("postcode"))
    city = cell(billing.get("city"))
    if not number and street:
        # "Oosteinde 136" → street / number when house_number is empty.
        match = re.match(r"^(.*\S)\s+(\d+\S*)$", street)
        if match:
            street, number = match.group(1), match.group(2)
    if not (street or number or postal or city):
        return None
    return (street or "-", number or "-", postal or "-", city or "-")


def invoice_status(woo_status: str, paid_at: datetime | None) -> tuple[str, int, str | None]:
    status = (woo_status or "").strip().lower()
    if paid_at is not None:
        return "paid", 0, fmt_stamp(paid_at)
    if status in {"cancelled", "refunded"}:
        return "prepared", 0, None
    return "prepared", 1, None


def clear_four_tables(cursor) -> None:
    cursor.execute("DELETE FROM dbo.orderlines")
    cursor.execute("DELETE FROM dbo.orders")
    cursor.execute("DELETE FROM dbo.invoicelines")
    cursor.execute("DELETE FROM dbo.invoices")


def insert_address(cursor, parts: tuple[str, str, str, str]) -> int:
    street, number, postal, city = parts
    cursor.execute(
        """
        INSERT INTO dbo.address (street, [number], postalcode, city)
        OUTPUT INSERTED.id
        VALUES (?, ?, ?, ?)
        """,
        (street, number, postal, city),
    )
    return int(cursor.fetchone()[0])


def upsert_debtor(
    cursor,
    *,
    debtor_id: int,
    name: str,
    email: str,
    address_id: int | None,
) -> None:
    code = PLACEHOLDER_CODE.format(id=debtor_id)
    mail = email or PLACEHOLDER_EMAIL.format(id=debtor_id)
    cursor.execute("SELECT id FROM dbo.debtors WHERE id = ?", (debtor_id,))
    if cursor.fetchone():
        cursor.execute(
            """
            UPDATE dbo.debtors
            SET name = ?, email = ?, vat_number = ?, code = ?, address_id = ?
            WHERE id = ?
            """,
            (name, mail, PLACEHOLDER_VAT, code, address_id, debtor_id),
        )
        return
    cursor.execute("SET IDENTITY_INSERT dbo.debtors ON")
    cursor.execute(
        """
        INSERT INTO dbo.debtors (id, name, email, vat_number, code, address_id, iban)
        VALUES (?, ?, ?, ?, ?, ?, NULL)
        """,
        (debtor_id, name, mail, PLACEHOLDER_VAT, code, address_id),
    )
    cursor.execute("SET IDENTITY_INSERT dbo.debtors OFF")


def build_debtors(orders: list[dict]) -> dict[int, dict]:
    """customer_id → latest billing snapshot (by date_created). Guest → id 0."""
    latest: dict[int, tuple[str, dict]] = {}
    for order in orders:
        if not isinstance(order, dict):
            continue
        try:
            customer_id = int(order.get("customer_id") or 0)
        except (TypeError, ValueError):
            customer_id = 0
        debtor_id = GUEST_DEBTOR_ID if customer_id <= 0 else customer_id
        billing = order.get("billing") if isinstance(order.get("billing"), dict) else {}
        when = cell(order.get("date_created"))
        previous = latest.get(debtor_id)
        if previous is None or when >= previous[0]:
            latest[debtor_id] = (when, billing)
    out: dict[int, dict] = {}
    for debtor_id, (_when, billing) in latest.items():
        out[debtor_id] = {
            "name": debtor_display_name(billing, debtor_id),
            "email": cell(billing.get("email")),
            "billing": billing,
        }
    if GUEST_DEBTOR_ID not in out:
        out[GUEST_DEBTOR_ID] = {
            "name": "Gast (WooCommerce)",
            "email": "",
            "billing": {},
        }
    return out


def load() -> int:
    load_env()
    if not SOURCE.is_file():
        raise SystemExit(f"missing {SOURCE}")
    raw = json.loads(SOURCE.read_text(encoding="utf-8"))
    orders = raw.get("orders") if isinstance(raw, dict) else None
    if not isinstance(orders, list):
        raise SystemExit("bestellingen.json has no orders list")

    debtors = build_debtors(orders)
    book_titles: dict[str, str] = {}

    conn = connect()
    cursor = conn.cursor()
    inserted = 0
    skipped_no_lines = 0
    addresses_written = 0
    try:
        clear_four_tables(cursor)

        for debtor_id, info in sorted(debtors.items()):
            address_id = None
            parts = split_street(info["billing"])
            if parts is not None:
                address_id = insert_address(cursor, parts)
                addresses_written += 1
            upsert_debtor(
                cursor,
                debtor_id=debtor_id,
                name=info["name"],
                email=info["email"],
                address_id=address_id,
            )

        cursor.execute("SET IDENTITY_INSERT dbo.invoices ON")
        for order in orders:
            if not isinstance(order, dict):
                continue
            try:
                woo_id = int(order.get("id"))
            except (TypeError, ValueError):
                continue
            invoice_id = woo_id + INVOICE_ID_OFFSET
            lines = order.get("line_items")
            if not isinstance(lines, list) or not lines:
                skipped_no_lines += 1
                continue
            try:
                customer_id = int(order.get("customer_id") or 0)
            except (TypeError, ValueError):
                customer_id = 0
            debtor_id = GUEST_DEBTOR_ID if customer_id <= 0 else customer_id
            billing = order.get("billing") if isinstance(order.get("billing"), dict) else {}
            created = parse_when(order.get("date_created"))
            paid_at = parse_when(order.get("date_paid"))
            when = created or paid_at or datetime(1970, 1, 1, 0, 0)
            ordered_at = fmt_stamp(when)
            due = when.date() + timedelta(days=ACCOUNT_DUE_DAYS)
            payable = money_cents(order.get("total"))
            porto = money_cents(order.get("shipping_total"))
            vat_cents = money_cents(order.get("total_tax"))
            status, open_factor, paid_stamp = invoice_status(cell(order.get("status")), paid_at)
            open_cents = payable * open_factor
            email = cell(billing.get("email")) or PLACEHOLDER_EMAIL.format(id=debtor_id)
            woo_status = cell(order.get("status")) or "imported"

            cursor.execute(
                """
                INSERT INTO dbo.invoices (
                    id, token, debtor_id, customer_id, mollie_id, mollie_settlement_id,
                    ordered_at, due_on, payable_cents, open_cents, portokosten_cents,
                    status, sent_at, paid_at
                )
                VALUES (?, ?, ?, NULL, NULL, NULL, ?, ?, ?, ?, ?, ?, NULL, ?)
                """,
                (
                    invoice_id,
                    secrets.token_urlsafe(32),
                    debtor_id,
                    ordered_at,
                    due.isoformat(),
                    payable,
                    open_cents,
                    porto if porto else None,
                    status,
                    paid_stamp,
                ),
            )
            for line in lines:
                if not isinstance(line, dict):
                    continue
                product_id = cell(line.get("product_id")) or "0"
                name = cell(line.get("name"))
                if product_id and name and product_id not in book_titles:
                    book_titles[product_id] = name
                copies = int(float(line.get("quantity") or 0))
                price = money_cents(line.get("price"))
                cursor.execute(
                    """
                    INSERT INTO dbo.invoicelines
                        (invoice_id, slug, number_of_copies, price_cents_per_copy)
                    VALUES (?, ?, ?, ?)
                    """,
                    (invoice_id, slug_for(product_id), copies, price),
                )
            cursor.execute(
                """
                INSERT INTO dbo.orders (
                    invoice_id, token, email, status, amount_cents, vat_cents,
                    created_at, debtor_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    invoice_id,
                    secrets.token_hex(16),
                    email,
                    woo_status,
                    payable,
                    vat_cents,
                    ordered_at,
                    debtor_id,
                ),
            )
            for line in lines:
                if not isinstance(line, dict):
                    continue
                product_id = cell(line.get("product_id")) or "0"
                copies = int(float(line.get("quantity") or 0))
                price = money_cents(line.get("price"))
                cursor.execute(
                    """
                    INSERT INTO dbo.orderlines
                        (order_id, slug, number_of_copies, price_cents_per_copy)
                    VALUES (?, ?, ?, ?)
                    """,
                    (invoice_id, slug_for(product_id), copies, price),
                )
            inserted += 1
        cursor.execute("SET IDENTITY_INSERT dbo.invoices OFF")

        cursor.execute("SELECT ISNULL(MAX(id), 99999) FROM dbo.invoices")
        max_id = int(cursor.fetchone()[0])
        cursor.execute(f"DBCC CHECKIDENT (N'dbo.invoices', RESEED, {max_id})")

        conn.commit()
    except Exception:
        conn.rollback()
        try:
            cursor.execute("SET IDENTITY_INSERT dbo.invoices OFF")
            cursor.execute("SET IDENTITY_INSERT dbo.debtors OFF")
        except Exception:  # noqa: BLE001
            pass
        raise
    finally:
        conn.close()

    print(
        f"inserted {inserted} invoices+orders "
        f"(invoice_id = woo id + {INVOICE_ID_OFFSET}; "
        f"{skipped_no_lines} skipped: no lines; "
        f"{addresses_written} addresses; {len(book_titles)} book titles seen)"
    )
    print_report()
    return 0


def print_report() -> None:
    print(
        f"""
=== Cannot upload (no matching column / not in JSON) ===
- VAT number, IBAN: not in the WooCommerce export → debtors.vat_number='-', iban NULL.
- Debtor bestelcode: synthesized as IMPORT-{{id}} (not a real ship-before-payment code).
- Mollie payment / settlement ids: JSON has payment_method names only, not Mollie ids.
- WooCommerce line_id / variation_id / sku: line tables only store slug/copies/price;
  slug is woo-{{product_id}}; book title is not a column.
- Line subtotal / line total / line tax: only unit price × quantity are stored.
- Phone, country, address_2, shipping address, customer_note, discount_total,
  payment_method, invoice_number / number from WooCommerce: no shop columns.
- Guest identity: all customer_id=0 share debtors.id=0 (latest guest billing wins
  for that debtor row); per-order billing email still goes on orders.email.

=== Numbering ===
- invoice_id / orders.invoice_id = WooCommerce id + {INVOICE_ID_OFFSET}
  (e.g. woo 4975 → DB-1004975 / DBF-1004975).

=== Columns unused or only placeholder after this load ===
invoices: customer_id, mollie_id, mollie_settlement_id, sent_at
  (token generated; invoices.portokosten_cents set when shipping_total > 0)
orders:   (vat_cents from total_tax; email/status/amount filled; no portokosten column)
debtors:  iban; vat_number/code are placeholders; address_id set when billing has an address
customers, stock, payments, bookings, reminders: not touched
address:  written for debtors with billing street data (not per order)
""".strip()
    )


if __name__ == "__main__":
    try:
        raise SystemExit(load())
    except Exception as exc:  # noqa: BLE001
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

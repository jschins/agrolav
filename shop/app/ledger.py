"""Buyer subledger in the webshop database.

beheer_boog stays the general ledger in agrolav. This module reads bookings from
there and does not write a booking, a category, or a modification. Every row it
writes here belongs to one of two buyers:

  a debtor   -- an account company; the administrator invoices it after the mail
                order has been sent, so its invoices can stay open.
  a customer -- a Mollie buyer; invoiced and paid at checkout.
"""
from __future__ import annotations

import re
import secrets
import uuid
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP

from app.catalog import Book, Catalog
from app.orders import (
    Address,
    Order,
    address_by_id,
    connect,
    connect_bookkeeping,
    get_order,
    insert_id,
    mark_invoiced,
    one,
    query,
    run,
    save_address,
)

ACCOUNT_DUE_DAYS = 14
REMINDER_STEPS = (
    ("before_7", -7),
    ("due", 0),
    ("after_14", 14),
    ("after_30", 30),
)


@dataclass(frozen=True)
class InvoiceLine:
    slug: str
    number_of_copies: int
    price_cents_per_copy: int


@dataclass(frozen=True)
class Invoice:
    number: str
    name: str
    email: str
    address: str
    vat_number: str
    ordered_at: str
    due_on: date
    payable_cents: int
    open_cents: int
    ship_before_payment: bool
    portokosten_cents: int | None
    token: str
    lines: tuple[InvoiceLine, ...]
    debtor_id: int | None
    customer_id: int | None
    mollie_id: str | None = None

    @property
    def paid(self) -> bool:
        return self.open_cents <= 0

    @property
    def for_customer(self) -> bool:
        return self.customer_id is not None


@dataclass(frozen=True)
class Booking:
    transaction_id: int
    amount_cents: int
    description: str


@dataclass(frozen=True)
class Allocation:
    transaction_id: int
    invoice_number: str
    amount_cents: int


def seed_stock(conn, books: tuple[Book, ...]) -> None:
    for book in books:
        if book.voorraad is None:
            continue
        run(
            conn,
            """
            IF NOT EXISTS (SELECT 1 FROM dbo.stock WHERE slug = ?)
            INSERT INTO dbo.stock (slug, voorraad) VALUES (?, ?)
            """,
            (book.slug, book.slug, book.voorraad),
        )


def stock_map(conn) -> dict[str, int]:
    rows = query(conn, "SELECT slug, voorraad FROM dbo.stock")
    return {row["slug"]: int(row["voorraad"]) for row in rows}


def set_stock(conn, amounts: dict[str, int]) -> None:
    for slug, amount in amounts.items():
        if amount < 0:
            raise ValueError(f"voorraad voor {slug} moet een geheel getal van 0 of meer zijn.")
        run(
            conn,
            """
            MERGE dbo.stock AS target
            USING (SELECT ? AS slug, ? AS voorraad) AS source
            ON target.slug = source.slug
            WHEN MATCHED THEN UPDATE SET voorraad = source.voorraad
            WHEN NOT MATCHED THEN INSERT (slug, voorraad) VALUES (source.slug, source.voorraad);
            """,
            (slug, amount),
        )
    conn.commit()


def overlay_stock(conn, catalog: Catalog) -> Catalog:
    seed_stock(conn, catalog.books)
    conn.commit()
    amounts = stock_map(conn)
    books = []
    for book in catalog.books:
        if book.voorraad is None or book.slug not in amounts:
            books.append(book)
        else:
            books.append(replace(book, voorraad=amounts[book.slug]))
    return replace(catalog, books=tuple(books))


def _take_stock(conn, slug: str, copies: int) -> None:
    row = one(conn, "SELECT voorraad FROM dbo.stock WHERE slug = ?", (slug,))
    if row is None:
        return
    if int(row["voorraad"]) < copies:
        raise ValueError(f"Onvoldoende voorraad voor {slug}.")
    run(
        conn,
        """
        UPDATE dbo.stock
        SET voorraad = voorraad - ?
        WHERE slug = ? AND voorraad >= ?
        """,
        (copies, slug, copies),
    )


def _next_number(conn) -> str:
    row = one(conn, "SELECT TOP 1 number FROM dbo.invoices ORDER BY id DESC")
    current = 0
    if row is not None:
        match = re.search(r"(\d+)$", str(row["number"]))
        if match:
            current = int(match.group(1))
    return f"DB-{current + 1:05d}"


def save_shop_debtor(name: str, email: str, vat_number: str) -> str:
    """Store a new debtor and return the bestelcode. A code means ship before payment."""
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    conn = connect(autocommit=True)
    try:
        code = ""
        for _ in range(8):
            candidate = "".join(secrets.choice(alphabet) for _ in range(18))
            if one(conn, "SELECT 1 AS ok FROM dbo.debtors WHERE code = ?", (candidate,)) is None:
                code = candidate
                break
        if not code:
            raise RuntimeError("bestelcode kon niet worden gemaakt")
        run(
            conn,
            "INSERT INTO dbo.debtors (name, email, vat_number, code, address_id) VALUES (?, ?, ?, ?, NULL)",
            (name.strip(), email.strip(), vat_number.strip(), code),
        )
        return code
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError("debtors kon niet worden geschreven") from exc
    finally:
        conn.close()


def shop_debtor_by_code(code: str) -> dict | None:
    wanted = code.strip()
    if not wanted:
        return None
    conn = connect(autocommit=True)
    try:
        row = one(
            conn,
            """
            SELECT d.id, d.name, d.email, d.vat_number, d.code, d.address_id,
                   a.street, a.[number] AS house_number, a.postalcode, a.city
            FROM dbo.debtors d
            LEFT JOIN dbo.address a ON a.id = d.address_id
            WHERE d.code = ?
            """,
            (wanted,),
        )
    except Exception as exc:
        raise RuntimeError("debtors kon niet worden gelezen") from exc
    finally:
        conn.close()
    if row is None:
        return None
    stored = str(row["code"] or "").strip()
    if not stored:
        return None
    address = Address(
        street=str(row["street"] or ""),
        number=str(row["house_number"] or ""),
        postalcode=str(row["postalcode"] or ""),
        city=str(row["city"] or ""),
    )
    return {
        "id": int(row["id"]),
        "name": str(row["name"] or "").strip(),
        "email": str(row["email"] or "").strip(),
        "vat_number": str(row["vat_number"] or "").strip(),
        "code": stored,
        "address": address.formatted(),
        "address_id": row["address_id"],
    }


def create_account_order(
    *,
    code: str,
    lines: list[tuple[str, int, int]],
    books: tuple[Book, ...],
    vat_cents_amount: int,
) -> Order:
    """Write the order for a code-carrying debtor. The invoice comes later, from the
    administrator. lines are (slug, copies, price_cents_per_copy)."""
    debtor = shop_debtor_by_code(code)
    if debtor is None:
        raise ValueError("Deze code hoort niet bij een bedrijf.")
    email = str(debtor.get("email") or "").strip()
    vat_number = str(debtor.get("vat_number") or "").strip()
    if not email:
        raise ValueError("E-mail ontbreekt.")
    if not vat_number:
        raise ValueError("Een bestelling op rekening heeft een btw-nummer nodig.")
    if not lines:
        raise ValueError("De bestelling heeft geen regels.")
    payable = sum(copies * price for _slug, copies, price in lines)
    order_id = uuid.uuid4().hex
    conn = connect(autocommit=False)
    try:
        seed_stock(conn, books)
        run(
            conn,
            """
            INSERT INTO dbo.orders (
                id, token, email, status, amount_cents, vat_cents,
                created_at, debtor_id, invoice_number
            ) VALUES (?, ?, ?, 'open', ?, ?, ?, ?, NULL)
            """,
            (
                order_id,
                secrets.token_urlsafe(32),
                email,
                payable,
                vat_cents_amount,
                datetime.now().strftime("%Y-%m-%d %H:%M"),
                int(debtor["id"]),
            ),
        )
        for slug, copies, price in lines:
            run(
                conn,
                "INSERT INTO dbo.orderlines (order_id, slug, number_of_copies, price_cents_per_copy) VALUES (?, ?, ?, ?)",
                (order_id, slug, copies, price),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    fresh = connect(autocommit=True)
    try:
        order = one(fresh, "SELECT 1 AS ok FROM dbo.orders WHERE id = ?", (order_id,))
    finally:
        fresh.close()
    if order is None:
        raise RuntimeError("bestelling kon niet worden opgeslagen")
    conn = connect(autocommit=True)
    try:
        return get_order(conn, order_id)
    finally:
        conn.close()


def create_debtor_invoice(conn, order: Order) -> Invoice:
    """An administrator turns a shipped order into an invoice. The stock leaves here."""
    row = one(
        conn,
        "SELECT name, email, vat_number, code FROM dbo.debtors WHERE id = ?",
        (order.debtor_id,),
    )
    if row is None:
        raise ValueError("De bestelling hoort niet bij een bedrijf.")
    vat_number = str(row["vat_number"] or "").strip()
    if not vat_number:
        raise ValueError("Een bestelling op rekening heeft een btw-nummer nodig.")
    if not order.items:
        raise ValueError("De factuur heeft geen regels.")
    when = datetime.now()
    number = _next_number(conn)
    token = secrets.token_urlsafe(32)
    payable = order.amount_cents
    due_on = when.date() + timedelta(days=ACCOUNT_DUE_DAYS)
    ordered_at = when.strftime("%Y-%m-%d %H:%M")
    try:
        invoice_id = insert_id(
            conn,
            """
            INSERT INTO dbo.invoices (
                number, token, debtor_id, customer_id, mollie_id, mollie_settlement_id,
                ordered_at, due_on, payable_cents, open_cents, portokosten_cents
            )
            OUTPUT INSERTED.id
            VALUES (?, ?, ?, NULL, NULL, NULL, ?, ?, ?, ?, NULL)
            """,
            (number, token, order.debtor_id, ordered_at, due_on.isoformat(), payable, payable),
        )
        stored: list[InvoiceLine] = []
        for item in order.items:
            _take_stock(conn, item.slug, item.number_of_copies)
            run(
                conn,
                """
                INSERT INTO dbo.invoicelines (invoice_id, slug, number_of_copies, price_cents_per_copy)
                VALUES (?, ?, ?, ?)
                """,
                (invoice_id, item.slug, item.number_of_copies, item.price_cents_per_copy),
            )
            stored.append(InvoiceLine(item.slug, item.number_of_copies, item.price_cents_per_copy))
        mark_invoiced(conn, order.id, number)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return Invoice(
        number=number,
        name=str(row["name"] or ""),
        email=str(row["email"] or ""),
        address=order.address.formatted(),
        vat_number=vat_number,
        ordered_at=ordered_at,
        due_on=due_on,
        payable_cents=payable,
        open_cents=payable,
        ship_before_payment=True,
        portokosten_cents=None,
        token=token,
        lines=tuple(stored),
        debtor_id=order.debtor_id,
        customer_id=None,
    )


def create_customer_invoice(
    *,
    name: str,
    email: str,
    address: Address,
    lines: list[tuple[str, int, int]],
    vat_cents_amount: int,
) -> Invoice:
    """A Mollie buyer: one address, one customer, one open invoice. The payment page
    takes the stock once Mollie reports the payment."""
    if not lines:
        raise ValueError("De factuur heeft geen regels.")
    payable = sum(copies * price for _slug, copies, price in lines)
    when = datetime.now()
    conn = connect(autocommit=False)
    try:
        address_id = save_address(conn, address)
        customer_id = insert_id(
            conn,
            "INSERT INTO dbo.customers (name, email, address_id) OUTPUT INSERTED.id VALUES (?, ?, ?)",
            (name.strip(), email.strip(), address_id),
        )
        number = _next_number(conn)
        token = secrets.token_urlsafe(32)
        due_on = when.date() + timedelta(days=ACCOUNT_DUE_DAYS)
        ordered_at = when.strftime("%Y-%m-%d %H:%M")
        invoice_id = insert_id(
            conn,
            """
            INSERT INTO dbo.invoices (
                number, token, debtor_id, customer_id, mollie_id, mollie_settlement_id,
                ordered_at, due_on, payable_cents, open_cents, portokosten_cents
            )
            OUTPUT INSERTED.id
            VALUES (?, ?, NULL, ?, NULL, NULL, ?, ?, ?, ?, ?)
            """,
            (
                number,
                token,
                customer_id,
                ordered_at,
                due_on.isoformat(),
                payable,
                payable,
                vat_cents_amount,
            ),
        )
        stored: list[InvoiceLine] = []
        for slug, copies, price in lines:
            run(
                conn,
                "INSERT INTO dbo.invoicelines (invoice_id, slug, number_of_copies, price_cents_per_copy) VALUES (?, ?, ?, ?)",
                (invoice_id, slug, copies, price),
            )
            stored.append(InvoiceLine(slug, copies, price))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return Invoice(
        number=number,
        name=name.strip(),
        email=email.strip(),
        address=address.formatted(),
        vat_number="",
        ordered_at=ordered_at,
        due_on=due_on,
        payable_cents=payable,
        open_cents=payable,
        ship_before_payment=False,
        portokosten_cents=vat_cents_amount,
        token=token,
        lines=tuple(stored),
        debtor_id=None,
        customer_id=customer_id,
    )


def attach_mollie(conn, invoice_number: str, mollie_id: str) -> None:
    run(conn, "UPDATE dbo.invoices SET mollie_id = ? WHERE number = ?", (mollie_id, invoice_number))
    conn.commit()


def invoice_by_payment(conn, mollie_id: str) -> Invoice | None:
    row = one(conn, "SELECT number FROM dbo.invoices WHERE mollie_id = ?", (mollie_id,))
    if row is None:
        return None
    return get_invoice(row["number"])


def apply_payment(
    conn,
    invoice: Invoice,
    *,
    status: str,
    amount_cents: int,
    invoice_number_from_provider: str,
) -> str:
    """Record a payment status fetched from Mollie. A paid invoice is never reopened."""
    if invoice_number_from_provider != invoice.number:
        return "invoice-mismatch"
    if amount_cents != invoice.payable_cents:
        return "amount-mismatch"
    if invoice.paid:
        return "paid"
    if status == "paid":
        for line in invoice.lines:
            _take_stock(conn, line.slug, line.number_of_copies)
        run(conn, "UPDATE dbo.invoices SET open_cents = 0 WHERE number = ?", (invoice.number,))
        conn.commit()
        return "paid"
    if status in {"canceled", "expired", "failed"}:
        return status
    return "open"


def get_invoice(number: str) -> Invoice | None:
    conn = connect(autocommit=True)
    try:
        row = one(
            conn,
            """
            SELECT i.number, i.token, i.mollie_id, i.ordered_at, i.due_on, i.payable_cents, i.open_cents,
                   i.portokosten_cents, i.debtor_id, i.customer_id,
                   d.name AS debtor_name, d.email AS debtor_email, d.vat_number AS debtor_vat,
                   d.address_id AS debtor_address_id, d.code AS debtor_code,
                   c.name AS customer_name, c.email AS customer_email, c.address_id AS customer_address_id
            FROM dbo.invoices i
            LEFT JOIN dbo.debtors d ON d.id = i.debtor_id
            LEFT JOIN dbo.customers c ON c.id = i.customer_id
            WHERE i.number = ?
            """,
            (number,),
        )
        if row is None:
            return None
        lines = query(
            conn,
            """
            SELECT slug, number_of_copies, price_cents_per_copy
            FROM dbo.invoicelines
            WHERE invoice_id = (SELECT id FROM dbo.invoices WHERE number = ?)
            ORDER BY id
            """,
            (number,),
        )
        for_customer = row["customer_id"] is not None
        if for_customer:
            name = str(row["customer_name"] or "")
            email = str(row["customer_email"] or "")
            vat_number = ""
            address_id = row["customer_address_id"]
            ship_before_payment = False
        else:
            name = str(row["debtor_name"] or "")
            email = str(row["debtor_email"] or "")
            vat_number = str(row["debtor_vat"] or "")
            address_id = row["debtor_address_id"]
            ship_before_payment = True
        address_text = address_by_id(conn, address_id).formatted()
    finally:
        conn.close()
    return Invoice(
        number=row["number"],
        name=name,
        email=email,
        address=address_text,
        vat_number=vat_number,
        ordered_at=row["ordered_at"],
        due_on=date.fromisoformat(str(row["due_on"])),
        payable_cents=int(row["payable_cents"]),
        open_cents=int(row["open_cents"]),
        ship_before_payment=ship_before_payment,
        portokosten_cents=row["portokosten_cents"],
        token=str(row["token"] or ""),
        lines=tuple(
            InvoiceLine(
                slug=line["slug"],
                number_of_copies=int(line["number_of_copies"]),
                price_cents_per_copy=int(line["price_cents_per_copy"]),
            )
            for line in lines
        ),
        debtor_id=None if for_customer else int(row["debtor_id"]),
        customer_id=int(row["customer_id"]) if for_customer else None,
        mollie_id=row["mollie_id"],
    )


def invoice_by_token(number: str, token: str) -> Invoice | None:
    invoice = get_invoice(number)
    if invoice is None or not token or not secrets.compare_digest(invoice.token, token):
        return None
    return invoice


def open_invoices(conn) -> list[Invoice]:
    """Debtor invoices only: a Mollie customer pays before anything is shipped."""
    rows = query(
        conn,
        "SELECT number FROM dbo.invoices WHERE debtor_id IS NOT NULL AND open_cents > 0 ORDER BY id",
    )
    found = []
    for row in rows:
        invoice = get_invoice(row["number"])
        if invoice is not None:
            found.append(invoice)
    return found


def applied_transaction_ids(conn) -> set[int]:
    rows = query(conn, "SELECT DISTINCT transaction_id FROM dbo.payments")
    return {int(row["transaction_id"]) for row in rows}


def numbers_in_description(description: str, numbers: list[str]) -> list[str]:
    found = []
    for number in sorted(numbers, key=len, reverse=True):
        pattern = rf"(?<![A-Za-z0-9]){re.escape(number)}(?![A-Za-z0-9])"
        if re.search(pattern, description or ""):
            found.append(number)
    return found


def plan_allocations(
    invoices: list[Invoice],
    bookings: list[Booking],
    applied: set[int],
) -> list[Allocation]:
    by_number = {invoice.number: invoice for invoice in invoices if invoice.open_cents > 0}
    planned: list[Allocation] = []
    for booking in bookings:
        if booking.transaction_id in applied or booking.amount_cents <= 0:
            continue
        hits = numbers_in_description(booking.description, list(by_number))
        if len(hits) == 1:
            invoice = by_number[hits[0]]
            if booking.amount_cents > invoice.open_cents:
                continue
            planned.append(
                Allocation(booking.transaction_id, invoice.number, booking.amount_cents)
            )
            by_number[invoice.number] = replace(
                invoice, open_cents=invoice.open_cents - booking.amount_cents
            )
        elif len(hits) > 1:
            chosen = [by_number[number] for number in hits]
            total = sum(invoice.open_cents for invoice in chosen)
            if booking.amount_cents != total or any(invoice.open_cents <= 0 for invoice in chosen):
                continue
            for invoice in chosen:
                planned.append(
                    Allocation(booking.transaction_id, invoice.number, invoice.open_cents)
                )
                by_number[invoice.number] = replace(invoice, open_cents=0)
        applied.add(booking.transaction_id)
    return planned


def apply_allocations(conn, allocations: list[Allocation]) -> None:
    """Record a bank booking against an invoice. The stock already left at invoicing."""
    for allocation in allocations:
        run(
            conn,
            "INSERT INTO dbo.payments (transaction_id, invoice_number, amount_cents) VALUES (?, ?, ?)",
            (allocation.transaction_id, allocation.invoice_number, allocation.amount_cents),
        )
        row = one(conn, "SELECT open_cents FROM dbo.invoices WHERE number = ?", (allocation.invoice_number,))
        if row is None:
            continue
        remaining = int(row["open_cents"]) - allocation.amount_cents
        run(
            conn,
            "UPDATE dbo.invoices SET open_cents = ? WHERE number = ?",
            (remaining, allocation.invoice_number),
        )
    conn.commit()


def euros_to_cents(amount: Decimal) -> int:
    return int((amount * Decimal(100)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def read_incoming_bookings(iban: str) -> list[Booking]:
    """Read money-in bookings on the Boog account. No write."""
    cleaned = re.sub(r"\s+", "", iban).upper()
    if not cleaned:
        return []
    conn = connect_bookkeeping(autocommit=True)
    try:
        rows = query(
            conn,
            """
            SELECT t.transaction_id, t.amount, t.description
            FROM dbo.transaction_beheer_boog t
            INNER JOIN dbo.account a ON a.account_id = t.account_id
            WHERE REPLACE(UPPER(a.iban), ' ', '') = ?
              AND t.amount > 0
            """,
            (cleaned,),
        )
        return [
            Booking(
                transaction_id=int(row["transaction_id"]),
                amount_cents=euros_to_cents(Decimal(str(row["amount"]))),
                description=str(row["description"] or ""),
            )
            for row in rows
        ]
    finally:
        conn.close()


def sync_payments(conn, bookings: list[Booking]) -> list[Allocation]:
    planned = plan_allocations(open_invoices(conn), bookings, applied_transaction_ids(conn))
    apply_allocations(conn, planned)
    return planned


def sent_steps(conn) -> set[tuple[str, str]]:
    rows = query(conn, "SELECT invoice_number, step FROM dbo.reminders")
    return {(row["invoice_number"], row["step"]) for row in rows}


def steps_due(invoice: Invoice, today: date, sent: set[tuple[str, str]]) -> list[str]:
    if invoice.open_cents <= 0:
        return []
    due = []
    for name, offset in REMINDER_STEPS:
        if today == invoice.due_on + timedelta(days=offset) and (invoice.number, name) not in sent:
            due.append(name)
    return due


def reminder_body(invoice: Invoice, iban: str) -> str:
    from app.catalog import euro

    return (
        f"Factuur {invoice.number}\n"
        f"Openstaand bedrag: {euro(invoice.open_cents)}\n"
        f"IBAN: {iban}\n"
        f"Zet {invoice.number} in de omschrijving van de betaling.\n"
    )


def record_reminder(conn, invoice: Invoice, step: str, when: datetime) -> None:
    run(
        conn,
        "INSERT INTO dbo.reminders (invoice_number, email, step, sent_at) VALUES (?, ?, ?, ?)",
        (invoice.number, invoice.email, step, when.strftime("%Y-%m-%d %H:%M")),
    )
    conn.commit()

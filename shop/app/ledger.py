"""Buyer subledger in the webshop database.

beheer_boog stays the general ledger in agrolav. This module reads bookings from
there and does not write a booking, a category, or a modification. Every row it
writes here belongs to one of two buyers:

  a debtor   -- an account company; its order becomes a draft invoice
                (status 'prepared') the moment it is placed, so its invoices
                can stay open.
  a customer -- a Mollie buyer; invoiced (status 'customer') and paid at
                checkout.
"""
from __future__ import annotations

import re
import secrets
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
    status: str = "prepared"
    sent_at: str | None = None
    paid_at: str | None = None

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
    booked_on: str = ""
    name: str = ""
    iban: str = ""


@dataclass(frozen=True)
class Allocation:
    transaction_id: int
    invoice_number: str
    amount_cents: int
    paid_at: str | None = None


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


def invoice_number(invoice_id: int) -> str:
    """The invoice's public number, derived from its id: BDF-{id}."""
    return f"BDF-{int(invoice_id)}"


def _invoice_id(number: str) -> int | None:
    match = re.fullmatch(r"BDF-(\d+)", str(number or "").strip())
    return int(match.group(1)) if match else None


def save_shop_debtor(name: str, email: str, vat_number: str, address: Address | None = None) -> str:
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
        address_id = save_address(conn, address) if address is not None else None
        run(
            conn,
            "INSERT INTO dbo.debtors (name, email, vat_number, code, address_id) VALUES (?, ?, ?, ?, ?)",
            (name.strip(), email.strip(), vat_number.strip(), code, address_id),
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
    """Write the order and its invoice in one transaction.

    The order becomes a draft invoice (status 'prepared') the moment it is
    placed; the stock leaves here, so an order that exceeds the stock is
    refused before anything is written. lines are (slug, copies,
    price_cents_per_copy); the invoice mirrors them exactly, and the
    administrator edits the invoice, not the order, afterwards.
    """
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
    token = secrets.token_hex(16)
    when = datetime.now()
    due_on = when.date() + timedelta(days=ACCOUNT_DUE_DAYS)
    ordered_at = when.strftime("%Y-%m-%d %H:%M")
    conn = connect(autocommit=False)
    try:
        seed_stock(conn, books)
        for slug, copies, _price in lines:
            _take_stock(conn, slug, copies)
        invoice_id = insert_id(
            conn,
            """
            INSERT INTO dbo.invoices (
                token, debtor_id, customer_id, mollie_id, mollie_settlement_id,
                ordered_at, due_on, payable_cents, open_cents, portokosten_cents, status
            )
            OUTPUT INSERTED.id
            VALUES (?, ?, NULL, NULL, NULL, ?, ?, ?, ?, NULL, 'prepared')
            """,
            (
                secrets.token_urlsafe(32),
                int(debtor["id"]),
                ordered_at,
                due_on.isoformat(),
                payable,
                payable,
            ),
        )
        for slug, copies, price in lines:
            run(
                conn,
                """
                INSERT INTO dbo.invoicelines (invoice_id, slug, number_of_copies, price_cents_per_copy)
                VALUES (?, ?, ?, ?)
                """,
                (invoice_id, slug, copies, price),
            )
        run(
            conn,
            """
            INSERT INTO dbo.orders (
                invoice_id, token, email, status, amount_cents, vat_cents,
                created_at, debtor_id
            )
            VALUES (?, ?, ?, 'invoiced', ?, ?, ?, ?)
            """,
            (
                invoice_id,
                token,
                email,
                payable,
                vat_cents_amount,
                ordered_at,
                int(debtor["id"]),
            ),
        )
        for slug, copies, price in lines:
            run(
                conn,
                "INSERT INTO dbo.orderlines (order_id, slug, number_of_copies, price_cents_per_copy) VALUES (?, ?, ?, ?)",
                (invoice_id, slug, copies, price),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    conn = connect(autocommit=True)
    try:
        order = get_order(conn, invoice_id)
    finally:
        conn.close()
    if order is None:
        raise RuntimeError("bestelling kon niet worden opgeslagen")
    return order


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
        token = secrets.token_urlsafe(32)
        due_on = when.date() + timedelta(days=ACCOUNT_DUE_DAYS)
        ordered_at = when.strftime("%Y-%m-%d %H:%M")
        invoice_id = insert_id(
            conn,
            """
            INSERT INTO dbo.invoices (
                token, debtor_id, customer_id, mollie_id, mollie_settlement_id,
                ordered_at, due_on, payable_cents, open_cents, portokosten_cents, status
            )
            OUTPUT INSERTED.id
            VALUES (?, NULL, ?, NULL, NULL, ?, ?, ?, ?, ?, 'customer')
            """,
            (
                token,
                customer_id,
                ordered_at,
                due_on.isoformat(),
                payable,
                payable,
                vat_cents_amount,
            ),
        )
        number = invoice_number(invoice_id)
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
        status="customer",
    )


def party_choices(conn) -> list[tuple[str, str]]:
    """Who an ad-hoc invoice can be written to: (value, label) per debtor and
    customer, the label carrying the name plus IBAN when there is one."""
    rows = query(
        conn,
        """
        SELECT 'debtor' AS kind, id, name, iban FROM dbo.debtors
        UNION ALL
        SELECT 'customer' AS kind, id, name, iban FROM dbo.customers
        ORDER BY name, kind
        """,
    )
    choices: list[tuple[str, str]] = []
    for row in rows:
        name = str(row["name"] or "").strip() or "(zonder naam)"
        iban = str(row["iban"] or "").strip()
        label = f"{name} — {iban}" if iban else name
        choices.append((f'{row["kind"]}:{int(row["id"])}', label))
    return choices


def create_adhoc_invoice(
    *,
    owner: str,
    lines: list[tuple[str, int, int]],
    books: tuple[Book, ...] = (),
    vat_cents_amount: int | None = None,
) -> Invoice:
    """An ad-hoc invoice from the administrator's 'Voeg factuur toe' form.

    owner is 'debtor:12' or 'customer:7'. A debtor invoice starts as a draft
    (status 'prepared'); a customer invoice is a customer invoice ('customer')
    right away. lines are (slug, copies, price_cents_per_copy) and the stock
    leaves here.
    """
    kind, sep, raw_id = str(owner or "").strip().partition(":")
    if not sep or kind not in {"debtor", "customer"}:
        raise ValueError("Kies een bedrijf of klant.")
    try:
        owner_id = int(raw_id.strip())
    except ValueError:
        raise ValueError("Kies een bedrijf of klant.")
    wanted = [(slug.strip(), copies, price) for slug, copies, price in lines if copies != 0]
    if not wanted:
        raise ValueError("De factuur heeft geen regels.")
    for slug, _copies, _price in wanted:
        if not slug:
            raise ValueError("Elke regel heeft een slug nodig.")
    token = secrets.token_urlsafe(32)
    when = datetime.now()
    due_on = when.date() + timedelta(days=ACCOUNT_DUE_DAYS)
    ordered_at = when.strftime("%Y-%m-%d %H:%M")
    conn = connect(autocommit=False)
    try:
        seed_stock(conn, books)
        if kind == "debtor":
            row = one(
                conn,
                "SELECT name, email, vat_number, address_id FROM dbo.debtors WHERE id = ?",
                (owner_id,),
            )
            if row is None:
                raise ValueError("Onbekend bedrijf.")
            if not str(row["vat_number"] or "").strip():
                raise ValueError("Een factuur op rekening heeft een btw-nummer nodig.")
            debtor_id, customer_id = owner_id, None
            vat_number = str(row["vat_number"] or "")
            status, portokosten = "prepared", None
        else:
            row = one(
                conn,
                "SELECT name, email, address_id FROM dbo.customers WHERE id = ?",
                (owner_id,),
            )
            if row is None:
                raise ValueError("Onbekende klant.")
            debtor_id, customer_id = None, owner_id
            vat_number = ""
            status, portokosten = "customer", vat_cents_amount
        name = str(row["name"] or "")
        email = str(row["email"] or "")
        address = address_by_id(conn, row["address_id"]).formatted()
        payable = sum(copies * price for _slug, copies, price in wanted)
        invoice_id = insert_id(
            conn,
            """
            INSERT INTO dbo.invoices (
                token, debtor_id, customer_id, mollie_id, mollie_settlement_id,
                ordered_at, due_on, payable_cents, open_cents, portokosten_cents, status
            )
            OUTPUT INSERTED.id
            VALUES (?, ?, ?, NULL, NULL, ?, ?, ?, ?, ?, ?)
            """,
            (
                token,
                debtor_id,
                customer_id,
                ordered_at,
                due_on.isoformat(),
                payable,
                payable,
                portokosten,
                status,
            ),
        )
        stored: list[InvoiceLine] = []
        for slug, copies, price in wanted:
            _take_stock(conn, slug, copies)
            run(
                conn,
                """
                INSERT INTO dbo.invoicelines (invoice_id, slug, number_of_copies, price_cents_per_copy)
                VALUES (?, ?, ?, ?)
                """,
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
        number=invoice_number(invoice_id),
        name=name,
        email=email,
        address=address,
        vat_number=vat_number,
        ordered_at=ordered_at,
        due_on=due_on,
        payable_cents=payable,
        open_cents=payable,
        ship_before_payment=kind == "debtor",
        portokosten_cents=portokosten,
        token=token,
        lines=tuple(stored),
        debtor_id=debtor_id,
        customer_id=customer_id,
        status=status,
    )


def attach_mollie(conn, number: str, mollie_id: str) -> None:
    invoice_id = _invoice_id(number)
    if invoice_id is None:
        return
    run(conn, "UPDATE dbo.invoices SET mollie_id = ? WHERE id = ?", (mollie_id, invoice_id))
    conn.commit()


def invoice_by_payment(conn, mollie_id: str) -> Invoice | None:
    row = one(conn, "SELECT id FROM dbo.invoices WHERE mollie_id = ?", (mollie_id,))
    if row is None:
        return None
    return get_invoice(invoice_number(int(row["id"])))


def apply_payment(
    conn,
    invoice: Invoice,
    *,
    status: str,
    amount_cents: int,
    paid_at: str | None = None,
) -> str:
    """Record a payment status fetched from Mollie. A paid invoice is never reopened."""
    if amount_cents != invoice.payable_cents:
        return "amount-mismatch"
    if invoice.paid:
        return "paid"
    if status == "paid":
        invoice_id = _invoice_id(invoice.number)
        for line in invoice.lines:
            _take_stock(conn, line.slug, line.number_of_copies)
        paid_on = paid_at or datetime.now().strftime("%Y-%m-%d %H:%M")
        run(
            conn,
            "UPDATE dbo.invoices SET open_cents = 0, paid_at = ? WHERE id = ?",
            (paid_on, invoice_id),
        )
        conn.commit()
        return "paid"
    if status in {"canceled", "expired", "failed"}:
        return status
    return "open"


def get_invoice(number: str) -> Invoice | None:
    invoice_id = _invoice_id(number)
    if invoice_id is None:
        return None
    conn = connect(autocommit=True)
    try:
        row = one(
            conn,
            """
            SELECT i.id, i.token, i.mollie_id, i.ordered_at, i.due_on, i.payable_cents, i.open_cents,
                   i.portokosten_cents, i.debtor_id, i.customer_id, i.status, i.sent_at, i.paid_at,
                   d.name AS debtor_name, d.email AS debtor_email, d.vat_number AS debtor_vat,
                   d.address_id AS debtor_address_id, d.code AS debtor_code,
                   c.name AS customer_name, c.email AS customer_email, c.address_id AS customer_address_id
            FROM dbo.invoices i
            LEFT JOIN dbo.debtors d ON d.id = i.debtor_id
            LEFT JOIN dbo.customers c ON c.id = i.customer_id
            WHERE i.id = ?
            """,
            (invoice_id,),
        )
        if row is None:
            return None
        lines = query(
            conn,
            """
            SELECT slug, number_of_copies, price_cents_per_copy
            FROM dbo.invoicelines
            WHERE invoice_id = ?
            ORDER BY id
            """,
            (invoice_id,),
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
        number=invoice_number(int(row["id"])),
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
        status=str(row["status"] or "prepared"),
        sent_at=None if row["sent_at"] is None else str(row["sent_at"]),
        paid_at=None if row["paid_at"] is None else str(row["paid_at"]),
    )


def mark_invoice_sent(conn, number: str) -> bool:
    """Record a successful send, transitioning debtor drafts to sent."""
    invoice_id = _invoice_id(number)
    if invoice_id is None:
        return False
    sent_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    changed = query(
        conn,
        """
        UPDATE dbo.invoices
        SET status = CASE WHEN status = 'prepared' THEN 'sent' ELSE status END,
            sent_at = ?
        OUTPUT INSERTED.id
        WHERE id = ?
          AND (status = 'prepared' OR (status = 'customer' AND sent_at IS NULL))
        """,
        (sent_at, invoice_id),
    )
    if not changed:
        conn.rollback()
        return False
    conn.commit()
    return True


def invoice_by_token(number: str, token: str) -> Invoice | None:
    invoice = get_invoice(number)
    if invoice is None or not token or not secrets.compare_digest(invoice.token, token):
        return None
    return invoice


def open_invoices(conn) -> list[Invoice]:
    """Debtor invoices only: a Mollie customer pays before anything is shipped."""
    rows = query(
        conn,
        "SELECT id FROM dbo.invoices WHERE debtor_id IS NOT NULL AND open_cents > 0 ORDER BY id",
    )
    found = []
    for row in rows:
        invoice = get_invoice(invoice_number(int(row["id"])))
        if invoice is not None:
            found.append(invoice)
    return found


def unpaid_invoices(conn) -> list[Invoice]:
    """Sent debtor/account invoices with a remaining balance."""
    rows = query(
        conn,
        """
        SELECT id FROM dbo.invoices
        WHERE debtor_id IS NOT NULL AND sent_at IS NOT NULL AND open_cents > 0
        ORDER BY id
        """,
    )
    found = []
    for row in rows:
        invoice = get_invoice(invoice_number(int(row["id"])))
        if invoice is not None:
            found.append(invoice)
    return found


def paid_invoices(conn) -> list[Invoice]:
    """Sent debtor/account invoices with no remaining balance."""
    rows = query(
        conn,
        """
        SELECT id FROM dbo.invoices
        WHERE debtor_id IS NOT NULL AND sent_at IS NOT NULL AND open_cents <= 0
        ORDER BY id
        """,
    )
    found = []
    for row in rows:
        invoice = get_invoice(invoice_number(int(row["id"])))
        if invoice is not None:
            found.append(invoice)
    return found


def mollie_invoices(conn) -> list[Invoice]:
    """Invoices linked to Mollie checkout payments, whether paid or pending."""
    rows = query(
        conn,
        """
        SELECT id FROM dbo.invoices
        WHERE customer_id IS NOT NULL AND mollie_id IS NOT NULL
        ORDER BY id
        """,
    )
    found = []
    for row in rows:
        invoice = get_invoice(invoice_number(int(row["id"])))
        if invoice is not None:
            found.append(invoice)
    return found


def latest_reminder_dates(conn) -> dict[str, str]:
    rows = query(
        conn,
        "SELECT invoice_number, MAX(sent_at) AS sent_at FROM dbo.reminders GROUP BY invoice_number",
    )
    return {
        str(row["invoice_number"]): str(row["sent_at"])
        for row in rows
        if row["sent_at"] is not None
    }


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
                Allocation(
                    booking.transaction_id,
                    invoice.number,
                    booking.amount_cents,
                    booking.booked_on or None,
                )
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
                    Allocation(
                        booking.transaction_id,
                        invoice.number,
                        invoice.open_cents,
                        booking.booked_on or None,
                    )
                )
                by_number[invoice.number] = replace(invoice, open_cents=0)
        applied.add(booking.transaction_id)
    return planned


def compact_iban(value: object) -> str:
    return "".join(str(value or "").split()).upper()


def known_party_ibans(conn) -> set[str]:
    """Every IBAN a debtor or customer can be paid from."""
    rows = query(
        conn,
        """
        SELECT iban FROM dbo.debtors WHERE iban IS NOT NULL AND LTRIM(RTRIM(iban)) <> N''
        UNION
        SELECT iban FROM dbo.customers WHERE iban IS NOT NULL AND LTRIM(RTRIM(iban)) <> N''
        """,
    )
    return {compact_iban(row["iban"]) for row in rows if row["iban"]}


def register_bank_bookings(conn, statements) -> set[int]:
    """Persist downloaded statements once, marking known-party IBANs registered."""
    known = known_party_ibans(conn)
    recognized: set[int] = set()
    for statement in statements:
        booking_id = int(statement.key)
        iban = compact_iban(statement.iban)
        is_known = bool(iban and iban in known)
        if is_known:
            recognized.add(booking_id)
        previous = one(conn, "SELECT status FROM dbo.bookings WHERE id = ?", (booking_id,))
        if previous is None:
            run(
                conn,
                """
                INSERT INTO dbo.bookings (
                    id, booked_on, name, iban, description, amount_cents, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    booking_id,
                    str(statement.booked_on or "") or None,
                    str(statement.name or ""),
                    iban,
                    str(statement.description or ""),
                    int(statement.amount_cents),
                    "registered" if is_known else "unregistered",
                ),
            )
            continue

        old_status = str(previous["status"] or "unregistered")
        if old_status in {"registered", "unregistered"}:
            new_status = "registered" if is_known or old_status == "registered" else "unregistered"
        else:
            new_status = old_status
        run(
            conn,
            """
            UPDATE dbo.bookings
            SET booked_on = ?, name = ?, iban = ?, description = ?, amount_cents = ?, status = ?
            WHERE id = ?
            """,
            (
                str(statement.booked_on or "") or None,
                str(statement.name or ""),
                iban,
                str(statement.description or ""),
                int(statement.amount_cents),
                new_status,
                booking_id,
            ),
        )
    conn.commit()
    return recognized


def registered_bank_bookings(conn) -> list[Booking]:
    rows = query(
        conn,
        """
        SELECT id, amount_cents, description, booked_on, name, iban
        FROM dbo.bookings
        WHERE status = N'registered'
        ORDER BY created_at, id
        """,
    )
    return [
        Booking(
            transaction_id=int(row["id"]),
            amount_cents=int(row["amount_cents"]),
            description=str(row["description"] or ""),
            booked_on="" if row["booked_on"] is None else str(row["booked_on"]),
            name=str(row["name"] or ""),
            iban=compact_iban(row["iban"]),
        )
        for row in rows
    ]


def bookings_for_year(conn, year: int) -> list[dict]:
    """All persisted statement bookings with a bank booking date in the year."""
    start = f"{int(year):04d}-01-01"
    end = f"{int(year) + 1:04d}-01-01"
    return query(
        conn,
        """
        SELECT id, created_at, booked_on, name, iban, description, amount_cents, status
        FROM dbo.bookings
        WHERE booked_on >= ? AND booked_on < ?
        ORDER BY booked_on, created_at, id
        """,
        (start, end),
    )


def latest_booking_created_at(conn) -> date | None:
    row = one(conn, "SELECT MAX(created_at) AS latest_created_at FROM dbo.bookings")
    if row is None or row["latest_created_at"] is None:
        return None
    value = row["latest_created_at"]
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def open_invoice_candidates(conn) -> list[dict]:
    """Open Mollie and sent account invoices eligible for exact bank matching."""
    rows = query(
        conn,
        """
        SELECT i.id, i.debtor_id, i.open_cents,
               d.iban AS debtor_iban, c.iban AS customer_iban
        FROM dbo.invoices i
        LEFT JOIN dbo.debtors d ON d.id = i.debtor_id
        LEFT JOIN dbo.customers c ON c.id = i.customer_id
        WHERE i.open_cents > 0
          AND (
              (i.debtor_id IS NOT NULL AND i.sent_at IS NOT NULL)
              OR (i.customer_id IS NOT NULL AND i.mollie_id IS NOT NULL)
          )
        ORDER BY i.id
        """,
    )
    out: list[dict] = []
    for row in rows:
        if row["debtor_id"] is not None:
            iban = row["debtor_iban"]
        else:
            iban = row["customer_iban"]
        if not compact_iban(iban):
            continue
        out.append(
            {
                "invoice_id": int(row["id"]),
                "iban": compact_iban(iban),
                "invoice_number": invoice_number(int(row["id"])),
                "open_cents": int(row["open_cents"]),
            }
        )
    return out


def match_registered_bank_bookings(
    bookings: list[Booking], candidates: list[dict]
) -> list[Allocation]:
    """Match a registered booking by exact counterparty IBAN and open amount."""
    by_iban: dict[str, list[dict]] = {}
    for candidate in candidates:
        by_iban.setdefault(compact_iban(candidate["iban"]), []).append(candidate)

    planned: list[Allocation] = []
    taken: set[str] = set()
    for booking in bookings:
        bucket = by_iban.get(compact_iban(booking.iban), [])
        matches = [
            candidate
            for candidate in bucket
            if candidate["invoice_number"] not in taken
            and int(candidate["open_cents"]) == booking.amount_cents
        ]
        if len(matches) != 1:
            continue
        invoice = matches[0]
        taken.add(invoice["invoice_number"])
        planned.append(
            Allocation(
                booking.transaction_id,
                invoice["invoice_number"],
                booking.amount_cents,
                booking.booked_on or None,
            )
        )
    return planned


def set_invoice_lines(conn, number: str, lines: list[InvoiceLine]) -> Invoice:
    """Replace invoice lines and recompute payable/open cents."""
    invoice_id = _invoice_id(number)
    if invoice_id is None:
        raise ValueError("Onbekende factuur.")
    row = one(
        conn,
        "SELECT payable_cents, open_cents, debtor_id, customer_id, token, ordered_at, due_on, portokosten_cents FROM dbo.invoices WHERE id = ?",
        (invoice_id,),
    )
    if row is None:
        raise ValueError("Onbekende factuur.")
    payable_old = int(row["payable_cents"])
    open_old = int(row["open_cents"])
    payable_new = 0
    for line in lines:
        if line.number_of_copies == 0:
            continue
        payable_new += line.number_of_copies * line.price_cents_per_copy
    paid = payable_old - open_old
    open_new = payable_new - paid
    try:
        run(conn, "DELETE FROM dbo.invoicelines WHERE invoice_id = ?", (invoice_id,))
        for line in lines:
            run(
                conn,
                "INSERT INTO dbo.invoicelines (invoice_id, slug, number_of_copies, price_cents_per_copy) VALUES (?, ?, ?, ?)",
                (invoice_id, line.slug, line.number_of_copies, line.price_cents_per_copy),
            )
        run(
            conn,
            "UPDATE dbo.invoices SET payable_cents = ?, open_cents = ? WHERE id = ?",
            (payable_new, open_new, invoice_id),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    result = get_invoice(number)
    if result is None:
        raise RuntimeError("factuur kon niet worden bijgewerkt")
    return result


def apply_allocations(
    conn,
    allocations: list[Allocation],
    *,
    mark_bookings: bool = False,
) -> None:
    """Record a bank booking against an invoice. The stock already left at invoicing.

    A debtor invoice settled in full turns 'paid'; a customer invoice keeps its
    own status, its paid state is the open_cents that drop to zero."""
    for allocation in allocations:
        run(
            conn,
            "INSERT INTO dbo.payments (transaction_id, invoice_number, amount_cents) VALUES (?, ?, ?)",
            (allocation.transaction_id, allocation.invoice_number, allocation.amount_cents),
        )
        invoice_id = _invoice_id(allocation.invoice_number)
        row = one(
            conn,
            "SELECT open_cents, customer_id, status FROM dbo.invoices WHERE id = ?",
            (invoice_id,),
        )
        if row is None:
            continue
        remaining = int(row["open_cents"]) - allocation.amount_cents
        if remaining <= 0 and row["customer_id"] is None:
            paid_on = allocation.paid_at or datetime.now().strftime("%Y-%m-%d %H:%M")
            if row["status"] == "sent":
                run(
                    conn,
                    "UPDATE dbo.invoices SET open_cents = ?, status = 'paid', paid_at = ? WHERE id = ?",
                    (remaining, paid_on, invoice_id),
                )
            else:
                run(
                    conn,
                    "UPDATE dbo.invoices SET open_cents = ?, paid_at = ? WHERE id = ?",
                    (remaining, paid_on, invoice_id),
                )
        elif remaining <= 0 and row["customer_id"] is not None:
            paid_on = allocation.paid_at or datetime.now().strftime("%Y-%m-%d %H:%M")
            run(
                conn,
                "UPDATE dbo.invoices SET open_cents = ?, paid_at = ? WHERE id = ?",
                (remaining, paid_on, invoice_id),
            )
        else:
            run(
                conn,
                "UPDATE dbo.invoices SET open_cents = ? WHERE id = ?",
                (remaining, invoice_id),
            )
        if mark_bookings:
            run(
                conn,
                "UPDATE dbo.bookings SET status = ? WHERE id = ? AND status = N'registered'",
                (str(invoice_id), allocation.transaction_id),
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
            SELECT t.transaction_id, t.amount, t.description, t.booked_on
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
                booked_on="" if row["booked_on"] is None else str(row["booked_on"])[:10],
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
    if invoice.status != "sent" or invoice.open_cents <= 0:
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

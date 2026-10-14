"""Debtor subledger in the shop SQLite file.

beheer_boog stays the general ledger. This module reads bookings and does
not write a booking, a category, or a modification.
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP

from app.catalog import Book, Catalog

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
    debtor_name: str
    email: str
    vat_number: str
    address: str
    ordered_at: str
    due_on: date
    payable_cents: int
    open_cents: int
    ship_before_payment: bool
    portokosten_cents: int | None
    lines: tuple[InvoiceLine, ...]


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


def seed_stock(conn: sqlite3.Connection, books: tuple[Book, ...]) -> None:
    for book in books:
        if book.voorraad is None:
            continue
        conn.execute(
            "INSERT OR IGNORE INTO stock (slug, voorraad) VALUES (?, ?)",
            (book.slug, book.voorraad),
        )
    conn.commit()


def stock_map(conn: sqlite3.Connection) -> dict[str, int]:
    rows = conn.execute("SELECT slug, voorraad FROM stock").fetchall()
    return {row["slug"]: int(row["voorraad"]) for row in rows}


def set_stock(conn: sqlite3.Connection, amounts: dict[str, int]) -> None:
    for slug, amount in amounts.items():
        if amount < 0:
            raise ValueError(f"voorraad voor {slug} moet een geheel getal van 0 of meer zijn.")
        conn.execute(
            """
            INSERT INTO stock (slug, voorraad) VALUES (?, ?)
            ON CONFLICT(slug) DO UPDATE SET voorraad = excluded.voorraad
            """,
            (slug, amount),
        )
    conn.commit()


def overlay_stock(conn: sqlite3.Connection, catalog: Catalog) -> Catalog:
    seed_stock(conn, catalog.books)
    amounts = stock_map(conn)
    books = []
    for book in catalog.books:
        if book.voorraad is None or book.slug not in amounts:
            books.append(book)
        else:
            books.append(replace(book, voorraad=amounts[book.slug]))
    return replace(catalog, books=tuple(books))


def set_book_costs(
    conn: sqlite3.Connection,
    slug: str,
    *,
    drukkosten_cents: int | None = None,
    vrijwilligersbijdrage_cents: int | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO book_costs (slug, drukkosten_cents, vrijwilligersbijdrage_cents)
        VALUES (?, ?, ?)
        ON CONFLICT(slug) DO UPDATE SET
            drukkosten_cents = excluded.drukkosten_cents,
            vrijwilligersbijdrage_cents = excluded.vrijwilligersbijdrage_cents
        """,
        (slug, drukkosten_cents, vrijwilligersbijdrage_cents),
    )
    conn.commit()


def _take_stock(conn: sqlite3.Connection, slug: str, copies: int) -> None:
    row = conn.execute("SELECT voorraad FROM stock WHERE slug = ?", (slug,)).fetchone()
    if row is None:
        return
    if int(row["voorraad"]) < copies:
        raise ValueError(f"Onvoldoende voorraad voor {slug}.")
    conn.execute(
        "UPDATE stock SET voorraad = voorraad - ? WHERE slug = ? AND voorraad >= ?",
        (copies, slug, copies),
    )


def create_invoice(
    conn: sqlite3.Connection,
    *,
    name: str,
    email: str,
    address: str,
    vat_number: str,
    ship_before_payment: bool,
    lines: list[tuple[str, int, int]],
    when: datetime,
    books: tuple[Book, ...],
) -> Invoice:
    """lines are (slug, copies, price_cents_per_copy). The price is the amount charged."""
    if not email.strip():
        raise ValueError("E-mail ontbreekt.")
    if ship_before_payment and not vat_number.strip():
        raise ValueError("Een bestelling op rekening heeft een btw-nummer nodig.")
    if not lines:
        raise ValueError("De factuur heeft geen regels.")
    seed_stock(conn, books)
    payable = sum(copies * price for _slug, copies, price in lines)
    try:
        return _insert_invoice(
            conn,
            name=name,
            email=email,
            address=address,
            vat_number=vat_number,
            ship_before_payment=ship_before_payment,
            lines=lines,
            when=when,
            payable=payable,
        )
    except Exception:
        conn.rollback()
        raise


def _insert_invoice(
    conn: sqlite3.Connection,
    *,
    name: str,
    email: str,
    address: str,
    vat_number: str,
    ship_before_payment: bool,
    lines: list[tuple[str, int, int]],
    when: datetime,
    payable: int,
) -> Invoice:
    due_on = when.date() + timedelta(days=ACCOUNT_DUE_DAYS)
    ordered_at = when.strftime("%Y-%m-%d %H:%M")
    number = _next_number(conn)
    cursor = conn.execute(
        """
        INSERT INTO debtors (name, email, address, vat_number, ship_before_payment)
        VALUES (?, ?, ?, ?, ?)
        """,
        (name.strip(), email.strip(), address.strip(), vat_number.strip(), int(ship_before_payment)),
    )
    debtor_id = cursor.lastrowid
    cursor = conn.execute(
        """
        INSERT INTO invoices (
            number, debtor_id, ordered_at, due_on, payable_cents, open_cents, portokosten_cents
        ) VALUES (?, ?, ?, ?, ?, ?, NULL)
        """,
        (number, debtor_id, ordered_at, due_on.isoformat(), payable, payable),
    )
    invoice_id = cursor.lastrowid
    stored: list[InvoiceLine] = []
    for slug, copies, price in lines:
        if ship_before_payment:
            _take_stock(conn, slug, copies)
        conn.execute(
            """
            INSERT INTO invoice_lines (
                invoice_id, slug, number_of_copies, price_cents_per_copy
            ) VALUES (?, ?, ?, ?)
            """,
            (invoice_id, slug, copies, price),
        )
        stored.append(InvoiceLine(slug, copies, price))
    conn.commit()
    return Invoice(
        number=number,
        debtor_name=name.strip(),
        email=email.strip(),
        vat_number=vat_number.strip(),
        address=address.strip(),
        ordered_at=ordered_at,
        due_on=due_on,
        payable_cents=payable,
        open_cents=payable,
        ship_before_payment=ship_before_payment,
        portokosten_cents=None,
        lines=tuple(stored),
    )


def _next_number(conn: sqlite3.Connection) -> str:
    row = conn.execute("SELECT number FROM invoices ORDER BY id DESC LIMIT 1").fetchone()
    current = 0
    if row is not None:
        match = re.search(r"(\d+)$", str(row["number"]))
        if match:
            current = int(match.group(1))
    return f"DB-{current + 1:05d}"


def get_invoice(conn: sqlite3.Connection, number: str) -> Invoice | None:
    row = conn.execute(
        """
        SELECT i.number, i.ordered_at, i.due_on, i.payable_cents, i.open_cents, i.portokosten_cents,
               d.name, d.email, d.address, d.vat_number, d.ship_before_payment
        FROM invoices i
        JOIN debtors d ON d.id = i.debtor_id
        WHERE i.number = ?
        """,
        (number,),
    ).fetchone()
    if row is None:
        return None
    lines = conn.execute(
        """
        SELECT slug, number_of_copies, price_cents_per_copy
        FROM invoice_lines
        WHERE invoice_id = (SELECT id FROM invoices WHERE number = ?)
        ORDER BY id
        """,
        (number,),
    ).fetchall()
    return Invoice(
        number=row["number"],
        debtor_name=row["name"],
        email=row["email"],
        vat_number=row["vat_number"],
        address=row["address"],
        ordered_at=row["ordered_at"],
        due_on=date.fromisoformat(row["due_on"]),
        payable_cents=int(row["payable_cents"]),
        open_cents=int(row["open_cents"]),
        ship_before_payment=bool(row["ship_before_payment"]),
        portokosten_cents=row["portokosten_cents"],
        lines=tuple(
            InvoiceLine(
                slug=line["slug"],
                number_of_copies=int(line["number_of_copies"]),
                price_cents_per_copy=int(line["price_cents_per_copy"]),
            )
            for line in lines
        ),
    )


def open_invoices(conn: sqlite3.Connection) -> list[Invoice]:
    rows = conn.execute(
        "SELECT number FROM invoices WHERE open_cents > 0 ORDER BY id"
    ).fetchall()
    found = []
    for row in rows:
        invoice = get_invoice(conn, row["number"])
        if invoice is not None:
            found.append(invoice)
    return found


def applied_transaction_ids(conn: sqlite3.Connection) -> set[int]:
    rows = conn.execute("SELECT DISTINCT transaction_id FROM invoice_payments").fetchall()
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


def apply_allocations(conn: sqlite3.Connection, allocations: list[Allocation]) -> None:
    for allocation in allocations:
        conn.execute(
            """
            INSERT INTO invoice_payments (transaction_id, invoice_number, amount_cents)
            VALUES (?, ?, ?)
            """,
            (allocation.transaction_id, allocation.invoice_number, allocation.amount_cents),
        )
        row = conn.execute(
            "SELECT open_cents, debtor_id FROM invoices WHERE number = ?",
            (allocation.invoice_number,),
        ).fetchone()
        if row is None:
            continue
        remaining = int(row["open_cents"]) - allocation.amount_cents
        conn.execute(
            "UPDATE invoices SET open_cents = ? WHERE number = ?",
            (remaining, allocation.invoice_number),
        )
        if remaining == 0:
            debtor = conn.execute(
                "SELECT ship_before_payment FROM debtors WHERE id = ?",
                (row["debtor_id"],),
            ).fetchone()
            if debtor is not None and not debtor["ship_before_payment"]:
                lines = conn.execute(
                    """
                    SELECT slug, number_of_copies FROM invoice_lines
                    WHERE invoice_id = (SELECT id FROM invoices WHERE number = ?)
                    """,
                    (allocation.invoice_number,),
                ).fetchall()
                for line in lines:
                    _take_stock(conn, line["slug"], int(line["number_of_copies"]))
    conn.commit()


def euros_to_cents(amount: Decimal) -> int:
    return int((amount * Decimal(100)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def read_incoming_bookings(iban: str) -> list[Booking]:
    """Read money-in bookings on the Boog account. No write."""
    cleaned = re.sub(r"\s+", "", iban).upper()
    if not cleaned:
        return []
    import os

    url = os.environ.get("HUB_DATABASE_URL", "").strip()
    if not url:
        return []
    import pyodbc

    conn = pyodbc.connect(url, autocommit=True, timeout=15)
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT t.transaction_id, t.amount, t.description
            FROM dbo.transaction_beheer_boog t
            INNER JOIN dbo.account a ON a.account_id = t.account_id
            WHERE REPLACE(UPPER(a.iban), ' ', '') = ?
              AND t.amount > 0
            """,
            cleaned,
        )
        bookings = []
        for transaction_id, amount, description in cursor.fetchall():
            bookings.append(
                Booking(
                    transaction_id=int(transaction_id),
                    amount_cents=euros_to_cents(Decimal(str(amount))),
                    description=str(description or ""),
                )
            )
        return bookings
    finally:
        conn.close()


def sync_payments(conn: sqlite3.Connection, bookings: list[Booking]) -> list[Allocation]:
    planned = plan_allocations(open_invoices(conn), bookings, applied_transaction_ids(conn))
    apply_allocations(conn, planned)
    return planned


def sent_steps(conn: sqlite3.Connection) -> set[tuple[str, str]]:
    rows = conn.execute("SELECT invoice_number, step FROM reminder_sends").fetchall()
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


def record_reminder(conn: sqlite3.Connection, invoice: Invoice, step: str, when: datetime) -> None:
    conn.execute(
        """
        INSERT INTO reminder_sends (invoice_number, email, step, sent_at)
        VALUES (?, ?, ?, ?)
        """,
        (invoice.number, invoice.email, step, when.strftime("%Y-%m-%d %H:%M")),
    )
    conn.commit()


def match_settlement(description: str, settlement_id: str) -> bool:
    if not settlement_id:
        return False
    pattern = rf"(?<![A-Za-z0-9]){re.escape(settlement_id)}(?![A-Za-z0-9])"
    return re.search(pattern, description or "") is not None

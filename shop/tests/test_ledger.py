"""Invoice lines, bank matching, and reminder steps."""
from __future__ import annotations

import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

from app.catalog import Book
from app.ledger import (
    Booking,
    apply_allocations,
    create_invoice,
    get_invoice,
    numbers_in_description,
    open_invoices,
    plan_allocations,
    record_reminder,
    steps_due,
    stock_map,
    sync_payments,
)
from app.orders import connect

_BOOKS = (
    Book(
        slug="een",
        titel="Een",
        auteur="A",
        genre="G",
        tijdvak="nu",
        formaat="papier",
        isbn="",
        summary="",
        prijs_cent_excl=1000,
        cover="een.png",
        voorraad=5,
    ),
)


class LedgerTests(unittest.TestCase):
    def _conn(self, directory: Path):
        return connect(directory / "orders.sqlite")

    def test_one_line_stores_the_copy_count_and_lowers_stock(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            conn = self._conn(Path(tmp))
            many = Book(
                slug="een",
                titel="Een",
                auteur="A",
                genre="G",
                tijdvak="nu",
                formaat="papier",
                isbn="",
                summary="",
                prijs_cent_excl=1000,
                cover="een.png",
                voorraad=100,
            )
            invoice = create_invoice(
                conn,
                name="Parochie",
                email="a@example.com",
                address="Kerkstraat 1",
                vat_number="NL1",
                ship_before_payment=True,
                lines=[("een", 100, 1000)],
                when=datetime(2026, 10, 1, 9, 0),
                books=(many,),
            )
            self.assertEqual(invoice.number, "DB-00001")
            self.assertEqual(invoice.payable_cents, 100000)
            self.assertEqual(invoice.lines[0].number_of_copies, 100)
            self.assertEqual(stock_map(conn)["een"], 0)
            conn.close()

    def test_company_invoice_without_vat_number_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            conn = self._conn(Path(tmp))
            with self.assertRaises(ValueError):
                create_invoice(
                    conn,
                    name="Parochie",
                    email="a@example.com",
                    address="Kerkstraat 1",
                    vat_number="",
                    ship_before_payment=True,
                    lines=[("een", 1, 1000)],
                    when=datetime(2026, 10, 1, 9, 0),
                    books=_BOOKS,
                )
            self.assertNotIn("een", stock_map(conn))
            self.assertIsNone(get_invoice(conn, "DB-00001"))
            conn.close()

    def test_partial_payment_leaves_the_rest_open(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            conn = self._conn(Path(tmp))
            create_invoice(
                conn,
                name="Parochie",
                email="a@example.com",
                address="Kerkstraat 1",
                vat_number="NL1",
                ship_before_payment=True,
                lines=[("een", 2, 1000)],
                when=datetime(2026, 10, 1, 9, 0),
                books=_BOOKS,
            )
            applied = sync_payments(
                conn,
                [Booking(7, 500, "betaling DB-00001")],
            )
            self.assertEqual(applied[0].amount_cents, 500)
            self.assertEqual(get_invoice(conn, "DB-00001").open_cents, 1500)
            again = sync_payments(conn, [Booking(7, 500, "betaling DB-00001")])
            self.assertEqual(again, [])
            conn.close()

    def test_several_invoices_are_paid_only_when_the_sum_matches(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            conn = self._conn(Path(tmp))
            when = datetime(2026, 10, 1, 9, 0)
            first = create_invoice(
                conn,
                name="Een",
                email="a@example.com",
                address="Straat",
                vat_number="NL1",
                ship_before_payment=True,
                lines=[("een", 1, 1000)],
                when=when,
                books=_BOOKS,
            )
            second = create_invoice(
                conn,
                name="Twee",
                email="b@example.com",
                address="Straat",
                vat_number="NL2",
                ship_before_payment=True,
                lines=[("een", 1, 1000)],
                when=when,
                books=_BOOKS,
            )
            short = plan_allocations(
                open_invoices(conn),
                [Booking(1, 1000, f"{first.number} {second.number}")],
                set(),
            )
            self.assertEqual(short, [])
            full = plan_allocations(
                open_invoices(conn),
                [Booking(2, 2000, f"{first.number} en {second.number}")],
                set(),
            )
            self.assertEqual(len(full), 2)
            conn.close()

    def test_a_shorter_number_is_not_found_inside_a_longer_one(self) -> None:
        self.assertEqual(numbers_in_description("DB-000012", ["DB-00001", "DB-000012"]), ["DB-000012"])

    def test_pay_first_invoice_takes_stock_when_the_open_amount_hits_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            conn = self._conn(Path(tmp))
            invoice = create_invoice(
                conn,
                name="Lezer",
                email="a@example.com",
                address="Straat",
                vat_number="",
                ship_before_payment=False,
                lines=[("een", 2, 1000)],
                when=datetime(2026, 10, 1, 9, 0),
                books=_BOOKS,
            )
            self.assertEqual(stock_map(conn)["een"], 5)
            apply_allocations(
                conn,
                plan_allocations(open_invoices(conn), [Booking(3, 2000, invoice.number)], set()),
            )
            self.assertEqual(get_invoice(conn, invoice.number).open_cents, 0)
            self.assertEqual(stock_map(conn)["een"], 3)
            conn.close()

    def test_reminder_steps_follow_the_due_date_and_are_not_repeated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            conn = self._conn(Path(tmp))
            invoice = create_invoice(
                conn,
                name="Parochie",
                email="a@example.com",
                address="Straat",
                vat_number="NL1",
                ship_before_payment=True,
                lines=[("een", 1, 1000)],
                when=datetime(2026, 10, 1, 9, 0),
                books=_BOOKS,
            )
            self.assertEqual(invoice.due_on, date(2026, 10, 15))
            self.assertEqual(steps_due(invoice, date(2026, 10, 8), set()), ["before_7"])
            self.assertEqual(steps_due(invoice, date(2026, 10, 15), set()), ["due"])
            self.assertEqual(steps_due(invoice, date(2026, 10, 29), set()), ["after_14"])
            self.assertEqual(steps_due(invoice, date(2026, 11, 14), set()), ["after_30"])
            record_reminder(conn, invoice, "before_7", datetime(2026, 10, 8, 8, 0))
            stored = get_invoice(conn, invoice.number)
            sent = {("DB-00001", "before_7")}
            self.assertEqual(steps_due(stored, date(2026, 10, 8), sent), [])
            conn.close()

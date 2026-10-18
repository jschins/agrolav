"""Invoice matching helpers that do not need a live database."""
from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import date, datetime
from unittest.mock import Mock, patch

from app.ledger import (
    Booking,
    Allocation,
    Invoice,
    InvoiceLine,
    apply_allocations,
    apply_payment,
    numbers_in_description,
    plan_allocations,
    steps_due,
)
from app.reminders import send_invoice


def _invoice(number: str, open_cents: int, due: date | None = None) -> Invoice:
    return Invoice(
        number=number,
        name="Parochie",
        email="a@example.com",
        address="Kerkstraat 1, Utrecht",
        vat_number="NL1",
        ordered_at="2026-10-01 09:00",
        due_on=due or date(2026, 10, 15),
        payable_cents=open_cents,
        open_cents=open_cents,
        ship_before_payment=True,
        portokosten_cents=None,
        token="token",
        lines=(InvoiceLine("een", 1, open_cents),),
        debtor_id=1,
        customer_id=None,
        status="sent",
    )


class LedgerTests(unittest.TestCase):
    def test_numbers_in_description(self) -> None:
        self.assertEqual(numbers_in_description("Zet DB-00001 in de omschrijving", ["DB-00001"]), ["DB-00001"])
        self.assertEqual(numbers_in_description("DB-00001 en DB-00002", ["DB-00001", "DB-00002"]), ["DB-00001", "DB-00002"])

    def test_partial_payment_plan(self) -> None:
        planned = plan_allocations(
            [_invoice("DB-00001", 1000)],
            [Booking(1, 400, "DB-00001")],
            set(),
        )
        self.assertEqual(len(planned), 1)
        self.assertEqual(planned[0].amount_cents, 400)

    def test_reminder_steps(self) -> None:
        invoice = _invoice("DB-00001", 1000, due=date(2026, 10, 15))
        self.assertEqual(steps_due(invoice, date(2026, 10, 8), set()), ["before_7"])
        self.assertEqual(steps_due(invoice, date(2026, 10, 15), set()), ["due"])
        self.assertEqual(steps_due(invoice, date(2026, 10, 15), {("DB-00001", "due")}), [])

    def test_prepared_invoice_has_no_reminders(self) -> None:
        invoice = _invoice("DB-00001", 1000, due=date(2026, 10, 15))
        prepared = replace(invoice, status="prepared")
        self.assertEqual(steps_due(prepared, date(2026, 10, 8), set()), [])

    def test_full_bank_allocation_stores_the_booking_date(self) -> None:
        conn = Mock()
        with patch(
            "app.ledger.one",
            return_value={"open_cents": 1000, "customer_id": None, "status": "sent"},
        ), patch("app.ledger.run") as run:
            apply_allocations(
                conn,
                [Allocation(1, "BDF-100000", 1000, "2026-10-18")],
            )

        self.assertEqual(
            run.call_args_list[1].args[2],
            (0, "2026-10-18", 100000),
        )
        conn.commit.assert_called_once()

    def test_mollie_payment_stores_the_provider_payment_date(self) -> None:
        conn = Mock()
        invoice = _invoice("BDF-100000", 1000)
        with patch("app.ledger._take_stock"), patch("app.ledger.run") as run:
            result = apply_payment(
                conn,
                invoice,
                status="paid",
                amount_cents=1000,
                paid_at="2026-10-18T13:45:00+02:00",
            )

        self.assertEqual(result, "paid")
        self.assertEqual(
            run.call_args.args[2],
            ("2026-10-18T13:45:00+02:00", 100000),
        )
        conn.commit.assert_called_once()

    def test_invoice_email_contains_the_pdf_attachment_and_payment_details(self) -> None:
        invoice = _invoice("BDF-100000", 1000)
        with patch("app.reminders._deliver") as deliver:
            send_invoice("shop@example.com", invoice, b"%PDF-test", "NL00TEST")

        message = deliver.call_args.args[0]
        self.assertEqual(message["To"], invoice.email)
        body = message.get_body(preferencelist=("plain",)).get_content()
        self.assertIn(invoice.number, body)
        self.assertIn("NL00TEST", body)
        attachments = list(message.iter_attachments())
        self.assertEqual(len(attachments), 1)
        self.assertEqual(attachments[0].get_filename(), f"factuur-{invoice.number}.pdf")
        self.assertEqual(attachments[0].get_content(), b"%PDF-test")

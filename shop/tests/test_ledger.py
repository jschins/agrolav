"""Invoice matching helpers that do not need a live database."""
from __future__ import annotations

import unittest
from datetime import date, datetime

from app.ledger import (
    Booking,
    Invoice,
    InvoiceLine,
    numbers_in_description,
    plan_allocations,
    steps_due,
)


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

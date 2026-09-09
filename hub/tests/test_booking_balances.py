"""Booking rows on 1000-2999 feed non-bank balance totals."""
from __future__ import annotations

import unittest
from decimal import Decimal

from shared.balance_values import _booking_balances


class _FakeBookingCursor:
    def __init__(
        self,
        *,
        username: str | None = "beheer",
        table_exists: bool = True,
        rows: list | None = None,
    ) -> None:
        self.username = username
        self.table_exists = table_exists
        self.rows = rows or []
        self.sql = ""

    def execute(self, sql: str, params: tuple | None = None) -> "_FakeBookingCursor":
        del params
        self.sql = sql
        return self

    def fetchone(self):
        if "FROM dbo.country" in self.sql:
            return None if self.username is None else (self.username,)
        if "OBJECT_ID" in self.sql:
            return (1 if self.table_exists else None,)
        return None

    def fetchall(self):
        return list(self.rows)


class BookingBalancesTests(unittest.TestCase):
    def test_missing_country_returns_empty(self):
        self.assertEqual(
            _booking_balances(4, 2026, _FakeBookingCursor(username=None)),
            {},
        )

    def test_missing_table_returns_empty(self):
        self.assertEqual(
            _booking_balances(4, 2026, _FakeBookingCursor(table_exists=False)),
            {},
        )

    def test_loan_repayment_on_2500(self):
        cursor = _FakeBookingCursor(rows=[(2500, Decimal("-9333.32"))])
        self.assertEqual(
            _booking_balances(4, 2026, cursor),
            {2500: Decimal("-9333.32")},
        )


if __name__ == "__main__":
    unittest.main()

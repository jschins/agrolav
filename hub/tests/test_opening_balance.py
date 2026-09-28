"""Opening amounts: year-end of Y-1, then close category_role=balance into equity."""
from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal

from shared.balance_values import (
    CatalogError,
    afschrijving_booked_on,
    opening_amounts_from_year_end,
)


class OpeningAmountsTests(unittest.TestCase):
    def test_closes_balance_role_into_equity(self) -> None:
        amounts = opening_amounts_from_year_end(
            {
                10: (50_000, "opening+journal"),
                22: (12_500, "opening"),
                30: (99_900, "account:18"),
            },
            {20: Decimal("1000.00"), 22: Decimal("10.00")},
            {20: "equity", 22: "balance", 10: ""},
            {10: 1000, 20: 2000, 22: 2200, 30: 1051},
            20,
        )
        self.assertEqual(amounts[10], Decimal("500.00"))
        self.assertEqual(amounts[22], Decimal("0.00"))
        self.assertEqual(amounts[20], Decimal("1125.00"))
        self.assertNotIn(30, amounts)

    def test_existing_year_overwrites_live_bank_amounts(self) -> None:
        amounts = opening_amounts_from_year_end(
            {
                10: (50_000, "opening+journal"),
                22: (12_500, "opening"),
                30: (99_900, "account:18"),
            },
            {20: Decimal("1000.00")},
            {20: "equity", 22: "balance", 10: ""},
            {10: 1000, 20: 2000, 22: 2200, 30: 1051},
            20,
            include_live_banks=True,
        )
        self.assertEqual(amounts[30], Decimal("999.00"))
        self.assertEqual(amounts[10], Decimal("500.00"))

    def test_balance_role_missing_from_year_end_uses_its_opening(self) -> None:
        amounts = opening_amounts_from_year_end(
            {},
            {20: Decimal("40.00"), 22: Decimal("15.50")},
            {20: "equity", 22: "balance"},
            {20: 2000, 22: 2200},
            20,
        )
        self.assertEqual(amounts[22], Decimal("0.00"))
        self.assertEqual(amounts[20], Decimal("55.50"))

    def test_rc_posts_close_into_cp(self) -> None:
        amounts = opening_amounts_from_year_end(
            {
                22: (10_000, "opening"),
                101: (2_500, "opening+bookings"),
                119: (-4_000, "opening"),
                200: (8_000, "opening"),
                100: (1_000, "opening"),
            },
            {20: Decimal("500.00")},
            {
                20: "equity",
                22: "balance",
                101: "rc",
                119: "rc",
                100: "rc",
                200: "cp",
            },
            {20: 2000, 22: 2200, 101: 1101, 119: 1119, 100: 1100, 200: 1200},
            20,
        )
        self.assertEqual(amounts[101], Decimal("0.00"))
        self.assertEqual(amounts[119], Decimal("0.00"))
        self.assertEqual(amounts[100], Decimal("10.00"))
        self.assertEqual(amounts[200], Decimal("65.00"))
        self.assertEqual(amounts[20], Decimal("600.00"))

    def test_rc_without_cp_is_an_error(self) -> None:
        with self.assertRaises(CatalogError):
            opening_amounts_from_year_end(
                {101: (100, "opening")},
                {20: Decimal("1.00")},
                {20: "equity", 22: "balance", 101: "rc"},
                {20: 2000, 22: 2200, 101: 1101},
                20,
            )

    def test_missing_balance_role_is_an_error(self) -> None:
        with self.assertRaises(CatalogError):
            opening_amounts_from_year_end({}, {}, {20: "equity"}, {20: 2000}, 20)


class AfschrijvingDateTests(unittest.TestCase):
    def test_closed_year_stays_on_31_december(self) -> None:
        self.assertEqual(
            afschrijving_booked_on(2026, on=date(2027, 1, 15)),
            "2026-12-31",
        )

    def test_year_under_way_is_the_day_of_the_run(self) -> None:
        self.assertEqual(
            afschrijving_booked_on(2027, on=date(2027, 1, 15)),
            "2027-01-15",
        )


if __name__ == "__main__":
    unittest.main()

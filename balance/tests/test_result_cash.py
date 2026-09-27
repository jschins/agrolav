"""Cash table and sibling pairing for the resultaat window."""
from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal

from shared.balance_values import booking_signed_amount

from app.result import _names_pair, _unit_xx0x, build_cash_table


class SiblingTests(unittest.TestCase):
    def test_hd_name_pairs_with_the_unit(self) -> None:
        self.assertTrue(_names_pair("HD Den Eker", "Den Eker"))
        self.assertTrue(_names_pair("hd den eker", "den eker"))

    def test_unrelated_names_do_not_pair(self) -> None:
        self.assertFalse(_names_pair("Den Eker", "Den Eker"))
        self.assertFalse(_names_pair("HD Den Eker", "Aenstal"))

    def test_unit1104_reads_local_1114(self) -> None:
        digits = _unit_xx0x("unit1104")
        self.assertEqual(digits, 1104)
        self.assertEqual(digits + 10, 1114)
        signed = booking_signed_amount(1114, Decimal("-18500"))
        self.assertEqual(signed, Decimal("18500"))


class CashTableTests(unittest.TestCase):
    def test_single_bank_turns_red_when_the_totals_differ(self) -> None:
        cash = build_cash_table(
            [("Den Eker", Decimal("100"), Decimal("90"))],
            named=False,
            inkomsten=Decimal("18500"),
            uitgaven=Decimal("-20"),
            opening_day=date(2026, 1, 1),
            present_day=date(2026, 9, 27),
        )
        labels = [row["label"] for row in cash["rows"] if not row["gap"]]
        self.assertEqual(
            labels,
            [
                "Banksaldo d.d. 01/01/2026",
                "Inkomsten",
                "Uitgaven",
                "Totaal",
                "Banksaldo d.d. 27/09/2026",
            ],
        )
        self.assertTrue(cash["mismatch"])
        alert = [row["label"] for row in cash["rows"] if row["alert"]]
        self.assertEqual(alert, ["Totaal", "Banksaldo d.d. 27/09/2026"])
        self.assertEqual(cash["rows"][1]["amount"], 18500)

    def test_two_banks_color_both_totals(self) -> None:
        cash = build_cash_table(
            [
                ("Den Eker", Decimal("1000"), Decimal("800")),
                ("HD Den Eker", Decimal("500"), Decimal("700")),
            ],
            named=True,
            inkomsten=Decimal("100"),
            uitgaven=Decimal("-150"),
            opening_day=date(2026, 1, 1),
            present_day=date(2026, 9, 27),
        )
        labels = [row["label"] for row in cash["rows"] if not row["gap"]]
        self.assertEqual(
            labels,
            [
                "Banksaldo Den Eker d.d. 01/01/2026",
                "Banksaldo HD Den Eker d.d. 01/01/2026",
                "Inkomsten",
                "Uitgaven",
                "Totaal",
                "Banksaldo Den Eker d.d. 27/09/2026",
                "Banksaldo HD Den Eker d.d. 27/09/2026",
                "Totaal",
            ],
        )
        self.assertTrue(cash["mismatch"])
        alert = [row for row in cash["rows"] if row["alert"]]
        self.assertEqual([row["label"] for row in alert], ["Totaal", "Totaal"])
        self.assertEqual(alert[0]["amount"], 1450)
        self.assertEqual(alert[1]["amount"], 1500)

    def test_matching_totals_stay_plain(self) -> None:
        cash = build_cash_table(
            [("Bank", Decimal("10"), Decimal("40"))],
            named=False,
            inkomsten=Decimal("50"),
            uitgaven=Decimal("-20"),
            opening_day=date(2026, 1, 1),
            present_day=date(2026, 9, 27),
        )
        self.assertFalse(cash["mismatch"])
        self.assertFalse(any(row["alert"] for row in cash["rows"]))


if __name__ == "__main__":
    unittest.main()

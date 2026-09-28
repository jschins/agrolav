"""Cash table and sibling pairing for the resultaat window."""
from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal

from app.result import (
    _BankAccount,
    _fold_cash_extras,
    _is_unit_level,
    _names_pair,
    _unit_kind,
    _unit_xx0x,
    build_cash_table,
)


class SiblingTests(unittest.TestCase):
    def test_hd_name_pairs_with_the_unit(self) -> None:
        self.assertTrue(_names_pair("HD Den Eker", "Den Eker"))
        self.assertTrue(_names_pair("hd den eker", "den eker"))

    def test_unrelated_names_do_not_pair(self) -> None:
        self.assertFalse(_names_pair("Den Eker", "Den Eker"))
        self.assertFalse(_names_pair("HD Den Eker", "Aenstal"))

    def test_unit1104_is_xx0x(self) -> None:
        self.assertEqual(_unit_xx0x("unit1104"), 1104)
        self.assertIsNone(_unit_xx0x("unit1114"))


class UnitLevelTests(unittest.TestCase):
    def test_unit_flag_or_account_marks_a_unit_login(self) -> None:
        self.assertTrue(_is_unit_level("1", ""))
        self.assertTrue(_is_unit_level("", "NL00INGB0000000001"))
        self.assertFalse(_is_unit_level("", ""))

    def test_role_decides_hd_or_unit(self) -> None:
        hd = _BankAccount(1, "HD Den Eker", Decimal("0"), "", 7, "", "den_eker", "hd")
        unit = _BankAccount(2, "Den Eker", Decimal("0"), "", 7, "", "den_eker", "unit1104")
        self.assertEqual(_unit_kind(hd, "hd_den_eker"), "hd")
        self.assertEqual(_unit_kind(unit, "den_eker"), "unit")
        self.assertEqual(_unit_kind(None, "hd_den_eker"), "hd")
        self.assertEqual(_unit_kind(None, "den_eker"), "unit")


class CrossCashTests(unittest.TestCase):
    def test_sib_unit_folds_1125_and_its_own_code(self) -> None:
        lines = _fold_cash_extras(
            [
                (1125, "r/c centrale", Decimal("-2490"), "sib"),
                (1108, "r/c Lepelenburg", Decimal("10"), "rc"),
                (1118, "r/c HD Lepelenburg", Decimal("100"), "cp"),
                (1200, "Kruisposten", Decimal("-100"), "cp"),
                (3001, "Lonen", Decimal("5"), ""),
            ],
            center="lepelenburg",
        )
        self.assertEqual(
            lines,
            [
                ("Rekening courant SIb", Decimal("-2480")),
                ("Lonen", Decimal("5")),
            ],
        )

    def test_unbalanced_sibling_posts_stay_visible(self) -> None:
        lines = _fold_cash_extras(
            [
                (1118, "r/c HD Lepelenburg", Decimal("2490"), "cp"),
                (1200, "Kruisposten", Decimal("-100"), "cp"),
            ],
            center="lepelenburg",
        )
        self.assertEqual(lines, [("Kruisposten", Decimal("2390"))])

    def test_sia_center_uses_rekening_courant_sia(self) -> None:
        lines = _fold_cash_extras(
            [(1126, "r/c", Decimal("2490"), "sia")],
            center="center_sia",
        )
        self.assertEqual(lines, [("Rekening courant SIa", Decimal("2490"))])


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

    def test_rekening_courant_sits_in_the_top_total(self) -> None:
        cash = build_cash_table(
            [
                ("Den Eker", Decimal("7029"), Decimal("5596")),
                ("HD Den Eker", Decimal("4751"), Decimal("5397")),
            ],
            named=True,
            inkomsten=Decimal("55498"),
            uitgaven=Decimal("-33009"),
            opening_day=date(2026, 1, 1),
            present_day=date(2026, 9, 27),
            extras=[("Rekening courant SIb", Decimal("-23286"))],
        )
        labels = [row["label"] for row in cash["rows"] if not row["gap"]]
        self.assertEqual(
            labels[:5],
            [
                "Banksaldo Den Eker d.d. 01/01/2026",
                "Banksaldo HD Den Eker d.d. 01/01/2026",
                "Inkomsten",
                "Uitgaven",
                "Rekening courant SIb",
            ],
        )
        self.assertEqual(cash["rows"][4]["amount"], -23286)
        self.assertEqual(cash["rows"][5]["amount"], 10983)

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

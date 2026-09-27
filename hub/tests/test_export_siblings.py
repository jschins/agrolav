"""Export balans sums a unit and its HD sibling into one column and one bank post."""
from __future__ import annotations

import unittest
from decimal import Decimal

from app.sql_catalog import (
    add_afschrijving_to_centrale,
    afschrijving_column,
    afschrijving_side,
    ensure_centrale_columns,
    merge_sibling_balance,
    merge_sibling_pnl,
    order_export_columns,
    sibling_pairs,
)


def _account(
    account_id: int,
    name: str,
    role: str,
    center_id: int = 1,
    local_code: int | None = None,
) -> dict:
    return {
        "account_id": account_id,
        "account_name": name,
        "center_id": center_id,
        "role": role,
        "local_code": local_code,
        "iban": None,
        "person": None,
    }


class SiblingPairTests(unittest.TestCase):
    def test_den_eker_pairs_with_its_hd(self) -> None:
        pairs = sibling_pairs(
            [
                _account(40, "Den Eker", "unit1104", local_code=1025),
                _account(48, "HD Den Eker", "hd", local_code=1026),
                _account(43, "Lepelenburg", "unit1108", center_id=2, local_code=1022),
            ]
        )
        self.assertEqual([(unit["account_id"], hd["account_id"]) for unit, hd in pairs], [(40, 48)])

    def test_bank_prefix_still_pairs(self) -> None:
        pairs = sibling_pairs(
            [
                _account(40, "Bank Den Eker", "unit1104"),
                _account(48, "Bank HD Den Eker", "hd"),
            ]
        )
        self.assertEqual(len(pairs), 1)

    def test_two_hd_accounts_follow_the_name(self) -> None:
        pairs = sibling_pairs(
            [
                _account(1, "Den Eker", "unit1104"),
                _account(2, "HD Lepelenburg", "hd"),
                _account(3, "HD Den Eker", "hd"),
            ]
        )
        self.assertEqual(pairs[0][1]["account_id"], 3)


class SiblingMergeTests(unittest.TestCase):
    def test_pnl_columns_add_the_hd_into_the_unit(self) -> None:
        accounts = [
            {"account_id": 40, "account_name": "Den Eker", "iban": None, "person": None},
            {"account_id": 48, "account_name": "HD Den Eker", "iban": None, "person": None},
            {"account_id": 43, "account_name": "Lepelenburg", "iban": None, "person": None},
        ]
        sums = {
            13001: {40: Decimal("10"), 48: Decimal("3"), 43: Decimal("1")},
            14000: {48: Decimal("7")},
        }
        pairs = sibling_pairs(
            [
                _account(40, "Den Eker", "unit1104"),
                _account(48, "HD Den Eker", "hd"),
                _account(43, "Lepelenburg", "unit1108", center_id=2),
            ]
        )
        merged, folded = merge_sibling_pnl(accounts, sums, pairs)
        self.assertEqual([item["account_id"] for item in merged], [40, 43])
        self.assertEqual(folded[13001][40], Decimal("13"))
        self.assertNotIn(48, folded[13001])
        self.assertEqual(folded[14000][40], Decimal("7"))

    def test_balance_posts_add_the_hd_bank_into_the_unit(self) -> None:
        rows = [
            {"code": 1025, "label": "Bank Den Eker", "amount": 100.5},
            {"code": 1026, "label": "Bank HD Den Eker", "amount": 40},
            {"code": 1022, "label": "Bank Lepelenburg", "amount": 9},
        ]
        pairs = [
            (
                _account(40, "Den Eker", "unit1104", local_code=1025),
                _account(48, "HD Den Eker", "hd", local_code=1026),
            )
        ]
        merged = merge_sibling_balance(rows, pairs)
        self.assertEqual([row["code"] for row in merged], [1025, 1022])
        self.assertEqual(merged[0]["amount"], 140.5)
        self.assertEqual(merged[0]["label"], "Bank Den Eker")


class ExportColumnOrderTests(unittest.TestCase):
    def test_sia_then_sib_then_units_by_number(self) -> None:
        metas = [
            {"account_id": 20, "account_name": "Bank Centrale SIb", "role": "source", "parent": "Activa/Vlottende activa/Bank SIb"},
            {"account_id": 10, "account_name": "Bank Centrale SIa", "role": "source", "parent": "Activa/Vlottende activa/Bank SIa"},
            {"account_id": 8, "account_name": "Lepelenburg", "role": "unit1108", "parent": "Activa/Vlottende activa/Bank SIb"},
            {"account_id": 4, "account_name": "Den Eker", "role": "unit1104", "parent": "Activa/Vlottende activa/Bank SIb"},
            {"account_id": 11, "account_name": "SVOa", "role": "unit1110", "parent": "Activa/Vlottende activa/Bank SIa"},
            {"account_id": 1, "account_name": "Aenstal", "role": "unit1101", "parent": "Activa/Vlottende activa/Bank SIa"},
            {"account_id": 5, "account_name": "Hogeland", "role": "unit1105", "parent": "Activa/Vlottende activa/Bank SIa"},
        ]
        ordered = order_export_columns(
            [{"account_id": item["account_id"], "account_name": item["account_name"]} for item in metas],
            metas,
        )
        self.assertEqual(
            [item["account_name"] for item in ordered],
            ["SIa", "SIb", "Aenstal", "Hogeland", "SVOa", "Den Eker", "Lepelenburg"],
        )


class AfschrijvingColumnTests(unittest.TestCase):
    def test_side_comes_from_the_description(self) -> None:
        self.assertEqual(afschrijving_side("vaste afschrijving SIb"), "sib")
        self.assertEqual(afschrijving_side("vaste  afschrijving SIa"), "sia")
        self.assertIsNone(afschrijving_side("[afschrijving] FALSE: afgeboekte bedragen [1060]"))
        self.assertIsNone(afschrijving_side("gewone boeking SIa"))

    def test_pnl_leg_lands_on_the_matching_centrale(self) -> None:
        accounts = ensure_centrale_columns(
            [{"account_id": 40, "account_name": "Den Eker", "iban": None, "person": None}],
            [
                {"account_id": 10, "account_name": "Bank Centrale SIa", "iban": None, "person": None},
                {"account_id": 20, "account_name": "Bank Centrale SIb", "iban": None, "person": None},
            ],
        )
        sums: dict[int, dict[int, Decimal]] = {13105: {}}
        add_afschrijving_to_centrale(
            accounts,
            sums,
            [
                (11050, 13105, Decimal("-72612"), "vaste afschrijving SIa"),
                (11050, 13105, Decimal("-46000"), "vaste afschrijving SIb"),
            ],
            lambda cat: cat - 10000,
        )
        self.assertEqual(sums[13105][10], Decimal("-72612"))
        self.assertEqual(sums[13105][20], Decimal("-46000"))
        self.assertEqual(
            [item["account_name"] for item in accounts if item["account_id"] in (10, 20)],
            ["Bank Centrale SIa", "Bank Centrale SIb"],
        )


class PercentageAfschrijvingTests(unittest.TestCase):
    def test_percentage_rule_goes_fully_to_sib(self) -> None:
        text = "[afschrijving] FALSE: afgeboekte bedragen [1050] × -0.03"
        self.assertIsNone(afschrijving_side(text))
        self.assertEqual(afschrijving_column(text), "sib")
        self.assertEqual(afschrijving_column("vaste afschrijving SIa"), "sia")


if __name__ == "__main__":
    unittest.main()

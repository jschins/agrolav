"""Export balans sums a unit and its HD sibling into one column and one bank post."""
from __future__ import annotations

import unittest
from decimal import Decimal

from app.sql_catalog import (
    merge_sibling_balance,
    merge_sibling_pnl,
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


if __name__ == "__main__":
    unittest.main()

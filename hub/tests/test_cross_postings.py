"""Cross-postings: registered-account transfers with a same-day counterpart."""
from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal

from app.cross_postings import (
    CROSS_POSTING_CATEGORY_ID,
    _IBAN_NL46,
    _IBAN_NL84,
    between_registered_accounts,
    category_id_for_local_code,
    category_id_offset,
    is_country_bank_role,
    managed_category_ids,
    matching_transaction_ids,
    pair_local_codes,
    stored_category_id,
    user_digits,
)


class CrossPostingMatchTests(unittest.TestCase):
    def test_opposite_amounts_on_two_accounts_match(self) -> None:
        day = date(2026, 3, 1)
        matched = matching_transaction_ids(
            [
                (1, 10, day, Decimal("-12.50"), 20),
                (2, 20, day, Decimal("12.50"), 10),
                (3, 10, day, Decimal("-4.00"), 20),
            ]
        )
        self.assertEqual(matched, {1, 2})

    def test_same_account_does_not_match(self) -> None:
        day = date(2026, 3, 1)
        matched = matching_transaction_ids(
            [
                (1, 10, day, Decimal("-8"), 10),
                (2, 10, day, Decimal("8"), 10),
            ]
        )
        self.assertEqual(matched, set())

    def test_extra_same_amount_on_that_day_stays_out(self) -> None:
        day = date(2026, 3, 1)
        matched = matching_transaction_ids(
            [
                (1, 10, day, Decimal("-100"), 20),
                (2, 20, day, Decimal("100"), 10),
                (3, 30, day, Decimal("100"), 10),
            ]
        )
        self.assertEqual(matched, {1, 2})

    def test_different_day_does_not_match(self) -> None:
        matched = matching_transaction_ids(
            [
                (1, 10, date(2026, 3, 1), Decimal("-8"), 20),
                (2, 20, date(2026, 3, 2), Decimal("8"), 10),
            ]
        )
        self.assertEqual(matched, set())

    def test_receipt_without_a_return_iban_is_not_a_pair(self) -> None:
        day = date(2026, 9, 8)
        matched = matching_transaction_ids(
            [
                (1, 10, day, Decimal("-2700"), 20),
                (2, 20, day, Decimal("2700"), None),
            ]
        )
        self.assertEqual(matched, set())

    def test_both_bookings_must_name_each_other_and_oppose(self) -> None:
        day = date(2026, 9, 8)
        matched = matching_transaction_ids(
            [
                (1, 10, day, Decimal("-2700"), 20),
                (2, 20, day, Decimal("2700"), 10),
            ]
        )
        self.assertEqual(matched, {1, 2})

    def test_opposite_amount_on_a_different_account_is_not_the_counterpart(self) -> None:
        day = date(2026, 9, 2)
        matched = matching_transaction_ids(
            [
                (1, 10, day, Decimal("-2400"), 20),
                (2, 30, day, Decimal("2400"), 10),
            ]
        )
        self.assertEqual(matched, set())

    def test_payment_without_a_receipt_that_day_is_rejected(self) -> None:
        matched = matching_transaction_ids(
            [
                (1, 10, date(2026, 9, 2), Decimal("-2400"), 20),
            ]
        )
        self.assertEqual(matched, set())

    def test_only_registered_counterparty_ibans_enter_the_list(self) -> None:
        day = date(2026, 9, 8)
        accounts = {
            "NL97INGB0114425876": [20],
            "NL11INGB0006729488": [30],
        }
        kept = between_registered_accounts(
            [
                (1, 10, day, Decimal("-2700"), "NL97 INGB 0114 4258 76"),
                (2, 10, day, Decimal("-50"), "NL00INGB0000000000"),
                (3, 10, day, Decimal("500"), "nl11ingb0006729488"),
            ],
            accounts,
        )
        self.assertEqual([row[0] for row in kept], [1, 3])
        self.assertEqual(kept[0][4], 20)
        self.assertEqual(kept[1][4], 30)

    def test_sib_to_sia_is_11200_and_11100(self) -> None:
        self.assertEqual(pair_local_codes(_IBAN_NL46, _IBAN_NL84), (1200, 1100))
        self.assertEqual(pair_local_codes(_IBAN_NL84, _IBAN_NL46), (1100, 1200))
        self.assertEqual(
            category_id_for_local_code(1200),
            11200,
        )
        self.assertEqual(category_id_for_local_code(1100), 11100)

    def test_sib_to_a_sib_unit_is_the_unit_code_and_11125(self) -> None:
        self.assertEqual(
            pair_local_codes(_IBAN_NL46, "NL61INGB0002843544", "sib", "sib", "", "unit1108"),
            (1108, 1125),
        )
        self.assertEqual(category_id_for_local_code(1108), 11108)
        self.assertEqual(category_id_for_local_code(1125), 11125)
        self.assertEqual(
            pair_local_codes("NL61INGB0002843544", _IBAN_NL46, "sib", "sib", "unit1108", ""),
            (1125, 1108),
        )
        self.assertEqual(
            pair_local_codes(_IBAN_NL46, "NL61INGB0002843544", "sib", "sia", "", "unit1108"),
            (None, None),
        )

    def test_sia_to_a_sia_unit_is_the_unit_code_and_11126(self) -> None:
        self.assertEqual(
            pair_local_codes(_IBAN_NL84, "NL61INGB0002843544", "sia", "sia", "", "unit1108"),
            (1108, 1126),
        )
        self.assertEqual(category_id_for_local_code(1126), 11126)
        self.assertEqual(
            pair_local_codes("NL61INGB0002843544", _IBAN_NL84, "sia", "sia", "unit1108", ""),
            (1126, 1108),
        )

    def test_unit_xx0x_and_hd_sibling_split_1xx1x_and_11200(self) -> None:
        self.assertEqual(
            pair_local_codes(
                "NL00INGB0000000001",
                "NL00INGB0000000002",
                "sib",
                "sib",
                "unit1108",
                "hd",
            ),
            (1118, 1200),
        )
        self.assertEqual(
            pair_local_codes(
                "NL00INGB0000000002",
                "NL00INGB0000000001",
                "sia",
                "sia",
                "hd",
                "unit1102",
            ),
            (1200, 1112),
        )
        self.assertEqual(category_id_for_local_code(1118), 11118)
        self.assertEqual(category_id_for_local_code(1112), 11112)
        self.assertEqual(category_id_for_local_code(1200), 11200)
        self.assertEqual(
            pair_local_codes(
                "NL00INGB0000000001",
                "NL00INGB0000000002",
                "sib",
                "sia",
                "unit1108",
                "hd",
            ),
            (None, None),
        )
        self.assertEqual(
            pair_local_codes(
                "NL00INGB0000000001",
                "NL00INGB0000000002",
                "sib",
                "sib",
                "unit1025",
                "hd",
            ),
            (None, None),
        )

    def test_everything_else_stays_uncategorized(self) -> None:
        self.assertEqual(
            pair_local_codes("NL11INGB0006729488", "NL61INGB0002843544"),
            (None, None),
        )
        self.assertEqual(pair_local_codes(_IBAN_NL84, _IBAN_NL84), (None, None))

    def test_country_banks_are_roles_starting_with_unit_source_or_funds(self) -> None:
        self.assertTrue(is_country_bank_role("unit1108"))
        self.assertTrue(is_country_bank_role("user1108"))
        self.assertTrue(is_country_bank_role("source"))
        self.assertTrue(is_country_bank_role("funds"))
        self.assertFalse(is_country_bank_role("bank"))
        self.assertFalse(is_country_bank_role("mirror"))
        self.assertEqual(user_digits("unit1108"), 1108)

    def test_category_id_is_11200_not_the_local_code(self) -> None:
        self.assertEqual(CROSS_POSTING_CATEGORY_ID, 11200)

    def test_country_5_stores_local_code_plus_10000(self) -> None:
        self.assertEqual(pair_local_codes(_IBAN_NL46, _IBAN_NL84), (1200, 1100))
        self.assertEqual(category_id_for_local_code(1099), 11099)
        self.assertEqual(category_id_for_local_code(1100), 11100)
        self.assertEqual(category_id_for_local_code(1108), 11108)
        self.assertEqual(category_id_for_local_code(1200), 11200)
        self.assertEqual(category_id_for_local_code(1200, country_id=4), 1200)
        balance = [4, 5, 6]
        self.assertEqual(category_id_offset(4, balance), 0)
        self.assertEqual(category_id_offset(5, balance), 10000)
        self.assertEqual(category_id_offset(6, balance), 20000)
        self.assertEqual(category_id_for_local_code(1099, 6, balance), 21099)
        self.assertEqual(category_id_for_local_code(1200, 6, balance), 21200)
        # Country 7 takes the next block only when it has a balance.
        # A gap (no balance on 6) does not consume 20000.
        self.assertEqual(category_id_for_local_code(1100, 7, [4, 5, 7]), 21100)
        self.assertEqual(category_id_for_local_code(1100, 7, [4, 5, 6, 7]), 31100)

    def test_a_live_bank_category_is_not_released(self) -> None:
        found = managed_category_ids(
            {
                1099: 11099,
                1100: 11100,
                1125: 11125,
                1126: 11126,
                1200: 11200,
                3125: 13125,
                3126: 13126,
                1021: 11021,
            },
            {1108, 1021},
            {11021},
        )
        self.assertIn(11099, found)
        self.assertIn(11100, found)
        self.assertIn(11125, found)
        self.assertIn(11126, found)
        self.assertIn(11200, found)
        self.assertIn(13125, found)
        self.assertIn(13126, found)
        self.assertIn(11108, found)
        self.assertNotIn(11021, found)

    def test_dim_category_row_supplies_the_stored_id(self) -> None:
        self.assertEqual(stored_category_id(1099, {1099: 11099}), 11099)
        self.assertEqual(stored_category_id(1099, {}), 11099)


if __name__ == "__main__":
    unittest.main()

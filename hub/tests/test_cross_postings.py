"""Cross-postings: registered-account transfers with a same-day counterpart."""
from __future__ import annotations

import unittest
from datetime import date, timedelta
from decimal import Decimal

from app.cross_postings import (
    CategoryLink,
    PairLegs,
    _IBAN_NL46,
    _IBAN_NL84,
    _load_candidates,
    _pair_locals,
    assoc_pair_local_codes,
    between_registered_accounts,
    category_id_for_local_code,
    category_id_offset,
    is_country_bank_role,
    managed_category_ids,
    matching_transaction_ids,
    pair_local_codes,
    stored_category_id,
    user_digits,
    _sheet_pair_opposed,
)

# Country 5 rows: cp 1200, siasib 1100, sia 1126, sib 1125.
_LEGS = PairLegs(cp=1200, siasib=1100, sia=1126, sib=1125)


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

    def test_one_day_apart_matches(self) -> None:
        matched = matching_transaction_ids(
            [
                (1, 10, date(2026, 3, 1), Decimal("-8"), 20),
                (2, 20, date(2026, 3, 2), Decimal("8"), 10),
            ]
        )
        self.assertEqual(matched, {1, 2})

    def test_same_day_wins_over_the_neighbouring_day(self) -> None:
        day = date(2026, 3, 1)
        matched = matching_transaction_ids(
            [
                (1, 10, day, Decimal("-8"), 20),
                (2, 20, day, Decimal("8"), 10),
                (3, 20, day + timedelta(days=1), Decimal("8"), 10),
            ]
        )
        self.assertEqual(matched, {1, 2})

    def test_two_days_apart_does_not_match(self) -> None:
        matched = matching_transaction_ids(
            [
                (1, 10, date(2026, 3, 1), Decimal("-8"), 20),
                (2, 20, date(2026, 3, 3), Decimal("8"), 10),
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

    def test_sib_to_sia_is_the_cp_row_and_the_siasib_row(self) -> None:
        self.assertEqual(pair_local_codes(_IBAN_NL46, _IBAN_NL84, legs=_LEGS), (1200, 1100))
        self.assertEqual(pair_local_codes(_IBAN_NL84, _IBAN_NL46, legs=_LEGS), (1100, 1200))
        self.assertEqual(
            category_id_for_local_code(1200),
            11200,
        )
        self.assertEqual(category_id_for_local_code(1100), 11100)
        # No cp / siasib rows: both legs stay uncategorized.
        self.assertEqual(pair_local_codes(_IBAN_NL46, _IBAN_NL84), (None, None))

    def test_sib_to_a_sib_unit_is_the_unit_code_and_the_sib_row(self) -> None:
        self.assertEqual(
            pair_local_codes(
                _IBAN_NL46, "NL61INGB0002843544", "sib", "sib", "", "unit1108",
                legs=_LEGS,
            ),
            (1108, 1125),
        )
        self.assertEqual(category_id_for_local_code(1108), 11108)
        self.assertEqual(category_id_for_local_code(1125), 11125)
        self.assertEqual(
            pair_local_codes(
                "NL61INGB0002843544", _IBAN_NL46, "sib", "sib", "unit1108", "",
                legs=_LEGS,
            ),
            (1125, 1108),
        )
        self.assertEqual(
            pair_local_codes(
                _IBAN_NL46, "NL61INGB0002843544", "sib", "sia", "", "unit1108",
                legs=_LEGS,
            ),
            (None, None),
        )
        # No sib row in dim_category: the unit leg is left uncategorized.
        self.assertEqual(
            pair_local_codes(_IBAN_NL46, "NL61INGB0002843544", "sib", "sib", "", "unit1108"),
            (1108, None),
        )

    def test_sia_to_a_sia_unit_is_the_unit_code_and_the_sia_row(self) -> None:
        self.assertEqual(
            pair_local_codes(
                _IBAN_NL84, "NL61INGB0002843544", "sia", "sia", "", "unit1108",
                legs=_LEGS,
            ),
            (1108, 1126),
        )
        self.assertEqual(category_id_for_local_code(1126), 11126)
        self.assertEqual(
            pair_local_codes(
                "NL61INGB0002843544", _IBAN_NL84, "sia", "sia", "unit1108", "",
                legs=_LEGS,
            ),
            (1126, 1108),
        )

    def test_unit_xx0x_and_hd_sibling_split_1xx1x_and_the_cp_row(self) -> None:
        self.assertEqual(
            pair_local_codes(
                "NL00INGB0000000001",
                "NL00INGB0000000002",
                "sib",
                "sib",
                "unit1108",
                "hd",
                legs=_LEGS,
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
                legs=_LEGS,
            ),
            (1200, 1112),
        )
        self.assertEqual(category_id_for_local_code(1118), 11118)
        self.assertEqual(category_id_for_local_code(1112), 11112)
        self.assertEqual(category_id_for_local_code(1200), 11200)
        self.assertTrue(
            _sheet_pair_opposed(1118, Decimal("-100"), 1200, Decimal("100"))
        )
        self.assertTrue(
            _sheet_pair_opposed(1100, Decimal("100"), 1200, Decimal("-100"))
        )
        self.assertTrue(
            _sheet_pair_opposed(1108, Decimal("-100"), 1126, Decimal("100"))
        )
        self.assertTrue(
            _sheet_pair_opposed(1108, Decimal("-100"), 1125, Decimal("100"))
        )
        self.assertEqual(
            pair_local_codes(
                "NL00INGB0000000001",
                "NL00INGB0000000002",
                "sib",
                "sia",
                "unit1108",
                "hd",
                legs=_LEGS,
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
                legs=_LEGS,
            ),
            (None, None),
        )

    def test_assoc_writes_cp_on_the_hd_booking(self) -> None:
        links = (
            CategoryLink(1053, 1053, "hd", 44, 1056),
            CategoryLink(1056, 1056, "unit", 21, 1051),
            CategoryLink(1051, 1051, "source", 18, 1101),
            CategoryLink(1101, 1101, "rc", 21, 1051),
            CategoryLink(1111, 1111, "rc", 44, 1056),
            CategoryLink(11020, 1020, "source", 39, 11125),
            CategoryLink(11025, 1025, "unit", 40, 11020),
            CategoryLink(11125, 1125, "sib", 39, 11020),
            CategoryLink(11010, 1010, "source", 60, 11126),
            CategoryLink(11100, 1100, "siasib", 60, 11020),
            CategoryLink(11126, 1126, "sia", 60, 11010),
        )
        self.assertEqual(
            assoc_pair_local_codes(links, 21, 44, "keizersgracht", "keizersgracht", 1110),
            (1111, 1110),
        )
        self.assertEqual(
            assoc_pair_local_codes(links, 44, 21, "keizersgracht", "keizersgracht", 1110),
            (1110, 1111),
        )
        self.assertEqual(
            assoc_pair_local_codes(links, 21, 18, "keizersgracht", "algemeen", 1110),
            (1101, 1110),
        )
        self.assertEqual(
            assoc_pair_local_codes(links, 18, 21, "algemeen", "keizersgracht", 1110),
            (1110, 1101),
        )
        self.assertEqual(
            assoc_pair_local_codes(links, 40, 39, "den eker", "sib", 1200),
            (1125, 1200),
        )
        self.assertEqual(
            assoc_pair_local_codes(links, 39, 40, "sib", "den eker", 1200),
            (1200, 1125),
        )
        self.assertEqual(
            assoc_pair_local_codes(links, 60, 39, "sia", "sib", 1200),
            (1100, 1200),
        )
        self.assertEqual(
            assoc_pair_local_codes(links, 39, 60, "sib", "sia", 1200),
            (1200, 1100),
        )

    def test_everything_else_stays_uncategorized(self) -> None:
        self.assertEqual(
            pair_local_codes("NL11INGB0006729488", "NL61INGB0002843544", legs=_LEGS),
            (None, None),
        )
        self.assertEqual(pair_local_codes(_IBAN_NL84, _IBAN_NL84, legs=_LEGS), (None, None))

    def test_country_banks_are_roles_starting_with_unit_source_or_funds(self) -> None:
        self.assertTrue(is_country_bank_role("unit1108"))
        self.assertTrue(is_country_bank_role("user1108"))
        self.assertTrue(is_country_bank_role("source"))
        self.assertTrue(is_country_bank_role("funds"))
        self.assertFalse(is_country_bank_role("bank"))
        self.assertFalse(is_country_bank_role("mirror"))
        self.assertEqual(user_digits("unit1108"), 1108)

    def test_pair_legs_codes_skip_missing_rows(self) -> None:
        self.assertEqual(_LEGS.codes(), {1100, 1125, 1126, 1200})
        self.assertEqual(PairLegs(cp=1200).codes(), {1200})
        self.assertEqual(PairLegs().codes(), set())

    def test_country_5_stores_local_code_plus_10000(self) -> None:
        self.assertEqual(pair_local_codes(_IBAN_NL46, _IBAN_NL84, legs=_LEGS), (1200, 1100))
        self.assertEqual(category_id_for_local_code(1100), 11100)
        self.assertEqual(category_id_for_local_code(1108), 11108)
        self.assertEqual(category_id_for_local_code(1200), 11200)
        self.assertEqual(category_id_for_local_code(1200, country_id=4), 1200)
        balance = [4, 5, 6]
        self.assertEqual(category_id_offset(4, balance), 0)
        self.assertEqual(category_id_offset(5, balance), 10000)
        self.assertEqual(category_id_offset(6, balance), 20000)
        self.assertEqual(category_id_for_local_code(1100, 6, balance), 21100)
        self.assertEqual(category_id_for_local_code(1200, 6, balance), 21200)
        # Country 7 takes the next block only when it has a balance.
        # A gap (no balance on 6) does not consume 20000.
        self.assertEqual(category_id_for_local_code(1100, 7, [4, 5, 7]), 21100)
        self.assertEqual(category_id_for_local_code(1100, 7, [4, 5, 6, 7]), 31100)

    def test_a_live_bank_category_is_not_released(self) -> None:
        found = managed_category_ids(
            {
                1100: 11100,
                1125: 11125,
                1126: 11126,
                1200: 11200,
                1021: 11021,
            },
            {1108, 1021},
            {11021},
            role_codes=_LEGS.codes(),
        )
        self.assertIn(11100, found)
        self.assertIn(11125, found)
        self.assertIn(11126, found)
        self.assertIn(11200, found)
        self.assertIn(11108, found)
        self.assertNotIn(11021, found)
        # Without role rows only the digit codes are managed.
        self.assertEqual(managed_category_ids({}, {1108}), {1108, 11108})

    def test_dim_category_row_supplies_the_stored_id(self) -> None:
        self.assertEqual(stored_category_id(1100, {1100: 11100}), 11100)
        self.assertEqual(stored_category_id(1100, {}), 11100)


class LoadCandidatesSqlTests(unittest.TestCase):
    def test_accounts_without_categories_omit_the_empty_in_list(self) -> None:
        class Cursor:
            def __init__(self) -> None:
                self.sql = ""
                self.params: tuple = ()

            def execute(self, sql: str, params: object) -> None:
                self.sql = sql
                self.params = tuple(params)

            def fetchall(self) -> list:
                return []

        cursor = Cursor()
        self.assertEqual(_load_candidates(cursor, "dbo.transaction_nederland", {18}, set()), [])
        self.assertNotIn("IN ()", cursor.sql)
        self.assertIn("WHERE (t.account_id IN (?))", cursor.sql)
        self.assertIn("t.bank_type <> N'Geldautomaat'", cursor.sql)
        self.assertNotIn("category_id IN", cursor.sql)
        self.assertEqual(cursor.params, (18,))

    def test_no_accounts_and_no_categories_runs_no_sql(self) -> None:
        class Cursor:
            def execute(self, sql: str, params: object) -> None:
                raise AssertionError(sql)

        self.assertEqual(_load_candidates(Cursor(), "dbo.transaction_nederland", set(), set()), [])


if __name__ == "__main__":
    unittest.main()

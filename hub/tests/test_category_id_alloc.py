"""New booking category_id must fit the transaction table CHECK, not country*10000."""
from __future__ import annotations

import unittest

from app.sql_catalog import (
    _new_booking_category_id,
    _next_booking_category_id,
    _parse_txn_cat_check,
    category_id_bounds,
)


class CategoryIdAllocTests(unittest.TestCase):
    def test_beheer_formula_was_40000_block(self) -> None:
        lo, hi = category_id_bounds(4)
        self.assertEqual((lo, hi), (40000, 49999))
        used = {3001, 3300, 3997, 3998, 3999}
        self.assertEqual(_next_booking_category_id(used, lo, hi), 40003)

    def test_beheer_new_row_uses_local_code(self) -> None:
        used = {3001, 3997, 3998, 3999, 4000}
        self.assertEqual(_new_booking_category_id(used, 3300, 1000, 9999), 3300)

    def test_parse_beheer_check(self) -> None:
        self.assertEqual(
            _parse_txn_cat_check("([category_id]>=(1000) AND [category_id]<(10000))"),
            (1000, 9999),
        )


if __name__ == "__main__":
    unittest.main()

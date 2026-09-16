"""New booking category_id must fit the transaction table CHECK, not country*10000."""
from __future__ import annotations

import unittest

from app.sql_catalog import (
    _new_booking_category_id,
    _next_booking_category_id,
    _parse_catalog_items,
    _parse_txn_cat_check,
    category_id_bounds,
)


class CategoryIdAllocTests(unittest.TestCase):
    def test_beheer_formula_was_40000_block(self) -> None:
        lo, hi = category_id_bounds(4)
        self.assertEqual((lo, hi), (40000, 49999))
        used = {3001, 3300, 3500, 3501, 3502}
        self.assertEqual(_next_booking_category_id(used, lo, hi), 40003)

    def test_beheer_new_row_uses_local_code(self) -> None:
        used = {3001, 3500, 3501, 3502, 4000}
        self.assertEqual(_new_booking_category_id(used, 3300, 1000, 9999), 3300)

    def test_parse_beheer_check(self) -> None:
        self.assertEqual(
            _parse_txn_cat_check("([category_id]>=(1000) AND [category_id]<(10000))"),
            (1000, 9999),
        )


class CatalogParseTests(unittest.TestCase):
    def test_requires_id_and_refuses_duplicate_id_or_code(self) -> None:
        with self.assertRaisesRegex(ValueError, "numeric id"):
            _parse_catalog_items(
                [
                    {
                        "local_code": 12,
                        "label": "A",
                        "is_remainder": True,
                    }
                ]
            )
        rows = [
            {
                "category_id": 12,
                "local_code": 12,
                "label": "A",
                "is_remainder": True,
            },
            {
                "category_id": 12,
                "local_code": 13,
                "label": "B",
                "is_remainder": False,
            },
        ]
        with self.assertRaisesRegex(ValueError, "id 12 is already in use"):
            _parse_catalog_items(rows)
        rows[1]["category_id"] = 13
        rows[1]["local_code"] = 12
        with self.assertRaisesRegex(ValueError, "code 0012 is already in use"):
            _parse_catalog_items(rows)

    def test_allows_duplicate_labels(self) -> None:
        parsed = _parse_catalog_items(
            [
                {
                    "category_id": 12,
                    "local_code": 12,
                    "label": "Same",
                    "is_remainder": True,
                },
                {
                    "category_id": 13,
                    "local_code": 13,
                    "label": "Same",
                    "is_remainder": False,
                },
            ]
        )
        self.assertEqual([row["category_id"] for row in parsed], [12, 13])


if __name__ == "__main__":
    unittest.main()

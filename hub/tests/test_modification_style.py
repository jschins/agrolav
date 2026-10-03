"""2 and 4 bold the category. 3 and 4 blue the description. 2 leaves it black."""
import unittest

from app.core import categorize
from app.sql_replica import stored_category_id_for_code


def _row(row_id: str, modification: int) -> dict:
    return {
        "id": row_id,
        "modification": modification,
        "type": "Bank",
        "category": 3100,
    }


class StyleFlagTests(unittest.TestCase):
    def test_category_hand_is_bold_only(self):
        blue, bold = categorize.style_flags_for_row(_row("a", 2))
        self.assertFalse(blue)
        self.assertTrue(bold)

    def test_description_hand_is_blue_only(self):
        blue, bold = categorize.style_flags_for_row(_row("b", 3))
        self.assertTrue(blue)
        self.assertFalse(bold)

    def test_both_hands_mark_each_field(self):
        blue, bold = categorize.style_flags_for_row(_row("a", 4))
        self.assertTrue(blue)
        self.assertTrue(bold)

    def test_term_row_has_neither_mark(self):
        blue, bold = categorize.style_flags_for_row(_row("c", 0))
        self.assertFalse(blue)
        self.assertFalse(bold)


class CombineHandFlagTests(unittest.TestCase):
    def test_description_on_a_category_hand_writes_both(self):
        self.assertEqual(
            categorize._combine_hand_flags(categorize.MOD_HAND, description=True),
            categorize.MOD_BOTH,
        )

    def test_category_on_a_description_hand_writes_both(self):
        self.assertEqual(
            categorize._combine_hand_flags(categorize.MOD_DESCRIPTION, category=True),
            categorize.MOD_BOTH,
        )

    def test_description_on_an_open_row_writes_3(self):
        self.assertEqual(
            categorize._combine_hand_flags(categorize.MOD_NONE, description=True),
            categorize.MOD_DESCRIPTION,
        )

    def test_category_on_an_open_row_writes_2(self):
        self.assertEqual(
            categorize._combine_hand_flags(categorize.MOD_NONE, category=True),
            categorize.MOD_HAND,
        )


class HandCategoryIdTests(unittest.TestCase):
    def test_hand_pick_stores_the_category_id_for_that_local_code(self) -> None:
        self.assertEqual(
            stored_category_id_for_code(1301, {}, {1301: 21301}, 18, 2),
            21301,
        )

    def test_term_write_does_not_use_a_role_terms_cannot_hit(self) -> None:
        self.assertEqual(
            stored_category_id_for_code(1051, {}, {1051: 21051}, 18, 0),
            18,
        )


if __name__ == "__main__":
    unittest.main()

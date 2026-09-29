"""Category hand is bold. Description hand is blue on that cell only."""
import unittest

from app.core import categorize


def _row(row_id: str, modification: int, *, excel: bool = False) -> dict:
    return {
        "id": row_id,
        "modification": modification,
        "type": "Excel" if excel else "Bank",
        "category": 3100,
    }


class StyleFlagTests(unittest.TestCase):
    def test_category_hand_is_bold_only(self):
        blue, bold = categorize.style_flags_for_row(_row("a", 2), {"a"})
        self.assertFalse(blue)
        self.assertTrue(bold)

    def test_description_hand_is_blue_only(self):
        blue, bold = categorize.style_flags_for_row(_row("b", 2), set())
        self.assertTrue(blue)
        self.assertFalse(bold)

    def test_both_hands_mark_each_field(self):
        blue, bold = categorize.style_flags_for_row(_row("a", 3), {"a"})
        self.assertTrue(blue)
        self.assertTrue(bold)

    def test_term_row_has_neither_mark(self):
        blue, bold = categorize.style_flags_for_row(_row("c", 0), set())
        self.assertFalse(blue)
        self.assertFalse(bold)


if __name__ == "__main__":
    unittest.main()

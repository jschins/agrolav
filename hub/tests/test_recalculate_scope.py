"""Recalculate categories stays inside the login, and G-terms stay with country."""
import unittest

from app.store import term_changes_in_scope

_ROWS = [
    {"id": 1, "term": "ah", "added": True, "person": None, "account": None, "center": None},
    {"id": 2, "term": "rent", "added": True, "person": "sia", "account": "uid-a", "center": "dkg"},
    {"id": 3, "term": "food", "added": False, "person": "sia", "account": None, "center": "dkg"},
    {"id": 4, "term": "tax", "added": True, "person": "sib", "account": "uid-b", "center": "gph"},
]


class TermChangeScopeTests(unittest.TestCase):
    def test_country_applies_g_terms_and_every_center(self):
        apply_rows, clear_ids = term_changes_in_scope(
            _ROWS, center="dkg", whole_country=True
        )
        self.assertEqual([row["id"] for row in apply_rows], [1, 2, 3, 4])
        self.assertEqual(clear_ids, [1, 2, 3, 4])

    def test_center_skips_g_terms_and_other_centers(self):
        apply_rows, clear_ids = term_changes_in_scope(_ROWS, center="dkg")
        self.assertEqual([row["id"] for row in apply_rows], [2, 3])
        self.assertEqual(clear_ids, [2, 3])

    def test_person_skips_g_terms_and_other_people(self):
        apply_rows, clear_ids = term_changes_in_scope(
            _ROWS, center="dkg", person="sia"
        )
        self.assertEqual([row["id"] for row in apply_rows], [2, 3])
        self.assertEqual(clear_ids, [2, 3])

    def test_unit_rescores_its_account_and_leaves_person_wide_terms(self):
        apply_rows, clear_ids = term_changes_in_scope(
            _ROWS, center="dkg", person="sia", account_uid="uid-a"
        )
        self.assertEqual([row["id"] for row in apply_rows], [2, 3])
        self.assertEqual(clear_ids, [2])


if __name__ == "__main__":
    unittest.main()

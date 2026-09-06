"""From-scratch recalculation must keep user-set category/description locks."""
import unittest
from unittest.mock import patch

from app.core import categorize

_GENERAL = {
    "18 Unclassified expenses": ["1800"],
    "1005 Zorgverlening": ["1005"],
}


def _row(
    transaction_id: str,
    *,
    modification: int,
    category: int | None = None,
    type_: str = "SEPA",
) -> dict:
    return {
        "id": transaction_id,
        "amount": "-12.50",
        "currency": "EUR",
        "type": type_,
        "name": "Somewhere",
        "iban": "NL00BANK0000000000",
        "description": "zzz-no-match",
        "date": "01-01-2026",
        "category": category,
        "modification": modification,
        "hit": "some-rule",
    }


class RecalculateFromScratchLocksTests(unittest.TestCase):
    def test_user_set_locks_and_excel_survive_from_scratch(self):
        store = {
            "transactions": [
                _row("auto", modification=categorize.MOD_NONE, category=1800),
                _row("lock-cat", modification=categorize.MOD_CATEGORY, category=1005),
                _row("lock-desc", modification=categorize.MOD_DESCRIPTION, category=1800),
                _row("lock-both", modification=categorize.MOD_BOTH, category=1005),
                _row("excel", modification=categorize.MOD_NONE, category=1005, type_="Excel"),
                _row("uncalc", modification=categorize.MOD_UNCALCULATED),
            ]
        }
        persisted: list[dict] = []
        with (
            patch.object(categorize, "_load_categorized_store", return_value=store),
            patch.object(categorize, "_persist_categorized_store", side_effect=persisted.append),
            patch.object(categorize, "_categories_file", return_value=_GENERAL),
            patch.object(categorize, "_personal_category_map", return_value={}),
            patch.object(categorize, "_write_category_totals", return_value={}),
        ):
            categorize.recategorize_transactions(from_scratch=True)

        by_id = {t["id"]: t for t in persisted[-1]["transactions"]}

        self.assertEqual(by_id["lock-cat"]["category"], 1005)
        self.assertEqual(by_id["lock-cat"]["modification"], categorize.MOD_CATEGORY)

        self.assertEqual(by_id["lock-desc"]["modification"], categorize.MOD_DESCRIPTION)

        self.assertEqual(by_id["lock-both"]["category"], 1005)
        self.assertEqual(by_id["lock-both"]["modification"], categorize.MOD_BOTH)

        self.assertEqual(by_id["excel"]["category"], 1005)
        self.assertEqual(by_id["excel"]["modification"], categorize.MOD_CATEGORY)

        self.assertEqual(by_id["auto"]["modification"], categorize.MOD_NONE)
        self.assertEqual(by_id["uncalc"]["modification"], categorize.MOD_NONE)
        for row in persisted[-1]["transactions"]:
            self.assertIsNone(row["hit"])

    def test_non_scratch_still_preserves_locks(self):
        store = {
            "transactions": [
                _row("lock-cat", modification=categorize.MOD_CATEGORY, category=1005),
                _row("auto", modification=categorize.MOD_NONE, category=1800),
            ]
        }
        persisted: list[dict] = []
        with (
            patch.object(categorize, "_load_categorized_store", return_value=store),
            patch.object(categorize, "_persist_categorized_store", side_effect=persisted.append),
            patch.object(categorize, "_categories_file", return_value=_GENERAL),
            patch.object(categorize, "_personal_category_map", return_value={}),
            patch.object(categorize, "_write_category_totals", return_value={}),
        ):
            categorize.recategorize_transactions()

        by_id = {t["id"]: t for t in persisted[-1]["transactions"]}
        self.assertEqual(by_id["lock-cat"]["category"], 1005)
        self.assertEqual(by_id["lock-cat"]["modification"], categorize.MOD_CATEGORY)


if __name__ == "__main__":
    unittest.main()
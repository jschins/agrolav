"""Unlocked rows: all terms first; A/P beats R; type rules only as fallback."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from app.core import categorize

_CATALOG = {
    "categories": {
        "18 Unclassified expenses": [],
        "1052 Spaarrekening": ["spaarrekening"],
        "1110 Kruisposten": ["oude gracht"],
        "3110 Kosten": ["oranje", "oude"],
    },
    "category_roles": {
        "18 Unclassified expenses": "remainder",
        "1052 Spaarrekening": "mirror",
    },
    "typerules": [
        {"type": "Online bankieren", "category": "3110 Kosten"},
    ],
}


def _row(*, source_id: str, description: str, name: str = "", tx_type: str = "Online bankieren") -> dict:
    return {
        "id": source_id,
        "amount": "-100.00",
        "currency": "EUR",
        "type": tx_type,
        "name": name,
        "iban": "",
        "description": description,
        "date": "01-01-2026",
        "category": 3110,
        "modification": categorize.MOD_NONE,
        "hit": None,
        "account_uid": "acct-a",
    }


class TermPriorityTests(unittest.TestCase):
    def test_terms_beat_type_rule_and_ap_beats_r(self):
        store = {
            "transactions": [
                _row(
                    source_id="279",
                    name="Zakelijke oranje spaarrekening",
                    description="Naar spaarrekening",
                ),
                _row(
                    source_id="524",
                    name="Stichting de Oude Gracht",
                    description="Naam: Stichting de Oude Gracht",
                ),
            ]
        }
        persisted: list[dict] = []
        with (
            patch.object(categorize, "_categories_file", return_value=_CATALOG),
            patch.object(categorize, "_account_modality", return_value=False),
            patch.object(categorize, "_personal_category_map", return_value={}),
            patch.object(categorize, "_load_categorized_store", return_value=store),
            patch.object(
                categorize,
                "_persist_categorized_store",
                side_effect=persisted.append,
            ),
            patch.object(categorize, "_write_category_totals", return_value={}),
        ):
            categorize.recategorize_transactions()
        by_id = {row["id"]: row for row in persisted[-1]["transactions"]}
        self.assertEqual(by_id["279"]["category"], 1052)
        self.assertEqual(by_id["524"]["category"], 1110)


if __name__ == "__main__":
    unittest.main()

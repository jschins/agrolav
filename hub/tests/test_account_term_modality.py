"""Account-modality personal terms: P terms scope to one account (has_balance=1)."""
import unittest
from unittest.mock import patch

from app.core import categorize

_GENERAL = {
    "18 Unclassified expenses": ["1800"],
    "1005 Zorgverlening": ["1005"],
}

_ACCOUNT_A = "7ca377ed-1a28-499d-a155-d19e9f4cacb5"
_ACCOUNT_B = "52a3fbb6-4675-4a6f-a664-5f63bef89188"


def _row(
    transaction_id: str,
    *,
    account_uid: str,
    description: str = "zzz-no-match",
    category: int | None = None,
    modification: int = -1,
    hit: str | None = None,
) -> dict:
    return {
        "id": transaction_id,
        "amount": "-12.50",
        "currency": "EUR",
        "type": "SEPA",
        "name": "Somewhere",
        "iban": "NL00BANK0000000000",
        "description": description,
        "date": "01-01-2026",
        "category": category,
        "modification": modification,
        "hit": hit,
        "account_uid": account_uid,
    }


def _transactions_of(persisted: list[dict]) -> dict[str, dict]:
    return {row["id"]: row for row in persisted[-1]["transactions"]}


class AccountModalityRecategorizeTests(unittest.TestCase):
    def test_p_term_only_applies_to_its_own_account(self):
        store = {
            "transactions": [
                _row("tx-a", account_uid=_ACCOUNT_A, description="Studiecentrum fees"),
                _row("tx-b", account_uid=_ACCOUNT_B, description="Studiecentrum fees"),
            ]
        }
        personal_maps = {
            _ACCOUNT_A: {"1005 Zorgverlening": ["studiecentrum"]},
            _ACCOUNT_B: {},
        }
        persisted: list[dict] = []
        with (
            patch.object(categorize, "_categories_file", return_value=_GENERAL),
            patch.object(categorize, "_account_modality", return_value=True),
            patch.object(
                categorize, "_personal_category_maps", return_value=personal_maps
            ),
            patch.object(categorize, "_load_categorized_store", return_value=store),
            patch.object(
                categorize,
                "_persist_categorized_store",
                side_effect=persisted.append,
            ),
            patch.object(categorize, "_write_category_totals", return_value={}),
        ):
            categorize.recategorize_transactions(from_scratch=True)
        by_id = _transactions_of(persisted)
        self.assertEqual(by_id["tx-a"]["category"], 1005)
        self.assertIn("P:", str(by_id["tx-a"]["hit"]))
        self.assertEqual(by_id["tx-b"]["category"], 18)
        self.assertIsNone(by_id["tx-b"]["hit"])

    def test_person_modality_unaffected(self):
        store = {
            "transactions": [
                _row("tx-p", account_uid=_ACCOUNT_A, description="Studiecentrum fees"),
                _row("tx-q", account_uid=_ACCOUNT_B, description="Studiecentrum fees"),
            ]
        }
        persisted: list[dict] = []
        with (
            patch.object(categorize, "_categories_file", return_value=_GENERAL),
            patch.object(categorize, "_account_modality", return_value=False),
            patch.object(
                categorize,
                "_personal_category_map",
                return_value={"1005 Zorgverlening": ["studiecentrum"]},
            ),
            patch.object(categorize, "_load_categorized_store", return_value=store),
            patch.object(
                categorize,
                "_persist_categorized_store",
                side_effect=persisted.append,
            ),
            patch.object(categorize, "_write_category_totals", return_value={}),
        ):
            categorize.recategorize_transactions(from_scratch=True)
        by_id = _transactions_of(persisted)
        for row_id in ("tx-p", "tx-q"):
            self.assertEqual(by_id[row_id]["category"], 1005)
            self.assertIn("P:", str(by_id[row_id]["hit"]))


class AccountModalityIrcftTests(unittest.TestCase):
    def test_add_term_outranks_and_reweights_own_account_only(self):
        store = {
            "transactions": [
                _row(
                    "tx-a",
                    account_uid=_ACCOUNT_A,
                    description="Leidenhoven College tuition",
                    category=18,
                    modification=categorize.MOD_NONE,
                    hit="G:college",
                ),
                _row(
                    "tx-b",
                    account_uid=_ACCOUNT_B,
                    description="Leidenhoven College tuition",
                    category=1005,
                    modification=categorize.MOD_NONE,
                    hit="G:college",
                ),
            ]
        }
        personal_maps = {_ACCOUNT_A: {}, _ACCOUNT_B: {}}
        persisted: list[dict] = []
        with (
            patch.object(categorize, "_categories_file", return_value=_GENERAL),
            patch.object(categorize, "_account_modality", return_value=True),
            patch.object(
                categorize, "_personal_category_maps", return_value=personal_maps
            ),
            patch.object(categorize, "_load_categorized_store", return_value=store),
            patch.object(
                categorize,
                "_persist_categorized_store",
                side_effect=persisted.append,
            ),
            patch.object(categorize, "_write_category_totals", return_value={}),
        ):
            categorize.apply_ircft_terms(
                added=["leidenhoven"],
                removed=[],
                personal=True,
                category_name="1005 Zorgverlening",
                account=_ACCOUNT_A,
            )
        by_id = _transactions_of(persisted)
        self.assertEqual(by_id["tx-a"]["category"], 1005)
        self.assertIn("P:", str(by_id["tx-a"]["hit"]))
        self.assertEqual(by_id["tx-b"]["category"], 1005)
        self.assertEqual(by_id["tx-b"]["hit"], "G:college")

    def test_remove_term_resets_only_its_own_account(self):
        store = {
            "transactions": [
                _row(
                    "tx-a",
                    account_uid=_ACCOUNT_A,
                    description="Den Eker grocery",
                    category=1005,
                    modification=categorize.MOD_NONE,
                    hit="P:eker",
                ),
                _row(
                    "tx-b",
                    account_uid=_ACCOUNT_B,
                    description="Den Eker grocery",
                    category=1005,
                    modification=categorize.MOD_NONE,
                    hit="P:eker",
                ),
            ]
        }
        personal_maps = {_ACCOUNT_A: {}, _ACCOUNT_B: {}}
        persisted: list[dict] = []
        with (
            patch.object(categorize, "_categories_file", return_value=_GENERAL),
            patch.object(categorize, "_account_modality", return_value=True),
            patch.object(
                categorize, "_personal_category_maps", return_value=personal_maps
            ),
            patch.object(categorize, "_load_categorized_store", return_value=store),
            patch.object(
                categorize,
                "_persist_categorized_store",
                side_effect=persisted.append,
            ),
            patch.object(categorize, "_write_category_totals", return_value={}),
        ):
            categorize.apply_ircft_terms(
                added=[],
                removed=["eker"],
                personal=True,
                category_name="1005 Zorgverlening",
                account=_ACCOUNT_A,
            )
        by_id = _transactions_of(persisted)
        self.assertIsNone(by_id["tx-a"]["hit"])
        self.assertEqual(by_id["tx-a"]["category"], 18)
        self.assertEqual(by_id["tx-b"]["hit"], "P:eker")
        self.assertEqual(by_id["tx-b"]["category"], 1005)


if __name__ == "__main__":
    unittest.main()
"""Rabobank downloads stay raw; ING stays on the existing reader."""
import unittest

from app.core.enable_banking import EnableBankingError
from app.core.rabobank_export import (
    collect_raw,
    format_for_account,
    is_rabobank_format,
    split_accounts,
)


class RabobankFormatTests(unittest.TestCase):
    def test_only_rabobank_spelling(self):
        self.assertTrue(is_rabobank_format("Rabobank"))
        self.assertTrue(is_rabobank_format(" rabobank "))
        self.assertFalse(is_rabobank_format("ING"))
        self.assertFalse(is_rabobank_format("RABO"))
        self.assertFalse(is_rabobank_format(""))
        self.assertFalse(is_rabobank_format(None))

    def test_uid_wins_over_iban(self):
        formats = {"uid:abc": "ING", "iban:NL66RABO0324666403": "Rabobank"}
        account = {"uid": "abc", "iban": "NL66 RABO 0324 6664 03"}
        self.assertEqual(format_for_account(account, formats), "ING")

    def test_iban_match_ignores_spaces(self):
        formats = {"iban:NL66RABO0324666403": "Rabobank"}
        account = {"uid": "new", "iban": "NL66 RABO 0324 6664 03"}
        self.assertEqual(format_for_account(account, formats), "Rabobank")

    def test_split_keeps_ing_on_the_existing_side(self):
        accounts = [
            {"uid": "rabo", "iban": "NL66RABO0324666403"},
            {"uid": "ing", "iban": "NL34INGB0004378667"},
            {"uid": "blank", "iban": "NL00TEST0000000001"},
        ]
        formats = {
            "uid:rabo": "Rabobank",
            "uid:ing": "ING",
        }
        rabobank, other = split_accounts(accounts, formats)
        self.assertEqual([item["uid"] for item in rabobank], ["rabo"])
        self.assertEqual([item["uid"] for item in other], ["ing", "blank"])


class RabobankCollectTests(unittest.TestCase):
    def test_transactions_are_unmodified(self):
        raw = {"transaction_id": "RB-1", "booking_date": "2026-02-01", "note": "as-is"}

        def fetch(uid: str, date_from: str | None, date_to: str | None):
            self.assertEqual(uid, "rabo-uid")
            self.assertEqual(date_from, "2026-01-01")
            self.assertEqual(date_to, "2026-10-09")
            return [raw]

        document, errors = collect_raw(
            [{"uid": "rabo-uid", "iban": "NL66RABO0324666403", "name": "K218"}],
            date_from="2026-01-01",
            date_to="2026-10-09",
            person="k218",
            fetch=fetch,
        )
        self.assertEqual(errors, [])
        self.assertEqual(document["aspsp"], "Rabobank")
        self.assertEqual(document["person"], "k218")
        stored = document["accounts"][0]["transactions"][0]
        self.assertEqual(stored, raw)
        self.assertNotIn("_account_uid", stored)
        self.assertNotIn("_account_index", stored)

    def test_all_account_failures_raise(self):
        def fetch(uid: str, date_from: str | None, date_to: str | None):
            del uid, date_from, date_to
            raise EnableBankingError("down")

        with self.assertRaises(EnableBankingError):
            collect_raw(
                [{"uid": "rabo-uid", "iban": "NL66RABO0324666403", "name": "K218"}],
                date_from="2026-01-01",
                date_to="2026-10-09",
                person="k218",
                fetch=fetch,
            )

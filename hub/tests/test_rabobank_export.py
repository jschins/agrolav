"""Rabobank bookings keep the ING reader and fill the counterparty IBAN."""
import unittest

from app.core.enable_banking import EnableBankingError
from app.core.rabobank_export import (
    download_transactions,
    format_for_account,
    is_rabobank_format,
    simplify_rabobank,
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


class RabobankSimplifyTests(unittest.TestCase):
    def test_credit_uses_debtor_iban(self):
        record = simplify_rabobank(
            {
                "entry_reference": "3055",
                "booking_date": "2026-10-05",
                "credit_debit_indicator": "CRDT",
                "transaction_amount": {"amount": "350.00", "currency": "EUR"},
                "debtor": {"name": "Missione Cattolica Italiana inOl."},
                "debtor_account": {"iban": "NL67INGB0675890934"},
                "creditor_account": {"iban": "NL66RABO0324666403"},
                "remittance_information": ["Huur voor augustus en september"],
                "_account_index": 0,
                "_account_uid": "uid-1",
                "_own_iban": "NL66RABO0324666403",
            }
        )
        self.assertEqual(record["id"], "3055_0")
        self.assertEqual(record["amount"], "+350.00")
        self.assertEqual(record["name"], "Missione Cattolica Italiana inOl.")
        self.assertEqual(record["description"], "Huur voor augustus en september")
        self.assertEqual(record["iban"], "NL67INGB0675890934")
        self.assertEqual(record["date"], "05-10-2026")

    def test_debit_uses_creditor_iban(self):
        record = simplify_rabobank(
            {
                "entry_reference": "10",
                "booking_date": "2026-03-01",
                "credit_debit_indicator": "DBIT",
                "transaction_amount": {"amount": "12.00", "currency": "EUR"},
                "creditor": {"name": "Shop"},
                "creditor_account": {"iban": "NL00BANK0000000001"},
                "debtor_account": {"iban": "NL66RABO0324666403"},
                "remittance_information": ["note"],
                "_own_iban": "NL66RABO0324666403",
                "_account_index": 0,
            }
        )
        self.assertEqual(record["amount"], "-12.00")
        self.assertEqual(record["iban"], "NL00BANK0000000001")

    def test_own_iban_and_card_payment_stay_empty(self):
        costs = simplify_rabobank(
            {
                "entry_reference": "3054",
                "booking_date": "2026-10-01",
                "credit_debit_indicator": "DBIT",
                "transaction_amount": {"amount": "24.05", "currency": "EUR"},
                "creditor": {"name": "Rabobank"},
                "creditor_account": {"iban": "NL66RABO0324666403"},
                "debtor_account": {"iban": "NL66RABO0324666403"},
                "_own_iban": "NL66RABO0324666403",
                "_account_index": 0,
            }
        )
        card = simplify_rabobank(
            {
                "entry_reference": "3051",
                "booking_date": "2026-09-30",
                "credit_debit_indicator": "DBIT",
                "transaction_amount": {"amount": "77.61", "currency": "EUR"},
                "creditor": {"name": "Albert Heijn 1458"},
                "creditor_account": None,
                "debtor_account": {"iban": "NL66RABO0324666403"},
                "_own_iban": "NL66RABO0324666403",
                "_account_index": 0,
            }
        )
        self.assertEqual(costs["iban"], "")
        self.assertEqual(costs["name"], "Rabobank")
        self.assertEqual(card["iban"], "")
        self.assertEqual(card["name"], "Albert Heijn 1458")

    def test_download_tags_a_copy(self):
        raw = {"entry_reference": "1", "booking_date": "2026-02-01"}

        def fetch(uid: str, date_from: str | None, date_to: str | None):
            self.assertEqual((uid, date_from, date_to), ("rabo-uid", "2026-01-01", "2026-10-09"))
            return [raw]

        tagged, errors = download_transactions(
            [{"uid": "rabo-uid", "iban": "NL66 RABO 0324 6664 03", "name": "K218"}],
            date_from="2026-01-01",
            date_to="2026-10-09",
            fetch=fetch,
            index_by_uid={"rabo-uid": 0},
        )
        self.assertEqual(errors, [])
        self.assertEqual(tagged[0]["_account_uid"], "rabo-uid")
        self.assertEqual(tagged[0]["_own_iban"], "NL66RABO0324666403")
        self.assertNotIn("_account_uid", raw)

    def test_all_account_failures_raise(self):
        def fetch(uid: str, date_from: str | None, date_to: str | None):
            del uid, date_from, date_to
            raise EnableBankingError("down")

        with self.assertRaises(EnableBankingError):
            download_transactions(
                [{"uid": "rabo-uid", "iban": "NL66RABO0324666403", "name": "K218"}],
                date_from="2026-01-01",
                date_to="2026-10-09",
                fetch=fetch,
            )

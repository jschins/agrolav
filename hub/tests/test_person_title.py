"""Person title from bank account fields (periodic consent)."""
import unittest

from app.core.single_client import _normalize_account
from app.enable_sql import person_title_from_bank_accounts


class PersonTitleFromBankTests(unittest.TestCase):
    def test_uses_enable_banking_holder_name(self):
        self.assertEqual(
            person_title_from_bank_accounts(
                [
                    {
                        "uid": "acc-1",
                        "iban": "NL00BANK0123456789",
                        "name": "Juleon Schins",
                    }
                ]
            ),
            "Juleon Schins",
        )

    def test_uses_legacy_holder_when_name_missing(self):
        self.assertEqual(
            person_title_from_bank_accounts(
                [{"iban": "NL00BANK0123456789", "holder": "Ada Lovelace"}]
            ),
            "Ada Lovelace",
        )

    def test_skips_iban_copied_into_name(self):
        self.assertEqual(
            person_title_from_bank_accounts(
                [{"iban": "NL00BANK0123456789", "name": "NL00BANK0123456789"}]
            ),
            "",
        )

    def test_reads_nested_session_account(self):
        self.assertEqual(
            person_title_from_bank_accounts(
                [
                    {
                        "uid": "acc-1",
                        "account_id": {"iban": "FI0455231152453547"},
                        "name": "Organisation/Person Name",
                    }
                ]
            ),
            "Organisation/Person Name",
        )

    def test_normalize_keeps_holder_as_name(self):
        acc = _normalize_account(
            {
                "uid": "u",
                "iban": "NL00BANK0123456789",
                "holder": "Ada Lovelace",
                "identification_hash": "h",
            }
        )
        self.assertEqual(acc["name"], "Ada Lovelace")
        self.assertEqual(acc["holder"], "Ada Lovelace")

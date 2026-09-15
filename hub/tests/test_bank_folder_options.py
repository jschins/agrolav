"""Switcher folders only when a person has more than one account."""
from __future__ import annotations

import unittest
from unittest import mock

from app.core.bank_csv import person_bank_folder_options


class PersonBankFolderOptionsTests(unittest.TestCase):
    @mock.patch("app.user_store.list_accounts_for_username")
    def test_single_account_hides_switcher(self, listed):
        listed.return_value = [{"iban": "NL00BANK0123456789", "account_name": "Ada"}]
        opts = person_bank_folder_options(person="ada")
        self.assertEqual(opts["folders"], [])
        self.assertFalse(opts["multi_bank"])
        self.assertFalse(opts["show_switcher"])

    @mock.patch("app.user_store.list_accounts_for_username")
    def test_two_accounts_show_switcher(self, listed):
        listed.return_value = [
            {"iban": "NL01", "account_name": "Ada ING"},
            {"iban": "NL02", "account_name": "Ada ABN"},
        ]
        opts = person_bank_folder_options(person="ada")
        self.assertEqual(len(opts["folders"]), 2)
        self.assertTrue(opts["multi_bank"])
        self.assertTrue(opts["show_switcher"])

    @mock.patch("app.user_store.list_accounts_for_username")
    def test_no_accounts_empty_folders(self, listed):
        listed.return_value = []
        opts = person_bank_folder_options(person="ada")
        self.assertEqual(opts["folders"], [])
        self.assertFalse(opts["show_switcher"])

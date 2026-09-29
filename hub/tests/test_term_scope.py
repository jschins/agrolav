"""Who may change G-terms, and which account a unit login may change."""
import unittest

from shared.user_access import (
    ACCESS_CENTER,
    ACCESS_COUNTRY,
    ACCESS_PERSON,
    ACCESS_UNIT,
    can_edit_general_terms,
    unit_may_edit_account,
)

_OWN = "NL00BANK0000000001"
_OTHER = "NL00BANK0000000002"
_GROUPS = [
    {"account_key": "uid-own", "iban": _OWN},
    {"account_key": "uid-other", "iban": _OTHER},
]


class GeneralTermEditTests(unittest.TestCase):
    def test_only_country_may_edit_general_terms(self):
        self.assertTrue(can_edit_general_terms(ACCESS_COUNTRY))
        self.assertFalse(can_edit_general_terms(ACCESS_CENTER))
        self.assertFalse(can_edit_general_terms(ACCESS_PERSON))
        self.assertFalse(can_edit_general_terms(ACCESS_UNIT))
        self.assertFalse(can_edit_general_terms(""))


class UnitAccountTermTests(unittest.TestCase):
    def test_unit_may_edit_only_its_own_account(self):
        self.assertTrue(
            unit_may_edit_account(
                access=ACCESS_UNIT,
                login_account=_OWN,
                account_key="uid-own",
                groups=_GROUPS,
            )
        )
        self.assertFalse(
            unit_may_edit_account(
                access=ACCESS_UNIT,
                login_account=_OWN,
                account_key="uid-other",
                groups=_GROUPS,
            )
        )

    def test_unit_iban_spacing_does_not_matter(self):
        self.assertTrue(
            unit_may_edit_account(
                access=ACCESS_UNIT,
                login_account="NL00 BANK 0000000001",
                account_key=_OWN,
                groups=[],
            )
        )

    def test_other_logins_are_not_limited_to_one_account(self):
        for access in (ACCESS_PERSON, ACCESS_CENTER, ACCESS_COUNTRY):
            self.assertTrue(
                unit_may_edit_account(
                    access=access,
                    login_account="",
                    account_key="uid-other",
                    groups=_GROUPS,
                )
            )

    def test_unit_without_a_matching_account_is_refused(self):
        self.assertFalse(
            unit_may_edit_account(
                access=ACCESS_UNIT,
                login_account=_OWN,
                account_key="",
                groups=_GROUPS,
            )
        )
        self.assertFalse(
            unit_may_edit_account(
                access=ACCESS_UNIT,
                login_account="",
                account_key="uid-own",
                groups=_GROUPS,
            )
        )

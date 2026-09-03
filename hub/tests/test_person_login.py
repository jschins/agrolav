"""Person password hashing, formula fallback, OTP tokens."""
import unittest

from app.person_otp import encode_otp_token, issue_and_send, mask_phone, verify_otp_token
from app.user_store import (
    PASSWORD_PREFIX,
    credentials_match,
    default_password_hash,
    normalize_mobile_phone,
    password_for_username,
)
from shared.passwords import hash_password, verify_password


class CredentialsMatchTests(unittest.TestCase):
    def test_country_uses_formula_only(self):
        name = "nederland"
        self.assertTrue(
            credentials_match(
                password_for_username(name),
                username=name,
                is_person=False,
                password_hash=hash_password("other"),
            )
        )
        self.assertFalse(
            credentials_match(
                "other", username=name, is_person=False, password_hash=None
            )
        )

    def test_person_hash_wins_over_formula(self):
        name = "juleon_schins"
        stored = hash_password("secret-pass")
        self.assertTrue(
            credentials_match(
                "secret-pass", username=name, is_person=True, password_hash=stored
            )
        )
        self.assertFalse(
            credentials_match(
                password_for_username(name),
                username=name,
                is_person=True,
                password_hash=stored,
            )
        )

    def test_person_null_hash_falls_back_to_formula(self):
        name = "juleon_schins"
        self.assertTrue(
            credentials_match(
                password_for_username(name),
                username=name,
                is_person=True,
                password_hash=None,
            )
        )
        self.assertFalse(
            credentials_match("nope", username=name, is_person=True, password_hash=None)
        )

    def test_default_hash_verifies_formula(self):
        name = "someone"
        encoded = default_password_hash(name)
        self.assertTrue(verify_password(PASSWORD_PREFIX + name, encoded))


class MobilePhoneTests(unittest.TestCase):
    def test_empty_is_none(self):
        self.assertIsNone(normalize_mobile_phone(""))
        self.assertIsNone(normalize_mobile_phone("  "))

    def test_e164(self):
        self.assertEqual(normalize_mobile_phone("+31612345678"), "+31612345678")
        self.assertEqual(normalize_mobile_phone("+31 6 1234 5678"), "+31612345678")
        self.assertEqual(normalize_mobile_phone("0612345678"), "+31612345678")
        self.assertEqual(normalize_mobile_phone("0031612345678"), "+31612345678")

    def test_rejects_local(self):
        with self.assertRaises(ValueError):
            normalize_mobile_phone("12345")


class OtpTokenTests(unittest.TestCase):
    def test_roundtrip(self):
        token = encode_otp_token("juleon_schins", "123456")
        self.assertEqual(verify_otp_token(token, "123456"), "juleon_schins")
        self.assertIsNone(verify_otp_token(token, "000000"))

    def test_mask(self):
        hint = mask_phone("+31612345678")
        self.assertTrue(hint.startswith("+316"))
        self.assertTrue(hint.endswith("678"))
        self.assertNotIn("12345", hint)

    def test_unset_twilio_returns_dev_code(self):
        payload = issue_and_send("juleon_schins", "+31612345678")
        self.assertTrue(payload["otp_required"])
        self.assertTrue(payload["otp_token"])
        self.assertEqual(len(payload["dev_code"]), 6)
        self.assertTrue(payload["dev_code"].isdigit())

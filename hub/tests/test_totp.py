"""RFC 6238 SHA-1 vectors and the authenticator enrollment token."""
import time
import unittest

from app.person_otp import (
    enroll_from_token,
    encode_enroll_token,
    encode_login_token,
    generate_totp_secret,
    hotp,
    otpauth_uri,
    qr_data_uri,
    secret_groups,
    totp_matches,
    username_from_login_token,
)

_RFC_KEY = b"12345678901234567890"


class HotpVectorTests(unittest.TestCase):
    def test_rfc6238_sha1(self):
        vectors = (
            (59, "287082"),
            (1111111109, "081804"),
            (1111111111, "050471"),
            (1234567890, "005924"),
            (2000000000, "279037"),
        )
        for moment, code in vectors:
            step = moment // 30
            self.assertEqual(hotp(_RFC_KEY, step), code, moment)

    def test_window_accepts_one_step_either_side(self):
        secret = generate_totp_secret()
        moment = 1_111_111_111
        from app.person_otp import TOTP_STEP_SEC, _b32decode

        code = hotp(_b32decode(secret), moment // TOTP_STEP_SEC)
        self.assertTrue(totp_matches(secret, code, now=moment))
        self.assertTrue(totp_matches(secret, code, now=moment + 30))
        self.assertTrue(totp_matches(secret, code, now=moment - 30))
        self.assertFalse(totp_matches(secret, code, now=moment + 90))
        self.assertFalse(totp_matches(secret, "000000", now=moment))


class EnrollTokenTests(unittest.TestCase):
    def test_pending_secret_roundtrip(self):
        secret = generate_totp_secret()
        now = int(time.time())
        token = encode_enroll_token("juleon_schins", secret, now=now)
        self.assertEqual(enroll_from_token(token), ("juleon_schins", secret))
        login = encode_login_token("juleon_schins", now=now)
        self.assertIsNone(enroll_from_token(login))
        self.assertEqual(username_from_login_token(login), "juleon_schins")
        self.assertIsNone(username_from_login_token(token))

    def test_uri_and_groups(self):
        secret = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"
        uri = otpauth_uri("juleon_schins", secret)
        self.assertTrue(uri.startswith("otpauth://totp/Agrolav:juleon_schins?secret="))
        self.assertIn("issuer=Agrolav", uri)
        self.assertEqual(secret_groups(secret), "ABCD EFGH IJKL MNOP QRST UVWX YZ23 4567")
        image = qr_data_uri(uri)
        self.assertTrue(image.startswith("data:image/svg+xml"))

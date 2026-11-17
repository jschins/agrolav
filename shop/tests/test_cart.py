"""Cart cookie stores slug → copy count."""

from __future__ import annotations

import unittest

from app.cart import cart_size, dump_cart, load_cart


class CartCookieTests(unittest.TestCase):
    def test_round_trip_counts(self) -> None:
        secret = "test-secret"
        known = {"a", "b"}
        encoded = dump_cart({"a": 1, "b": 3}, secret)
        self.assertEqual(load_cart(encoded, secret, known), {"a": 1, "b": 3})
        self.assertEqual(cart_size({"a": 1, "b": 3}), 4)

    def test_legacy_slug_list_becomes_one_each(self) -> None:
        import base64
        import hashlib
        import hmac
        import json

        secret = "test-secret"
        known = {"a", "b"}
        body = base64.urlsafe_b64encode(json.dumps(["a", "b"]).encode()).decode().rstrip("=")
        sig = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
        self.assertEqual(load_cart(f"{body}.{sig}", secret, known), {"a": 1, "b": 1})


if __name__ == "__main__":
    unittest.main()

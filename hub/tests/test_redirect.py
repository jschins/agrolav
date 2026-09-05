import os
import unittest

from app.core import single_client

DEFAULT_REDIRECT = "https://deoudegracht.nl/banking-callback.html"


class RedirectUrlTests(unittest.TestCase):
    def _restore(self, old):
        if old is None:
            os.environ.pop("ENABLEBANKING_REDIRECT_URL", None)
        else:
            os.environ["ENABLEBANKING_REDIRECT_URL"] = old

    def test_default_redirect_points_to_hub_callback(self):
        old = os.environ.get("ENABLEBANKING_REDIRECT_URL")
        os.environ.pop("ENABLEBANKING_REDIRECT_URL", None)
        try:
            self.assertEqual(single_client.default_redirect_url(), DEFAULT_REDIRECT)
        finally:
            self._restore(old)

    def test_redirect_url_can_be_overridden_via_env(self):
        old = os.environ.get("ENABLEBANKING_REDIRECT_URL")
        os.environ["ENABLEBANKING_REDIRECT_URL"] = (
            "https://expenses.apsurt.nl/api/consent/callback"
        )
        try:
            self.assertEqual(
                single_client.default_redirect_url(),
                "https://expenses.apsurt.nl/api/consent/callback",
            )
        finally:
            self._restore(old)


if __name__ == "__main__":
    unittest.main()
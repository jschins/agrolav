import os
import unittest
from unittest import mock

from app.core import single_client


class RedirectUrlTests(unittest.TestCase):
    def test_default_redirect_points_to_hub_callback(self):
        with mock.patch(
            "app.core.single_client.app_config"
        ) as cfg:
            cfg.enablebanking_redirect_url.return_value = ""
            self.assertEqual(
                single_client.default_redirect_url(),
                "https://deoudegracht.nl/banking-callback.html",
            )

    def test_redirect_url_reads_app_config(self):
        with mock.patch(
            "app.core.single_client.app_config"
        ) as cfg:
            cfg.enablebanking_redirect_url.return_value = (
                "https://127.0.0.1:8200/api/consent/callback"
            )
            self.assertEqual(
                single_client.default_redirect_url(),
                "https://127.0.0.1:8200/api/consent/callback",
            )

    def test_redirect_url_can_be_overridden_via_env(self):
        old = os.environ.get("ENABLEBANKING_REDIRECT_URL")
        os.environ["ENABLEBANKING_REDIRECT_URL"] = "https://example.com/banking-callback"
        try:
            with mock.patch(
                "app.core.single_client.app_config"
            ) as cfg:
                cfg.enablebanking_redirect_url.return_value = (
                    "https://elsewhere.example/callback"
                )
                self.assertEqual(
                    single_client.default_redirect_url(),
                    "https://example.com/banking-callback",
                )
        finally:
            if old is None:
                os.environ.pop("ENABLEBANKING_REDIRECT_URL", None)
            else:
                os.environ["ENABLEBANKING_REDIRECT_URL"] = old


if __name__ == "__main__":
    unittest.main()
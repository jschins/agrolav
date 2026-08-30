import os
import unittest
from unittest import mock

from app.core import single_client


class RedirectUrlTests(unittest.TestCase):
    def test_default_redirect_points_to_hub_callback(self):
        with mock.patch(
            "app.core.single_client.app_config"
        ) as cfg:
            cfg.running_on_server.return_value = False
            cfg.enablebanking_redirect_url.return_value = ""
            self.assertEqual(
                single_client.default_redirect_url(),
                "https://deoudegracht.nl/banking-callback.html",
            )

    def test_redirect_url_reads_app_config(self):
        with mock.patch(
            "app.core.single_client.app_config"
        ) as cfg:
            cfg.running_on_server.return_value = False
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
                cfg.running_on_server.return_value = False
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

    def test_server_mode_db_row_wins_over_env(self):
        old = os.environ.get("ENABLEBANKING_REDIRECT_URL")
        os.environ["ENABLEBANKING_REDIRECT_URL"] = "https://env.example/callback"
        try:
            with mock.patch(
                "app.core.single_client.app_config"
            ) as cfg:
                cfg.running_on_server.return_value = True
                cfg.enablebanking_redirect_url.return_value = (
                    "https://db.example/callback"
                )
                self.assertEqual(
                    single_client.default_redirect_url(),
                    "https://db.example/callback",
                )
        finally:
            if old is None:
                os.environ.pop("ENABLEBANKING_REDIRECT_URL", None)
            else:
                os.environ["ENABLEBANKING_REDIRECT_URL"] = old


if __name__ == "__main__":
    unittest.main()
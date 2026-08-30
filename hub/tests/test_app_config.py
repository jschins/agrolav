import os
import unittest
from unittest import mock

from app import app_config

ROWS = {
    "PRODUCTION_ENABLEBANKING_REDIRECT_URL": "https://boekhouding.agrolav.nl/api/consent/callback",
    "LOCAL_ENABLEBANKING_REDIRECT_URL": "https://127.0.0.1:8200/api/consent/callback",
}


class AppConfigEnvironmentTests(unittest.TestCase):
    def tearDown(self):
        app_config.reset_cache()

    def test_environment_defaults_to_local(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            self.assertEqual(app_config.environment(), "local")

    def test_environment_ignores_legacy_data_root_env(self):
        env = {"BOEKHOUDING_DATA_ROOT": "/opt/agrolav/data"}
        with mock.patch.dict(os.environ, env, clear=False):
            self.assertEqual(app_config.environment(), "local")

    def test_environment_explicit_hub_env(self):
        env = {"HUB_ENV": "production"}
        with mock.patch.dict(os.environ, env, clear=False):
            self.assertEqual(app_config.environment(), "production")


class AppConfigRedirectTests(unittest.TestCase):
    def tearDown(self):
        app_config.reset_cache()

    def test_local_redirect_read_from_field_name(self):
        with mock.patch.object(app_config, "load", return_value=ROWS):
            self.assertEqual(
                app_config.enablebanking_redirect_url(),
                ROWS["LOCAL_ENABLEBANKING_REDIRECT_URL"],
            )

    def test_local_wins_over_production_row(self):
        rows = {
            "PRODUCTION_ENABLEBANKING_REDIRECT_URL": "https://production.example/callback",
            "LOCAL_ENABLEBANKING_REDIRECT_URL": "https://local.example/callback",
        }
        with mock.patch.object(app_config, "load", return_value=rows):
            self.assertEqual(
                app_config.enablebanking_redirect_url(),
                "https://local.example/callback",
            )

    def test_production_row_used_when_local_missing(self):
        rows = {
            "PRODUCTION_ENABLEBANKING_REDIRECT_URL": "https://production.example/callback",
        }
        with mock.patch.object(app_config, "load", return_value=rows):
            self.assertEqual(
                app_config.enablebanking_redirect_url(),
                "https://production.example/callback",
            )

    def test_run_on_server_flag_false_by_default(self):
        with mock.patch.object(app_config, "load", return_value={}):
            self.assertFalse(app_config.running_on_server())

    def test_run_on_server_flag_true_when_row_set(self):
        for raw in ("True", "true", "1", "yes", "on"):
            with mock.patch.object(app_config, "load", return_value={"RUN_ON_SERVER": raw}):
                self.assertTrue(app_config.running_on_server(), raw)

    def test_run_on_server_uses_production_row(self):
        rows = {
            "PRODUCTION_ENABLEBANKING_REDIRECT_URL": "https://production.example/callback",
            "LOCAL_ENABLEBANKING_REDIRECT_URL": "https://local.example/callback",
        }
        with mock.patch.object(app_config, "load", return_value={**rows, "RUN_ON_SERVER": "True"}):
            self.assertEqual(
                app_config.enablebanking_redirect_url(),
                "https://production.example/callback",
            )
            self.assertEqual(app_config.environment(), "production")

    def test_local_mode_uses_local_row(self):
        rows = {
            "PRODUCTION_ENABLEBANKING_REDIRECT_URL": "https://production.example/callback",
            "LOCAL_ENABLEBANKING_REDIRECT_URL": "https://local.example/callback",
        }
        with mock.patch.object(app_config, "load", return_value=rows):
            self.assertEqual(
                app_config.enablebanking_redirect_url(),
                "https://local.example/callback",
            )
            self.assertEqual(app_config.environment(), "local")

    def test_returns_empty_when_no_rows(self):
        with mock.patch.object(app_config, "load", return_value={}):
            self.assertEqual(app_config.enablebanking_redirect_url(), "")

    def test_get_returns_default_for_unknown_key(self):
        self.assertEqual(app_config.get("NO_SUCH_KEY", "fallback"), "fallback")


class AppConfigPublicUrlTests(unittest.TestCase):
    def tearDown(self):
        app_config.reset_cache()

    def test_public_urls_empty_in_local_mode(self):
        rows = {
            "PUBLIC_HUB_URL": "https://expenses.apsurt.nl",
            "PUBLIC_CLIENT_URL": "https://expenses.apsurt.nl",
        }
        with mock.patch.object(app_config, "load", return_value=rows):
            self.assertEqual(app_config.public_hub_url(), "")
            self.assertEqual(app_config.public_client_url(), "")

    def test_public_urls_from_rows_on_server(self):
        rows = {
            "RUN_ON_SERVER": "True",
            "PUBLIC_HUB_URL": "https://hub.example",
            "PUBLIC_CLIENT_URL": "https://client.example",
        }
        with mock.patch.object(app_config, "load", return_value=rows):
            self.assertEqual(app_config.public_hub_url(), "https://hub.example")
            self.assertEqual(app_config.public_client_url(), "https://client.example")

    def test_public_urls_empty_when_rows_missing_even_on_server(self):
        with mock.patch.object(app_config, "load", return_value={"RUN_ON_SERVER": "True"}):
            self.assertEqual(app_config.public_hub_url(), "")
            self.assertEqual(app_config.public_client_url(), "")


if __name__ == "__main__":
    unittest.main()
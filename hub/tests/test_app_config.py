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

    def test_returns_empty_when_no_rows(self):
        with mock.patch.object(app_config, "load", return_value={}):
            self.assertEqual(app_config.enablebanking_redirect_url(), "")

    def test_get_returns_default_for_unknown_key(self):
        self.assertEqual(app_config.get("NO_SUCH_KEY", "fallback"), "fallback")


if __name__ == "__main__":
    unittest.main()
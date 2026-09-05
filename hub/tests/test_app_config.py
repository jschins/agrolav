import os
import unittest
from unittest import mock

from app import app_config


class AppConfigApiKeyTests(unittest.TestCase):
    def tearDown(self):
        app_config.reset_cache()

    def test_key_from_env_when_no_row(self):
        with mock.patch.dict(os.environ, {"CENTRALE_API_KEY": "env-secret"}):
            self.assertEqual(app_config.centrale_api_key(), "env-secret")

    def test_key_empty_when_no_row_and_no_env(self):
        with mock.patch.dict(os.environ, {"CENTRALE_API_KEY": ""}):
            self.assertEqual(app_config.centrale_api_key(), "")

    def test_non_empty_row_overrides_env(self):
        with mock.patch.object(
            app_config,
            "load",
            return_value={"CENTRALE_API_KEY": "row-secret"},
        ), mock.patch.dict(os.environ, {"CENTRALE_API_KEY": "env-secret"}):
            self.assertEqual(app_config.centrale_api_key(), "row-secret")

    def test_blank_row_keeps_env(self):
        with mock.patch.object(
            app_config,
            "load",
            return_value={"CENTRALE_API_KEY": ""},
        ), mock.patch.dict(os.environ, {"CENTRALE_API_KEY": "env-secret"}):
            self.assertEqual(app_config.centrale_api_key(), "env-secret")


class AppConfigGetTests(unittest.TestCase):
    def tearDown(self):
        app_config.reset_cache()

    def test_get_returns_default_for_unknown_key(self):
        self.assertEqual(app_config.get("NO_SUCH_KEY", "fallback"), "fallback")


if __name__ == "__main__":
    unittest.main()
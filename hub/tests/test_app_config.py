import os
import unittest
from unittest import mock

from app import app_config


class AppConfigApiKeyTests(unittest.TestCase):
    def test_key_from_env(self):
        with mock.patch.dict(os.environ, {"CENTRALE_API_KEY": "env-secret"}):
            self.assertEqual(app_config.centrale_api_key(), "env-secret")

    def test_key_empty_when_no_env(self):
        with mock.patch.dict(os.environ, {"CENTRALE_API_KEY": ""}):
            self.assertEqual(app_config.centrale_api_key(), "")


if __name__ == "__main__":
    unittest.main()


if __name__ == "__main__":
    unittest.main()
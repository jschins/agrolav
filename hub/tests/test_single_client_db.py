"""DB-first profile/consent behaviour in single_client (no SQL round-trips)."""
import unittest
from unittest import mock

from app.core import single_client


def _db_enabled():
    return mock.patch("app.user_store.database_url", return_value="sql://hub")


class DbCountryIsoTests(unittest.TestCase):
    def test_maps_known_countries(self):
        cases = {
            "nederland": "NL",
            "netherlands": "NL",
            "united_kingdom": "GB",
            "uk": "GB",
            "gb": "GB",
            "ireland": "IE",
            "beheer": "NL",
        }
        for raw, expected in cases.items():
            with mock.patch.object(single_client.paths, "BOUND_COUNTRY", raw):
                self.assertEqual(single_client._db_country_iso(), expected)

    def test_two_letter_is_passthrough(self):
        with mock.patch.object(single_client.paths, "BOUND_COUNTRY", "ie"):
            self.assertEqual(single_client._db_country_iso(), "IE")

    def test_unknown_falls_back_to_nl(self):
        with mock.patch.object(single_client.paths, "BOUND_COUNTRY", "atlantis"):
            self.assertEqual(single_client._db_country_iso(), "NL")


class LoadProfileDbTests(unittest.TestCase):
    def test_profile_built_from_sql_when_configured(self):
        with _db_enabled(), mock.patch.object(
            single_client.paths, "BOUND_PERSON", "janpiet"
        ), mock.patch.object(
            single_client.paths, "BOUND_COUNTRY", ""
        ), mock.patch(
            "app.enable_sql.credentials_for_person",
            return_value=("APPLICATION_ID", "-----BEGIN PRIVATE KEY-----"),
        ), mock.patch(
            "app.enable_sql.person_country_username", return_value="nederland"
        ), mock.patch(
            "app.enable_sql.person_aspsp", return_value="ING"
        ):
            profile = single_client.load_profile()
        self.assertEqual(profile["person"], "janpiet")
        self.assertEqual(profile["connections"][0]["app_id"], "APPLICATION_ID")
        self.assertEqual(profile["connections"][0]["country"], "NL")
        self.assertEqual(profile["connections"][0]["aspsp"], "ING")

    def test_aspsp_from_account_format(self):
        with _db_enabled(), mock.patch.object(
            single_client.paths, "BOUND_PERSON", "janpiet"
        ), mock.patch(
            "app.enable_sql.credentials_for_person",
            return_value=("APP2", "KEY"),
        ), mock.patch(
            "app.enable_sql.person_country_username", return_value="nederland"
        ), mock.patch(
            "app.enable_sql.person_aspsp", return_value="Revolut"
        ):
            profile = single_client.load_profile()
        self.assertEqual(profile["connections"][0]["aspsp"], "Revolut")

    def test_country_iso_prefers_sql_over_bound(self):
        with _db_enabled(), mock.patch.object(
            single_client.paths, "BOUND_PERSON", "janpiet"
        ), mock.patch.object(
            single_client.paths, "BOUND_COUNTRY", "nederland"
        ), mock.patch(
            "app.enable_sql.person_country_username", return_value="united_kingdom"
        ):
            self.assertEqual(single_client._db_country_iso(), "GB")

    def test_country_iso_sql_missing_falls_back_to_bound(self):
        with _db_enabled(), mock.patch.object(
            single_client.paths, "BOUND_COUNTRY", "ireland"
        ), mock.patch(
            "app.enable_sql.person_country_username", return_value=""
        ):
            self.assertEqual(single_client._db_country_iso(), "IE")

    def test_no_database_falls_back_to_legacy(self):
        with mock.patch("app.user_store.database_url", return_value=""), mock.patch.object(
            single_client.paths, "BOUND_PERSON", ""
        ), mock.patch.object(
            single_client.paths, "BOUND_COUNTRY", ""
        ):
            with self.assertRaises(Exception):
                single_client.load_profile()


class SaveConsentDbTests(unittest.TestCase):
    def setUp(self):
        self.update = mock.MagicMock()
        self.upsert = mock.MagicMock()
        self.cm_update = mock.patch(
            "app.enable_sql.update_person_connection", self.update
        )
        self.cm_upsert = mock.patch(
            "app.enable_sql.upsert_person_accounts", self.upsert
        )
        self.cm_db = _db_enabled()
        self.cm_person = mock.patch.object(single_client.paths, "BOUND_PERSON", "janpiet")
        self.cm_country = mock.patch.object(single_client.paths, "BOUND_COUNTRY", "nederland")
        self.cm_db.start()
        self.cm_person.start()
        self.cm_country.start()
        self.cm_update.start()
        self.cm_upsert.start()

    def tearDown(self):
        self.cm_upsert.stop()
        self.cm_update.stop()
        self.cm_country.stop()
        self.cm_person.stop()
        self.cm_db.stop()

    def test_session_saved_to_database(self):
        record = {
            "person": "janpiet",
            "connections": [
                {
                    "app_id": "APP",
                    "aspsp": "ING",
                    "country": "NL",
                    "session_id": "session-1",
                    "valid_until": "2099-01-01",
                    "created_at": "2026-01-01",
                    "accounts": [
                        {
                            "uid": "acc-1",
                            "iban": "NL00BANK0123456789",
                            "name": "Betaalrekening",
                            "balance": "12.34",
                            "balance_currency": "EUR",
                            "enabled": True,
                        }
                    ],
                }
            ],
        }
        single_client._save_consent(record)
        self.update.assert_called_once()
        self.assertEqual(self.update.call_args[0][0], "janpiet")
        self.upsert.assert_called_once()
        accounts = self.upsert.call_args[0][1]
        self.assertEqual(accounts[0]["uid"], "acc-1")

    def test_redirect_meta_without_session_does_not_touch_database(self):
        record = {
            "person": "janpiet",
            "connections": [
                {
                    "app_id": "APP",
                    "aspsp": "ING",
                    "country": "NL",
                    "accounts": [],
                }
            ],
            "last_redirect_code": "abc123",
        }
        single_client._save_consent(record)
        self.update.assert_not_called()
        self.upsert.assert_not_called()


if __name__ == "__main__":
    unittest.main()
"""consent_flow: pending survives hub restart via SQL best-effort persistence."""
import unittest
from unittest import mock

from app import consent_flow


def _reset() -> None:
    consent_flow._pending.clear()
    consent_flow._ready.clear()


class RegisterPendingPersistenceTests(unittest.TestCase):
    def tearDown(self) -> None:
        _reset()

    def test_register_persists_to_sql(self):
        with mock.patch("app.enable_sql.upsert_consent_pending") as upsert:
            token = consent_flow.register_pending(
                center="ws1", person_name="janpiet", state="abc"
            )
        self.assertEqual(token, "abc")
        upsert.assert_called_once_with(
            "abc", center="ws1", person_name="janpiet"
        )

    def test_register_generates_token_when_no_state(self):
        with mock.patch("app.enable_sql.upsert_consent_pending") as upsert:
            token = consent_flow.register_pending(center="ws1", person_name="x")
        self.assertTrue(token)
        upsert.assert_called_once()
        self.assertEqual(upsert.call_args[0][0], token)

    def test_db_failure_does_not_break_memory_flow(self):
        with mock.patch(
            "app.enable_sql.upsert_consent_pending",
            side_effect=RuntimeError("db down"),
        ):
            token = consent_flow.register_pending(center="ws1", person_name="janpiet")
        item = consent_flow.take_pending(token)
        self.assertEqual(item and item["person_name"], "janpiet")


class TakePendingPersistenceTests(unittest.TestCase):
    def tearDown(self) -> None:
        _reset()

    def test_memory_hit_also_cleans_sql_row(self):
        with mock.patch("app.enable_sql.upsert_consent_pending"), mock.patch(
            "app.enable_sql.delete_consent_pending"
        ) as delete:
            token = consent_flow.register_pending(
                center="ws1", person_name="janpiet", state="abc"
            )
            item = consent_flow.take_pending("abc")
        self.assertEqual(item and item["person_name"], "janpiet")
        delete.assert_called_once_with("abc")

    def test_memory_miss_falls_back_to_sql(self):
        db_row = {"center": "ws1", "person_name": "janpiet"}
        with mock.patch(
            "app.enable_sql.take_consent_pending", return_value=dict(db_row)
        ):
            item = consent_flow.take_pending("abc")
        self.assertEqual(item and item["center"], "ws1")
        self.assertEqual(item and item["person_name"], "janpiet")
        self.assertIn("created", item or {})

    def test_memory_and_sql_miss_return_none(self):
        with mock.patch("app.enable_sql.take_consent_pending", return_value=None):
            self.assertIsNone(consent_flow.take_pending("unknown"))

    def test_sql_read_failure_returns_none(self):
        with mock.patch(
            "app.enable_sql.take_consent_pending",
            side_effect=RuntimeError("db down"),
        ):
            self.assertIsNone(consent_flow.take_pending("unknown"))


class ReadyFlowUnchangedTests(unittest.TestCase):
    def tearDown(self) -> None:
        _reset()

    def test_mark_and_list_ready(self):
        consent_flow.mark_ready(center="ws1", person_name="janpiet")
        ready = consent_flow.list_ready("ws1")
        self.assertEqual([x["person_name"] for x in ready], ["janpiet"])
        self.assertTrue(
            consent_flow.clear_ready(center="ws1", person_name="janpiet")
        )
        self.assertEqual(consent_flow.list_ready("ws1"), [])


if __name__ == "__main__":
    unittest.main()
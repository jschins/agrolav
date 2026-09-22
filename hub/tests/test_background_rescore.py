"""Right-click term adds rescore on a background thread and collapse a burst."""
import threading
import time
import unittest
from unittest.mock import patch

from app import store
from app.core import categorize


def _job(center: str, term: str, *, personal: bool, account: str | None, general: bool = False) -> dict:
    return {
        "center": center,
        "input_paths": ["categories.json"] if general else [f"{center}/secret/personal_categories.json"],
        "source": "local",
        "recalc_all_centers": general,
        "added": [term],
        "removed": [],
        "personal": personal,
        "category_name": "3110 Kosten",
        "account": account,
    }


class MergeRescoreJobTests(unittest.TestCase):
    def test_two_accounts_keep_the_person_and_drop_the_account_filter(self):
        merged = store._merge_rescore_job(
            _job("dkg", "alpha", personal=True, account="acc-a"),
            _job("dkg", "beta", personal=True, account="acc-b"),
        )
        self.assertEqual(merged["added"], ["alpha", "beta"])
        self.assertTrue(merged["personal"])
        self.assertIsNone(merged["account"])
        self.assertFalse(merged["recalc_all_centers"])

    def test_a_general_term_widens_the_pass_to_every_center(self):
        merged = store._merge_rescore_job(
            _job("dkg", "alpha", personal=True, account="acc-a"),
            _job("dkg", "beta", personal=False, account=None, general=True),
        )
        self.assertFalse(merged["personal"])
        self.assertTrue(merged["recalc_all_centers"])
        self.assertIsNone(merged["account"])


class BackgroundScheduleTests(unittest.TestCase):
    def setUp(self):
        self.release = threading.Event()
        store._rescore_running = False
        store._rescore_again = False
        store._rescore_job = None

    def tearDown(self):
        self.release.set()
        for _ in range(50):
            if not store._rescore_running:
                break
            time.sleep(0.02)
        store._rescore_running = False
        store._rescore_again = False
        store._rescore_job = None

    def test_queueing_a_term_does_not_start_a_pass(self):
        with patch.object(store, "_run_scheduled_rescore") as run:
            store.schedule_background_ircft(
                "dkg",
                ["categories.json"],
                added=["one"],
                removed=[],
                personal=False,
                category_name="3110 Kosten",
                recalc_all_centers=True,
            )
            time.sleep(0.05)
        run.assert_not_called()
        self.assertFalse(store._rescore_running)

    def test_a_term_saved_during_the_pass_schedules_one_follow_up(self):
        started = threading.Event()
        calls: list[list[str]] = []

        def run(job):
            calls.append(list(job["added"]))
            if len(calls) == 1:
                started.set()
                self.release.wait(2)

        with patch.object(store, "_run_scheduled_rescore", side_effect=run):
            store.schedule_background_ircft(
                "dkg",
                ["categories.json"],
                added=["one"],
                removed=[],
                personal=False,
                category_name="3110 Kosten",
                recalc_all_centers=True,
            )
            flushed = threading.Thread(target=store.flush_scheduled_rescore)
            flushed.start()
            self.assertTrue(started.wait(2))
            store.schedule_background_ircft(
                "dkg",
                ["categories.json"],
                added=["two"],
                removed=[],
                personal=False,
                category_name="3110 Kosten",
                recalc_all_centers=True,
            )
            self.release.set()
            flushed.join(2)

        self.assertEqual(calls, [["one"], ["two"]])
        self.assertFalse(store._rescore_running)


class ApplyIrcftOnceTests(unittest.TestCase):
    def test_several_added_terms_walk_the_rows_once(self):
        with (
            patch.object(categorize, "_categories_file", return_value={}),
            patch.object(categorize, "_category_map", return_value={}),
            patch.object(categorize, "_personal_category_map", return_value={}),
            patch.object(categorize, "_account_modality", return_value=False),
            patch.object(categorize, "ircft_remove_term", return_value=True) as removed,
            patch.object(categorize, "ircft_add_term", return_value=True) as added,
        ):
            categorize.apply_ircft_terms(
                added=["alpha", "beta"],
                removed=["gone"],
                personal=False,
                category_name="3110 Kosten",
            )
        self.assertEqual(removed.call_count, 1)
        self.assertEqual(added.call_count, 1)
        self.assertEqual(added.call_args.args[0], "alpha")

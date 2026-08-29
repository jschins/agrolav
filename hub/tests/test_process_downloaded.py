"""matrix.process_downloaded_file: fixed agrolav-sql file -> transaction_{country}."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app import matrix, runtime, user_store


class _Pack:
    person_name = "juleon_schins"
    folder = Path("nul")
    data_dir = Path("data")
    secret_dir = Path("data") / "secret"
    profile_path = Path("data") / "profile.json"
    private_key_path = Path("data") / "key.pem"
    year = "2026"
    country = "nederland"
    center = "dkg"


def _write_downloaded(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


class ProcessDownloadedFileTests(unittest.TestCase):
    def test_reads_file_and_runs_machinery_for_person(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "downloaded_transactions.json"
            raw = [{"id": "x1", "amount": "-1.00", "date": "2026-01-02"}]
            _write_downloaded(target, raw)
            pack = _Pack()
            with mock.patch("app.matrix.get_person", return_value=pack), mock.patch(
                "app.matrix.bind_person"
            ) as bind, mock.patch(
                "app.core.single_client.downloaded_transactions_target",
                return_value=target,
            ), mock.patch(
                "app.core.categorize.process_transactions", return_value={"12": "5.00"}
            ) as proc, mock.patch(
                "app.matrix._downloaded_sql_row_count", return_value=7
            ), mock.patch(
                "app.matrix._write_categorized_inspection"
            ) as inspection:
                stats = matrix.process_downloaded_file("juleon_schins")
        self.assertEqual(stats["person_name"], "juleon_schins")
        self.assertEqual(stats["source"], "downloaded-file")
        self.assertEqual(stats["raw_count"], 1)
        self.assertEqual(stats["transaction_rows"], 7)
        self.assertEqual(stats["totals"], {"12": "5.00"})
        proc.assert_called_once_with(raw, new_year=False)
        bind.assert_called_once_with(pack)
        inspection.assert_called_once_with(
            target, pack=pack, records=raw, totals={"12": "5.00"}, rows=7
        )

    def test_forwards_new_year(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "downloaded_transactions.json"
            _write_downloaded(target, [])
            with mock.patch("app.matrix.get_person", return_value=_Pack()), mock.patch(
                "app.matrix.bind_person"
            ), mock.patch(
                "app.core.single_client.downloaded_transactions_target",
                return_value=target,
            ), mock.patch(
                "app.core.categorize.process_transactions"
            ) as proc, mock.patch(
                "app.matrix._downloaded_sql_row_count", return_value=0
            ), mock.patch("app.matrix._write_categorized_inspection"):
                matrix.process_downloaded_file("juleon_schins", new_year=True)
        proc.assert_called_once_with([], new_year=True)

    def test_raises_when_file_missing(self):
        pack = _Pack()
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "nope.json"
            with mock.patch("app.matrix.get_person", return_value=pack), mock.patch(
                "app.core.single_client.downloaded_transactions_target",
                return_value=target,
            ):
                with self.assertRaises(Exception) as ctx:
                    matrix.process_downloaded_file("juleon_schins")
        self.assertIn("No downloaded_transactions.json", str(ctx.exception))

    def test_raises_when_not_a_list(self):
        pack = _Pack()
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "downloaded_transactions.json"
            _write_downloaded(target, {"transactions": []})
            with mock.patch("app.matrix.get_person", return_value=pack), mock.patch(
                "app.core.single_client.downloaded_transactions_target",
                return_value=target,
            ):
                with self.assertRaises(Exception) as ctx:
                    matrix.process_downloaded_file("juleon_schins")
        self.assertIn("JSON list", str(ctx.exception))


class ProcessDownloadedAfterFetchTests(unittest.TestCase):
    def test_bank_result_processes_file(self):
        result = {"person_name": "juleon_schins", "skipped": False, "source": "bank"}
        processed = {"raw_count": 1, "transaction_rows": 3}
        with mock.patch(
            "app.matrix.process_downloaded_file", return_value=processed
        ) as proc:
            out = matrix._process_downloaded_after_fetch(person_name="juleon_schins", result=result, extra=[])
        self.assertEqual(out["downloaded"], processed)
        proc.assert_called_once_with("juleon_schins", new_year=False)

    def test_skipped_person_not_processed(self):
        result = {"person_name": "x", "skipped": True, "source": "bank"}
        with mock.patch("app.matrix.process_downloaded_file") as proc:
            out = matrix._process_downloaded_after_fetch(person_name="x", result=result, extra=[])
        self.assertIs(out, result)
        proc.assert_not_called()

    def test_non_bank_source_not_processed(self):
        result = {"person_name": "x", "skipped": False, "source": "files"}
        with mock.patch("app.matrix.process_downloaded_file") as proc:
            out = matrix._process_downloaded_after_fetch(person_name="x", result=result, extra=[])
        self.assertIs(out, result)
        proc.assert_not_called()

    def test_failed_processing_becomes_warning(self):
        result = {"person_name": "x", "skipped": False, "source": "bank"}
        extra: list[str] = []
        with mock.patch(
            "app.matrix.process_downloaded_file",
            side_effect=RuntimeError("boom"),
        ):
            out = matrix._process_downloaded_after_fetch(person_name="x", result=result, extra=extra)
        self.assertIs(out, result)
        self.assertNotIn("downloaded", out)
        self.assertTrue(any("downloaded file processing failed" in w for w in extra))


class _FakeCursor:
    def __init__(self, results):
        self._results = list(results)
        self.executed: list[tuple] = []

    def execute(self, sql, params=()):
        self.executed.append((sql, params))

    def fetchone(self):
        return self._results.pop(0) if self._results else None


class _FakeConn:
    def __init__(self, results):
        self._cursor = _FakeCursor(results)
        self.closed = False

    def cursor(self):
        return self._cursor

    def close(self):
        self.closed = True


class CategorizedInspectionTests(unittest.TestCase):
    def test_writes_categorized_json_beside_downloaded_file(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "downloaded_transactions.json"
            out = matrix._write_categorized_inspection(
                target,
                pack=_Pack(),
                records=[{"id": "x1"}],
                totals={"12": "5.00"},
                rows=7,
            )
            self.assertEqual(out, Path(td) / "categorized_transactions.json")
            payload = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(payload["person"], "juleon_schins")
        self.assertEqual(payload["center"], "dkg")
        self.assertEqual(payload["country"], "nederland")
        self.assertEqual(payload["table"], "dbo.transaction_nederland")
        self.assertEqual(payload["raw_count"], 1)
        self.assertEqual(payload["transaction_rows"], 7)
        self.assertEqual(payload["totals"], {"12": "5.00"})

    def test_writes_basic_fields_without_sql_rows(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "downloaded_transactions.json"
            out = matrix._write_categorized_inspection(
                target,
                pack=_Pack(),
                records=[],
                totals={},
                rows=None,
            )
            payload = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(payload["transaction_rows"], None)
        self.assertEqual(payload["transactions"], [])
        self.assertEqual(payload["table"], "dbo.transaction_nederland")


class DownloadedSqlRowCountTests(unittest.TestCase):
    def test_counts_transactions_for_bound_person(self):
        conn = _FakeConn([(42,), (5,)])
        with mock.patch.object(user_store, "database_url", return_value=True), mock.patch(
            "app.user_store.init_user_store"
        ), mock.patch.object(user_store, "_sql_connect", return_value=conn), mock.patch.object(
            runtime, "BOUND_COUNTRY", "nederland"
        ), mock.patch.object(
            runtime, "BOUND_PERSON", "juleon_schins"
        ), mock.patch.object(
            runtime, "BOUND_YEAR", 2026
        ):
            count = matrix._downloaded_sql_row_count()
        self.assertEqual(count, 5)
        self.assertFalse(conn.closed)  # thread-shared connection: never close it
        params = [params for _sql, params in conn._cursor.executed]
        self.assertEqual(params[0], ("juleon_schins",))
        self.assertEqual(params[1], (42, 2026))

    def test_returns_none_without_sql(self):
        with mock.patch.object(user_store, "database_url", return_value=False):
            self.assertIsNone(matrix._downloaded_sql_row_count())


if __name__ == "__main__":
    unittest.main()
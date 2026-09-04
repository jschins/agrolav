"""Live path is SQL: people, categorized persist, and uploads without pack folders."""
from __future__ import annotations

import asyncio
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest import mock

from starlette.datastructures import Headers, UploadFile
from starlette.requests import Request

NATWEST_CSV = (
    "Date,Type,Description,Value,Balance,Account Name,Account Number\n"
    "14 Aug 2026,DPC,GROCERIES,-12.50,100.00,Jan Piet,12345678\n"
).encode("utf-8")


def _http_request(path: str, query: str = "") -> Request:
    return Request(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": query.encode(),
            "headers": [],
            "client": ("127.0.0.1", 123),
            "server": ("testserver", 80),
        }
    )


def _layout_dirs(root: Path) -> list[str]:
    return sorted(
        str(path.relative_to(root)).replace("\\", "/")
        for path in root.rglob("*")
        if path.is_dir()
    )


class PeopleFromSqlTests(unittest.TestCase):
    def test_list_people_is_sql_identity_without_paths(self):
        from app.people import list_people

        with mock.patch("app.people.active_center", return_value="dkg"), mock.patch(
            "app.people.active_country", return_value="nederland"
        ), mock.patch(
            "app.people.country_folder", side_effect=lambda name: (name or "").strip()
        ), mock.patch(
            "app.people.country_for_center", return_value="nederland"
        ), mock.patch(
            "app.people.people_in_center", return_value=["janpiet"]
        ), mock.patch(
            "app.people.years_by_person_in_center",
            return_value={"janpiet": ["2026"]},
        ):
            packs = list_people()
        self.assertEqual([pack.person for pack in packs], ["janpiet"])
        pack = packs[0]
        self.assertEqual(pack.country, "nederland")
        self.assertEqual(pack.center, "dkg")
        self.assertEqual(pack.year, "2026")
        self.assertIsNone(pack.account)
        self.assertFalse(hasattr(pack, "folder"))
        self.assertFalse(hasattr(pack, "data_dir"))

    def test_bind_scope_sets_account_not_paths(self):
        from app.runtime import PersonScope, bind_scope
        from app import runtime as paths

        pack = PersonScope(
            country="nederland",
            center="dkg",
            person="janpiet",
            year="2026",
            account="NL00TEST0123456789",
        )
        with bind_scope(pack):
            self.assertEqual(paths.BOUND_COUNTRY, "nederland")
            self.assertEqual(paths.BOUND_CENTER, "dkg")
            self.assertEqual(paths.BOUND_PERSON, "janpiet")
            self.assertEqual(paths.BOUND_YEAR, 2026)
            self.assertEqual(paths.BOUND_ACCOUNT, "NL00TEST0123456789")
            self.assertFalse(hasattr(paths, "PERSON_NAME"))
            self.assertFalse(hasattr(paths, "DATA_DIR"))


class CategorizedSqlPersistTests(unittest.TestCase):
    def test_persist_writes_sql_not_json(self):
        from app.core import categorize

        synced: list[dict] = []
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            json_path = (
                root / "nederland" / "dkg" / "janpiet" / "2026" / "categorized_transactions.json"
            )
            with mock.patch(
                "app.sql_replica.sync_bound_transactions",
                side_effect=lambda txs: synced.extend(txs),
            ):
                categorize._persist_categorized_store(
                    {
                        "transactions": [
                            {
                                "id": "jan_2_0",
                                "amount": "-12.50",
                                "date": "14-08-2026",
                                "category": 18,
                            }
                        ]
                    }
                )
            self.assertEqual(len(synced), 1)
            self.assertEqual(synced[0]["id"], "jan_2_0")
            self.assertFalse(json_path.exists())
            self.assertEqual(_layout_dirs(root), [])


class ExcelWriteOutputsTests(unittest.TestCase):
    def test_write_outputs_does_not_mkdir_pack_tree(self):
        from app.core import excel_import

        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "nederland" / "dkg" / "janpiet" / "2026"
            with self.assertRaises(FileNotFoundError):
                excel_import.write_outputs(missing, categories_path=missing.parent / "categories.json")
            self.assertFalse(missing.exists())
            self.assertEqual(_layout_dirs(Path(tmp)), [])


class AccountBalanceFileTests(unittest.TestCase):
    def test_list_reads_sql_rows(self):
        from app import sql_catalog

        cursor = mock.Mock()
        cursor.fetchall.return_value = [("jan.csv", "natwest-csv"), ("old.xlsx", "excel")]
        with mock.patch.object(sql_catalog, "_sql_ready", return_value=True), mock.patch.object(
            sql_catalog, "_sql_retry", side_effect=lambda fn: fn()
        ), mock.patch.object(sql_catalog, "_cursor", return_value=cursor):
            files = sql_catalog.list_uploaded_files("janpiet")
        self.assertEqual(
            files,
            [
                {"file_name": "jan.csv", "format": "natwest-csv"},
                {"file_name": "old.xlsx", "format": "excel"},
            ],
        )
        cursor.execute.assert_called_once()
        self.assertIn("uploaded_files", cursor.execute.call_args[0][0])

    def test_record_inserts_when_filename_is_new(self):
        from app import sql_catalog

        cursor = mock.Mock()
        cursor.fetchone.side_effect = [(7,), (3,), None]
        conn = mock.Mock()
        with mock.patch.object(sql_catalog, "_sql_ready", return_value=True), mock.patch.object(
            sql_catalog, "_sql_retry", side_effect=lambda fn: fn()
        ), mock.patch.object(sql_catalog, "_cursor", return_value=cursor), mock.patch(
            "app.user_store._sql_connect", return_value=conn
        ):
            sql_catalog.record_uploaded_file("janpiet", "jan.csv", "natwest-csv")
        insert_sql = cursor.execute.call_args_list[-1][0][0]
        self.assertIn("INSERT INTO dbo.uploaded_files", insert_sql)
        conn.commit.assert_called_once()


class WipeCountryYearTests(unittest.TestCase):
    def test_deletes_year_transactions_and_uploaded_files(self):
        from app import sql_catalog

        cursor = mock.Mock()
        cursor.fetchone.side_effect = [
            (1,),
            (4,),
            (12,),
            (3,),
        ]
        conn = mock.Mock()
        with mock.patch.object(sql_catalog, "_sql_ready", return_value=True), mock.patch.object(
            sql_catalog, "_sql_retry", side_effect=lambda fn: fn()
        ), mock.patch.object(sql_catalog, "_cursor", return_value=cursor), mock.patch(
            "app.user_store._sql_connect", return_value=conn
        ), mock.patch(
            "app.sql_replica._transaction_table", return_value="dbo.transaction_nederland"
        ):
            result = sql_catalog.wipe_country_year("nederland", "2025")
        sqls = [call.args[0] for call in cursor.execute.call_args_list]
        self.assertTrue(any("DELETE FROM dbo.transaction_nederland" in sql for sql in sqls))
        self.assertTrue(any("DELETE FROM dbo.category_total" in sql for sql in sqls))
        self.assertTrue(any("DELETE FROM dbo.uploaded_files" in sql for sql in sqls))
        self.assertEqual(result["transactions"], 12)
        self.assertEqual(result["files"], 3)
        self.assertEqual(result["year"], "2025")
        conn.commit.assert_called_once()


class UploadGrantAndIngestTests(unittest.TestCase):
    def test_grant_lists_files_from_uploaded_files(self):
        from app import main

        files = [{"file_name": "jan.csv", "format": "natwest-csv"}]
        request = _http_request(
            "/upload/api/upload/grant",
            "t=tok&person=janpiet&center=dkg",
        )
        with mock.patch.object(
            main, "_resolve_upload_identity", return_value={"person": "janpiet", "center": "dkg"}
        ), mock.patch(
            "app.runtime.resolve_country_for_center", return_value="nederland"
        ), mock.patch(
            "app.sql_catalog.years_for_person", return_value=["2026"]
        ), mock.patch(
            "app.sql_catalog.list_uploaded_files", return_value=files
        ), mock.patch(
            "app.core.bank_csv.upload_format_options", return_value=["excel", "natwest-csv"]
        ):
            payload = main.upload_grant(request, year="2026")
        self.assertEqual(payload["person"], "janpiet")
        self.assertEqual(payload["files"], files)

    def test_upload_parses_bytes_into_transaction_ingest(self):
        from app import main

        ingested: list[dict] = []
        recorded: list[tuple] = []

        async def _run(root: Path) -> dict:
            upload = UploadFile(
                BytesIO(NATWEST_CSV),
                filename="jan.csv",
                headers=Headers({"content-type": "text/csv"}),
            )
            request = _http_request("/upload/api/upload")
            with mock.patch.object(
                main,
                "_resolve_upload_identity",
                return_value={"person": "janpiet", "center": "dkg"},
            ), mock.patch(
                "app.runtime.resolve_country_for_center", return_value="nederland"
            ), mock.patch(
                "app.runtime.data_root", return_value=root
            ), mock.patch(
                "app.core.bank_csv.identify_upload_format", return_value="natwest-csv"
            ), mock.patch(
                "app.sql_catalog.category_codes_for_country", return_value=frozenset({18})
            ), mock.patch(
                "app.sql_replica.ingest_bound_transactions",
                side_effect=lambda recs, locked=False: ingested.extend(recs) or len(recs),
            ), mock.patch(
                "app.sql_catalog.record_uploaded_file",
                side_effect=lambda *args: recorded.append(args),
            ), mock.patch.object(
                main, "_sync_uploaded_account"
            ), mock.patch(
                "app.store.announce_mutation"
            ):
                return await main.upload_api(
                    request,
                    file=upload,
                    token="tok",
                    year="2026",
                    person="janpiet",
                    center="dkg",
                )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = asyncio.run(_run(root))
            self.assertEqual(payload["via"], "natwest-csv")
            self.assertGreater(payload["inserted"], 0)
            self.assertEqual(len(ingested), 1)
            self.assertEqual(ingested[0]["amount"], "-12.50")
            self.assertEqual(recorded, [("janpiet", "jan.csv", "natwest-csv")])
            self.assertEqual(_layout_dirs(root), [])
            self.assertFalse(
                (root / "nederland" / "dkg" / "janpiet" / "2026" / "categorized_transactions.json").exists()
            )


class MonthlyRefreshPeriodTests(unittest.TestCase):
    def test_never_updated_uses_first_of_current_month(self):
        from datetime import date

        from app.matrix import monthly_refresh_period

        self.assertEqual(
            monthly_refresh_period(None, today=date(2026, 9, 2)),
            (date(2026, 9, 1), date(2026, 9, 2)),
        )

    def test_skips_when_already_booked_through_today(self):
        from datetime import date

        from app.matrix import monthly_refresh_period

        self.assertIsNone(
            monthly_refresh_period(date(2026, 9, 2), today=date(2026, 9, 2))
        )

    def test_july_date_refreshes_through_today(self):
        from datetime import date

        from app.matrix import monthly_refresh_period

        self.assertEqual(
            monthly_refresh_period(date(2026, 7, 27), today=date(2026, 9, 2)),
            (date(2026, 7, 27), date(2026, 9, 2)),
        )

    def test_mid_august_still_fetches_through_today(self):
        from datetime import date

        from app.matrix import monthly_refresh_period

        self.assertEqual(
            monthly_refresh_period(date(2026, 8, 15), today=date(2026, 9, 2)),
            (date(2026, 8, 15), date(2026, 9, 2)),
        )

    def test_refreshes_from_updated_through_today(self):
        from datetime import date

        from app.matrix import monthly_refresh_period

        self.assertEqual(
            monthly_refresh_period(date(2026, 7, 31), today=date(2026, 9, 2)),
            (date(2026, 7, 31), date(2026, 9, 2)),
        )

    def test_next_month_picks_up_from_last_booked(self):
        from datetime import date

        from app.matrix import monthly_refresh_period

        self.assertEqual(
            monthly_refresh_period(date(2026, 8, 31), today=date(2026, 10, 2)),
            (date(2026, 8, 31), date(2026, 10, 2)),
        )


class _FakeOverlayCursor:
    """Minimal ODBC-like cursor: OBJECT_ID probes then the overlay UNION rows."""

    def __init__(self, tables_exist: bool = True, rows: list | None = None) -> None:
        self.tables_exist = tables_exist
        self.rows = rows or []
        self._mode = ""

    def execute(self, sql: str, params: tuple | None = None) -> "_FakeOverlayCursor":
        self._mode = "probe" if "OBJECT_ID" in sql else "data"
        return self

    def fetchone(self):
        if self._mode == "probe":
            return (1 if self.tables_exist else None,)
        return None

    def fetchall(self):
        if self._mode == "probe":
            return []
        return [row for row in self.rows if row and 3000 <= int(row[0]) <= 4999]


class BalanceOverlayTests(unittest.TestCase):
    def test_missing_tables_return_empty(self):
        from app.sql_replica import _balance_overlay_cents

        self.assertEqual(
            _balance_overlay_cents(2026, _FakeOverlayCursor(tables_exist=False)),
            {},
        )

    def test_to_from_journal_and_mirror_fold_into_cents(self):
        from app.sql_replica import _balance_overlay_cents

        rows = [
            (3000, 500.00),   # journal TO adds
            (3100, -200.00),  # journal FROM subtracts
            (3200, -50.00),   # mirror (signed amount) as stored
            (1000, 999.00),   # below 3000 → ignored
            (2500, 777.00),   # below 3000 → ignored
        ]
        self.assertEqual(
            _balance_overlay_cents(2026, _FakeOverlayCursor(rows=rows)),
            {3000: 50000, 3100: -20000, 3200: -5000},
        )


if __name__ == "__main__":
    unittest.main()

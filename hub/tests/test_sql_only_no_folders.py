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
    def test_list_people_does_not_create_or_require_folders(self):
        from app.people import list_people

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with mock.patch("app.runtime.data_root", return_value=root), mock.patch(
                "app.people.active_center", return_value="dkg"
            ), mock.patch(
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
            self.assertEqual([pack.person_name for pack in packs], ["janpiet"])
            self.assertEqual(packs[0].country, "nederland")
            self.assertEqual(packs[0].center, "dkg")
            self.assertEqual(packs[0].year, "2026")
            self.assertFalse(packs[0].folder.is_dir())
            self.assertFalse(packs[0].data_dir.is_dir())
            self.assertEqual(_layout_dirs(root), [])


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
            files = sql_catalog.list_account_balance_files("janpiet")
        self.assertEqual(
            files,
            [
                {"file_name": "jan.csv", "format": "natwest-csv"},
                {"file_name": "old.xlsx", "format": "excel"},
            ],
        )
        cursor.execute.assert_called_once()
        self.assertIn("account_balance_file", cursor.execute.call_args[0][0])

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
            sql_catalog.record_account_balance_file("janpiet", "jan.csv", "natwest-csv")
        insert_sql = cursor.execute.call_args_list[-1][0][0]
        self.assertIn("INSERT INTO dbo.account_balance_file", insert_sql)
        conn.commit.assert_called_once()


class UploadGrantAndIngestTests(unittest.TestCase):
    def test_grant_lists_files_from_account_balance_file(self):
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
            "app.sql_catalog.list_account_balance_files", return_value=files
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
                "app.sql_catalog.record_account_balance_file",
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


if __name__ == "__main__":
    unittest.main()

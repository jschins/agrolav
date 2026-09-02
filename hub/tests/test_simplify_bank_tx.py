"""Enable Banking payloads must simplify to ingestable booking rows."""
import unittest

from app.core.categorize import simplify_transaction
from app.sql_replica import _booked_on, _decimal_amount


class SimplifyBankTransactionTests(unittest.TestCase):
    def test_datetime_booking_date_and_transaction_id(self):
        record = simplify_transaction(
            {
                "transaction_id": "ING-abc",
                "booking_date": "2026-08-15T00:00:00Z",
                "credit_debit_indicator": "DBIT",
                "transaction_amount": {"amount": "12.50", "currency": "EUR"},
                "creditor": {"name": "Praxis"},
                "_account_index": 0,
                "_account_uid": "uid-1",
            }
        )
        self.assertEqual(record["id"], "ING-abc_0")
        self.assertEqual(record["date"], "15-08-2026")
        self.assertEqual(record["amount"], "-12.50")
        self.assertEqual(record["account_uid"], "uid-1")
        self.assertIsNotNone(_booked_on(record["date"]))
        self.assertIsNotNone(_decimal_amount(record["amount"]))

    def test_value_date_fallback_and_camel_case(self):
        record = simplify_transaction(
            {
                "entryReference": "ref-9",
                "valueDate": "2026-08-20",
                "creditDebitIndicator": "CRDT",
                "transactionAmount": {"amount": "3.00", "currency": "EUR"},
                "debtor": {"name": "Salary"},
                "_account_index": 1,
            }
        )
        self.assertEqual(record["id"], "ref-9_1")
        self.assertEqual(record["date"], "20-08-2026")
        self.assertEqual(record["amount"], "+3.00")
        self.assertEqual(record["name"], "Salary")

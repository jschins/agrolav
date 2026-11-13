"""Excel upload must refresh ``dbo.account.balance`` for connection-less accounts."""

from __future__ import annotations

import unittest

from app.core.excel_import import closing_balance_cents, dated_net_cents_from_rows, saldo_cents_from_rows


def _rows(*lines: dict[str, str]) -> list[dict[str, str]]:
    header = {
        "A": "Datum",
        "B": "Beschrijving",
        "C": "Inkomsten",
        "D": "Uitgaven",
        "E": "Categorie",
        "_row": "1",
    }
    out = [header]
    for index, line in enumerate(lines, start=2):
        row = dict(line)
        row.setdefault("_row", str(index))
        out.append(row)
    return out


class ExcelClosingBalanceTests(unittest.TestCase):
    def test_saldo_row_wins(self) -> None:
        rows = _rows(
            {"A": "01-08-2026", "B": "huur", "C": "", "D": "100", "E": "9"},
            {"A": "", "B": "SALDO", "C": "5000.50", "D": "", "E": ""},
        )
        self.assertEqual(saldo_cents_from_rows(rows), 500050)
        self.assertEqual(
            closing_balance_cents(rows, previous_cents=616700, inserted_net_cents=-10000),
            500050,
        )

    def test_without_saldo_adds_inserted_net(self) -> None:
        rows = _rows(
            {"A": "01-08-2026", "B": "salaris", "C": "200", "D": "", "E": "20"},
            {"A": "02-08-2026", "B": "boodschap", "C": "", "D": "30", "E": "9"},
        )
        self.assertIsNone(saldo_cents_from_rows(rows))
        self.assertEqual(dated_net_cents_from_rows(rows), 17000)
        self.assertEqual(
            closing_balance_cents(rows, previous_cents=616700, inserted_net_cents=17000),
            633700,
        )

    def test_without_saldo_or_inserts_leaves_balance(self) -> None:
        rows = _rows({"A": "01-08-2026", "B": "x", "C": "10", "D": "", "E": "20"})
        self.assertIsNone(
            closing_balance_cents(rows, previous_cents=616700, inserted_net_cents=None)
        )


if __name__ == "__main__":
    unittest.main()

"""Instudo cash posts are the bookings stored on that category."""
from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal
from unittest.mock import patch

from app.cash_on_hand import assign_cash_on_hand
from shared.balance_values import CASH_ON_HAND_ACCOUNT, balance_category_breakdown


class _Cursor:
    def __init__(self, rows: list[tuple] | None = None) -> None:
        self.calls: list[tuple[str, tuple]] = []
        self.rowcount = 3
        self._rows = list(rows or [])

    def execute(self, sql: str, params: tuple | None = None) -> None:
        self.calls.append((sql, tuple(params or ())))

    def fetchone(self) -> tuple:
        sql = self.calls[-1][0] if self.calls else ""
        if "cp_rules" in sql:
            return (1,)
        return (8, 8)

    def fetchall(self) -> list[tuple]:
        sql = self.calls[-1][0] if self.calls else ""
        if "dbo.cp_rules" in sql:
            return [(
                "geldautomaat", 1, "hd", None, 0,
                None, None, "role",
                "cash", "booking", None,
            )]
        return list(self._rows)


class CashOnHandTests(unittest.TestCase):
    def test_sheet_uses_the_category_not_the_bank(self) -> None:
        mapping = {
            11134: ("activa", None),
            11010: ("activa", 10),
        }
        with patch.multiple(
            "shared.balance_values",
            category_roles=lambda *_a, **_k: {},
            verlies_id=lambda *_a, **_k: None,
            eigen_vermogen_id=lambda *_a, **_k: None,
            spaar_mirror_targets=lambda *_a, **_k: set(),
            category_map=lambda *_a, **_k: mapping,
            category_local_codes=lambda *_a, **_k: {11134: 1134, 11010: 1010},
            _opening_balances=lambda *_a, **_k: {},
            _journal_balances=lambda *_a, **_k: {},
            _journal_effect=lambda *_a, **_k: {},
            _booking_balances=lambda *_a, **_k: {11134: Decimal("40")},
            _account_balances_asof=lambda *_a, **_k: {
                48: Decimal("4751"),
                10: Decimal("100"),
            },
        ):
            out = balance_category_breakdown(
                5, 2026, object(), as_of=date(2025, 12, 31), trace=False
            )
        self.assertEqual(out[11134], (4000, "opening+bookings"))
        self.assertEqual(out[11010], (10000, "account:10"))

    def test_opening_plus_category_bookings(self) -> None:
        mapping = {11133: ("activa", None)}
        with patch.multiple(
            "shared.balance_values",
            category_roles=lambda *_a, **_k: {},
            verlies_id=lambda *_a, **_k: None,
            eigen_vermogen_id=lambda *_a, **_k: None,
            spaar_mirror_targets=lambda *_a, **_k: set(),
            category_map=lambda *_a, **_k: mapping,
            category_local_codes=lambda *_a, **_k: {11133: 1133},
            _opening_balances=lambda *_a, **_k: {11133: Decimal("12.50")},
            _journal_balances=lambda *_a, **_k: {},
            _journal_effect=lambda *_a, **_k: {},
            _booking_balances=lambda *_a, **_k: {11133: Decimal("40")},
            _account_balances=lambda *_a, **_k: {55: Decimal("8000")},
        ):
            out = balance_category_breakdown(5, 2026, object(), trace=False)
        self.assertEqual(out[11133], (5250, "opening+bookings"))

    def test_assign_writes_the_cash_category_on_open_rows(self) -> None:
        cursor = _Cursor(list(CASH_ON_HAND_ACCOUNT.items()))
        count = assign_cash_on_hand(
            cursor,
            "dbo.transaction_beheer_instudo",
            5,
            person_id=7,
            year=2026,
        )
        lookup = next(sql for sql, _params in cursor.calls if "= N'hd'" in sql)
        self.assertIn("= N'hd'", lookup)
        self.assertIn("= N'cash'", lookup)
        updates = [call for call in cursor.calls if call[0].lstrip().upper().startswith("UPDATE")]
        self.assertEqual(count, 3 * 7)
        self.assertEqual(len(updates), 7)
        sql, params = updates[0]
        self.assertIn("bank_type = ?", sql)
        self.assertIn("modification IN (-1, 0, 1)", sql)
        self.assertNotIn("modification IN (-1, 0, 1, 2", sql)
        self.assertEqual(params[0], 11133)
        self.assertEqual(params[1], 55)
        self.assertEqual(params[2], "Geldautomaat")
        self.assertEqual(params[3:], (7, 2026))

    def test_country_4_cash_role_is_written_too(self) -> None:
        cursor = _Cursor([(1057, 48)])
        count = assign_cash_on_hand(
            cursor,
            "dbo.transaction_beheer_sdog",
            4,
            year=2026,
        )
        updates = [call for call in cursor.calls if call[0].lstrip().upper().startswith("UPDATE")]
        self.assertEqual(count, 3)
        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0][1][0], 1057)
        self.assertEqual(updates[0][1][1], 48)

    def test_missing_link_columns_write_nothing(self) -> None:
        cursor = _Cursor(list(CASH_ON_HAND_ACCOUNT.items()))
        cursor.fetchone = lambda: (None, None)  # type: ignore[method-assign]
        self.assertEqual(
            assign_cash_on_hand(cursor, "dbo.transaction_beheer_instudo", 5),
            0,
        )
        self.assertTrue(
            all(not sql.lstrip().upper().startswith("UPDATE") for sql, _params in cursor.calls)
        )

    def test_other_countries_are_left_alone(self) -> None:
        cursor = _Cursor()
        self.assertEqual(
            assign_cash_on_hand(cursor, "dbo.transaction_nederland", 1),
            0,
        )
        self.assertTrue(all(not sql.lstrip().upper().startswith("UPDATE") for sql, _params in cursor.calls))


if __name__ == "__main__":
    unittest.main()

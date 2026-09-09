"""Plug-2000 signs: FROM -X; TO +X iff same class (A vs P/R). K and O same."""
from __future__ import annotations

import unittest
from decimal import Decimal

from shared.balance_values import (
    _booking_balances,
    _journal_effect,
    booking_signed_amount,
    category_display_name,
    is_activa,
    is_hit_forbidden_code,
    is_journal_forbidden_code,
    journal_deltas,
    result_overlay_cents,
    spaar_mirror_posted_amount,
    spaar_source_exclude_clause,
)


class _FakeBookingCursor:
    def __init__(
        self,
        *,
        username: str | None = "beheer",
        table_exists: bool = True,
        rows: list | None = None,
    ) -> None:
        self.username = username
        self.table_exists = table_exists
        self.rows = rows or []
        self.sql = ""

    def execute(self, sql: str, params: tuple | None = None) -> "_FakeBookingCursor":
        del params
        self.sql = sql
        return self

    def fetchone(self):
        if "FROM dbo.country" in self.sql:
            return None if self.username is None else (self.username,)
        if "OBJECT_ID" in self.sql:
            return (1 if self.table_exists else None,)
        return None

    def fetchall(self):
        return list(self.rows)


class _FakeJournalCursor:
    def __init__(self, rows: list | None = None, *, exists: bool = True) -> None:
        self.rows = rows or []
        self.exists = exists
        self.sql = ""

    def execute(self, sql: str, params: tuple | None = None) -> "_FakeJournalCursor":
        del params
        self.sql = sql
        return self

    def fetchone(self):
        if "OBJECT_ID" in self.sql:
            return (1 if self.exists else None,)
        return None

    def fetchall(self):
        return list(self.rows)


class _FakeOverlayCursor:
    """OBJECT_ID probes, then journal pairs, then balance_transaction rows."""

    def __init__(
        self,
        *,
        tables_exist: bool = True,
        journals: list | None = None,
        transactions: list | None = None,
    ) -> None:
        self.tables_exist = tables_exist
        self.journals = journals or []
        self.transactions = transactions or []
        self.sql = ""

    def execute(self, sql: str, params: tuple | None = None) -> "_FakeOverlayCursor":
        del params
        self.sql = sql
        return self

    def fetchone(self):
        if "OBJECT_ID" in self.sql:
            return (1 if self.tables_exist else None,)
        return None

    def fetchall(self):
        if "OBJECT_ID" in self.sql:
            return []
        if "category_from" in self.sql:
            return list(self.journals)
        return list(self.transactions)


class BookingBalancesTests(unittest.TestCase):
    def test_missing_country_returns_empty(self):
        self.assertEqual(
            _booking_balances(4, 2026, _FakeBookingCursor(username=None)),
            {},
        )

    def test_missing_table_returns_empty(self):
        self.assertEqual(
            _booking_balances(4, 2026, _FakeBookingCursor(table_exists=False)),
            {},
        )

    def test_loan_repayment_on_2500_keeps_bank_sign(self):
        cursor = _FakeBookingCursor(rows=[(2500, 2500, Decimal("-9333.32"))])
        self.assertEqual(
            _booking_balances(4, 2026, cursor),
            {2500: Decimal("-9333.32")},
        )

    def test_activa_booking_negates_bank_sign(self):
        cursor = _FakeBookingCursor(rows=[(1110, 1110, Decimal("9000"))])
        self.assertEqual(
            _booking_balances(4, 2026, cursor),
            {1110: Decimal("-9000")},
        )

    def test_bank_codes_1051_1056_skipped(self):
        cursor = _FakeBookingCursor(
            rows=[
                (1051, 1051, Decimal("10")),
                (1052, 1052, Decimal("20")),
                (1056, 1056, Decimal("30")),
            ]
        )
        self.assertEqual(_booking_balances(4, 2026, cursor), {})

    def test_sql_excludes_spaar_source_rows(self):
        cursor = _FakeBookingCursor(rows=[])
        _booking_balances(4, 2026, cursor)
        sql = cursor.sql.lower()
        self.assertIn("not (t.account_id", sql)
        self.assertIn("like ?", sql)

    def test_country_without_mirror_skips_spaar_filter(self):
        cursor = _FakeBookingCursor(rows=[])
        _booking_balances(5, 2026, cursor)
        self.assertNotIn("not (t.account_id", cursor.sql.lower())


class SpaarMirrorTests(unittest.TestCase):
    def test_transfer_to_1052_posts_plus_x(self):
        # X > 0 leaves 1051 (bank amount -X); 1052 must increase by X.
        source = Decimal("-2500")
        posted = spaar_mirror_posted_amount(source)
        self.assertEqual(posted, Decimal("2500"))
        self.assertEqual(source + posted, Decimal("0"))

    def test_transfer_from_1052_posts_minus_x(self):
        source = Decimal("2500")
        posted = spaar_mirror_posted_amount(source)
        self.assertEqual(posted, Decimal("-2500"))
        self.assertEqual(source + posted, Decimal("0"))

    def test_posted_amount_is_not_activa_booking_sign(self):
        source = Decimal("-2500")
        self.assertIsNone(booking_signed_amount(1052, source))
        self.assertEqual(spaar_mirror_posted_amount(source), Decimal("2500"))

    def test_exclude_clause_beheer_only(self):
        sql, params = spaar_source_exclude_clause(4)
        self.assertIn("not (t.account_id", sql.lower())
        self.assertEqual(params[0], 18)
        self.assertEqual(params[1], "%spaarrekening%")
        sql5, params5 = spaar_source_exclude_clause(5)
        self.assertEqual(sql5, "")
        self.assertEqual(params5, [])


class BookingSignedAmountTests(unittest.TestCase):
    def test_ranges(self):
        x = Decimal("100")
        self.assertEqual(booking_signed_amount(1110, x), Decimal("-100"))
        self.assertEqual(booking_signed_amount(2500, x), Decimal("100"))
        self.assertIsNone(booking_signed_amount(1051, x))
        self.assertIsNone(booking_signed_amount(1052, x))
        self.assertIsNone(booking_signed_amount(1056, x))
        self.assertIsNone(booking_signed_amount(2000, x))
        self.assertIsNone(booking_signed_amount(2100, x))
        self.assertIsNone(booking_signed_amount(3110, x))


class InvarianceClassTests(unittest.TestCase):
    def test_activa_vs_rest(self):
        self.assertTrue(is_activa(1110))
        self.assertFalse(is_activa(2500))
        self.assertFalse(is_activa(3110))
        self.assertFalse(is_activa(4110))


class JournalDeltaTests(unittest.TestCase):
    def test_from_always_minus_x(self):
        x = Decimal("9000")
        for src, dst in (
            (1110, 1111),
            (1110, 2500),
            (2500, 1110),
            (2500, 2050),
            (1110, 3110),
            (2500, 3110),
            (3110, 1110),
            (3110, 2500),
            (3110, 4110),
        ):
            src_d, _dst_d = journal_deltas(src, dst, x)
            self.assertEqual(src_d, Decimal("-9000"), f"{src}->{dst}")

    def test_same_class_to_plus(self):
        x = Decimal("9000")
        self.assertEqual(journal_deltas(1110, 1111, x), (Decimal("-9000"), Decimal("9000")))
        self.assertEqual(journal_deltas(2500, 2050, x), (Decimal("-9000"), Decimal("9000")))
        self.assertEqual(journal_deltas(3110, 4110, x), (Decimal("-9000"), Decimal("9000")))
        self.assertEqual(journal_deltas(2500, 3110, x), (Decimal("-9000"), Decimal("9000")))
        self.assertEqual(journal_deltas(3110, 2500, x), (Decimal("-9000"), Decimal("9000")))

    def test_cross_class_to_minus(self):
        x = Decimal("9000")
        self.assertEqual(journal_deltas(1110, 2500, x), (Decimal("-9000"), Decimal("-9000")))
        self.assertEqual(journal_deltas(1110, 3110, x), (Decimal("-9000"), Decimal("-9000")))
        self.assertEqual(journal_deltas(2500, 1110, x), (Decimal("-9000"), Decimal("-9000")))
        self.assertEqual(journal_deltas(3110, 1110, x), (Decimal("-9000"), Decimal("-9000")))
        self.assertEqual(journal_deltas(1110, 4110, x), (Decimal("-9000"), Decimal("-9000")))


class JournalEffectTests(unittest.TestCase):
    def test_from_activa_to_kosten(self):
        cursor = _FakeJournalCursor(rows=[(1110, 3110, Decimal("9000"))])
        self.assertEqual(
            _journal_effect(4, 2026, cursor),
            {1110: Decimal("-9000"), 3110: Decimal("-9000")},
        )

    def test_from_activa_to_passiva(self):
        cursor = _FakeJournalCursor(rows=[(1110, 2500, Decimal("9000"))])
        self.assertEqual(
            _journal_effect(4, 2026, cursor),
            {1110: Decimal("-9000"), 2500: Decimal("-9000")},
        )

    def test_from_passiva_to_activa(self):
        cursor = _FakeJournalCursor(rows=[(2500, 1110, Decimal("9000"))])
        self.assertEqual(
            _journal_effect(4, 2026, cursor),
            {2500: Decimal("-9000"), 1110: Decimal("-9000")},
        )

    def test_from_passiva_to_resultaat(self):
        cursor = _FakeJournalCursor(rows=[(2500, 3110, Decimal("9000"))])
        self.assertEqual(
            _journal_effect(4, 2026, cursor),
            {2500: Decimal("-9000"), 3110: Decimal("9000")},
        )

    def test_skips_eigen_vermogen_2000(self):
        cursor = _FakeJournalCursor(
            rows=[(2000, 1110, Decimal("9000")), (1110, 2000, Decimal("50"))]
        )
        self.assertEqual(_journal_effect(4, 2026, cursor), {})


class ResultOverlayTests(unittest.TestCase):
    def test_missing_tables_return_empty(self):
        self.assertEqual(
            result_overlay_cents(4, 2026, _FakeOverlayCursor(tables_exist=False)),
            {},
        )

    def test_activa_to_kosten_decreases_saldo(self):
        cursor = _FakeOverlayCursor(journals=[(1110, 3110, Decimal("60"))])
        self.assertEqual(result_overlay_cents(4, 2026, cursor), {3110: -6000})

    def test_passiva_to_kosten_increases_saldo(self):
        cursor = _FakeOverlayCursor(journals=[(2500, 3110, Decimal("60"))])
        self.assertEqual(result_overlay_cents(4, 2026, cursor), {3110: 6000})

    def test_kosten_and_omzet_same_sign(self):
        cursor = _FakeOverlayCursor(journals=[(1110, 4110, Decimal("100"))])
        self.assertEqual(result_overlay_cents(4, 2026, cursor), {4110: -10000})

    def test_from_resultaat_always_minus_x(self):
        cursor = _FakeOverlayCursor(journals=[(3200, 1110, Decimal("40"))])
        self.assertEqual(result_overlay_cents(4, 2026, cursor), {3200: -4000})

    def test_transaction_rows_keep_stored_amount(self):
        cursor = _FakeOverlayCursor(
            transactions=[(4000, Decimal("200")), (3050, Decimal("-30"))]
        )
        self.assertEqual(
            result_overlay_cents(4, 2026, cursor),
            {4000: 20000, 3050: -3000},
        )

    def test_out_of_range_transaction_ignored(self):
        cursor = _FakeOverlayCursor(transactions=[(2500, Decimal("777"))])
        self.assertEqual(result_overlay_cents(4, 2026, cursor), {})


class MatrixRoleTests(unittest.TestCase):
    def test_footers_stay_bare(self):
        self.assertEqual(category_display_name("saldo", 22, "balance"), "saldo")
        self.assertEqual(category_display_name("datum", 23, "last_booked"), "datum")

    def test_never_and_no_hit_keep_coded_names(self):
        self.assertEqual(
            category_display_name("Eigen vermogen", 2000, "never"),
            "2000 Eigen vermogen",
        )
        self.assertEqual(
            category_display_name("Bank algemeen", 1051, "no_hit"),
            "1051 Bank algemeen",
        )

    def test_ordinary_coded(self):
        self.assertEqual(category_display_name("Gebouwen", 1000, None), "1000 Gebouwen")

    def test_hit_and_journal_rules(self):
        self.assertTrue(is_hit_forbidden_code(2000))
        self.assertTrue(is_journal_forbidden_code(2000))
        self.assertTrue(is_hit_forbidden_code(1051))
        self.assertTrue(is_hit_forbidden_code(1056, "no_hit"))
        self.assertFalse(is_journal_forbidden_code(1051))
        self.assertFalse(is_hit_forbidden_code(1110))
        self.assertFalse(is_journal_forbidden_code(1110))
        self.assertTrue(is_hit_forbidden_code(22, "balance"))


if __name__ == "__main__":
    unittest.main()

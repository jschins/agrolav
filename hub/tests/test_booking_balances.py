"""Journal signs: TO +X; FROM = minus APR product (A −1, P/R +1)."""
from __future__ import annotations

import unittest
from decimal import Decimal

from shared.balance_values import (
    _booking_balances,
    _journal_effect,
    afschrijving_amount,
    booking_signed_amount,
    category_display_name,
    is_activa,
    is_balance_sheet_code,
    is_kosten_local,
    is_resultaat,
    is_hit_forbidden_code,
    is_journal_forbidden_code,
    journal_deltas,
    journal_leg_amount,
    build_parent_tree,
    result_overlay_cents,
    _pair_spaar_mirrors,
    spaar_mirror_posted_amount,
    spaar_mirrors,
    spaar_source_exclude_clause,
)


class _FakeBookingCursor:
    def __init__(
        self,
        *,
        username: str | None = "beheer_sdog",
        table_exists: bool = True,
        rows: list | None = None,
    ) -> None:
        self.username = username
        self.table_exists = table_exists
        self.rows = rows or []
        self.sql = ""
        self._params: tuple | None = None

    def execute(self, sql: str, params: tuple | None = None) -> "_FakeBookingCursor":
        self.sql = sql
        self._params = params
        return self

    def fetchone(self):
        if "FROM dbo.country" in self.sql:
            return None if self.username is None else (self.username,)
        if "OBJECT_ID" in self.sql:
            return (1 if self.table_exists else None,)
        return None

    def fetchall(self):
        if "N'source'" in self.sql and "N'mirror'" in self.sql:
            cid = 0
            if self._params:
                cid = int(self._params[0])
            if cid == 4:
                return [
                    (1051, 1051, "source", 18, 1, "beh_stichtingen"),
                    (1052, 1052, "mirror", None, 1, "beh_stichtingen"),
                ]
            if cid == 5:
                return [
                    (11018, 1018, "source", 39, 7, "instudo_sia"),
                    (11019, 1019, "mirror", None, 7, "instudo_sia"),
                    (11020, 1020, "source", 40, 8, "instudo_sib"),
                    (11021, 1021, "mirror", None, 8, "instudo_sib"),
                ]
            return []
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
        sql = self.sql.lower()
        if "local_code" in sql and "category_role" not in sql:
            return [(2000, 2000), (2100, 2100)]
        if "dim_category" in sql:
            return [(2000, "equity"), (2100, "profit")]
        return list(self.rows)


class _FakeOverlayCursor:
    """OBJECT_ID probes, then journal pairs, then transaction_mirror rows."""

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
        if "dim_category" in self.sql.lower():
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

    def test_ordinary_2000_is_passiva_overlay(self):
        cursor = _FakeBookingCursor(rows=[(2000, 2000, Decimal("40"), "remainder")])
        self.assertEqual(_booking_balances(4, 2026, cursor), {2000: Decimal("40")})

    def test_equity_role_skipped_whatever_local_code(self):
        cursor = _FakeBookingCursor(rows=[(2199, 2199, Decimal("40"), "equity")])
        self.assertEqual(_booking_balances(4, 2026, cursor), {})

    def test_bank_and_source_skipped_mirror_kept(self):
        cursor = _FakeBookingCursor(
            rows=[
                (1051, 1051, Decimal("10"), "source"),
                (1052, 1052, Decimal("20"), "mirror"),
                (1056, 1056, Decimal("30"), "bank"),
            ]
        )
        self.assertEqual(_booking_balances(4, 2026, cursor), {1052: Decimal("-20")})

    def test_sql_excludes_spaar_source_rows(self):
        cursor = _FakeBookingCursor(rows=[])
        _booking_balances(4, 2026, cursor)
        sql = cursor.sql.lower()
        self.assertIn("not ((t.account_id", sql)
        self.assertIn("like ?", sql)

    def test_country_without_mirror_skips_spaar_filter(self):
        cursor = _FakeBookingCursor(rows=[])
        _booking_balances(6, 2026, cursor)
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
        self.assertEqual(spaar_mirror_posted_amount(source), Decimal("2500"))

    def test_exclude_clause_from_category_roles(self):
        sql, params = spaar_source_exclude_clause(4, cursor=_FakeBookingCursor())
        self.assertIn("not ((t.account_id", sql.lower())
        self.assertEqual(params[0], 18)
        self.assertEqual(params[1], "%spaarrekening%")
        sql5, params5 = spaar_source_exclude_clause(5, cursor=_FakeBookingCursor())
        self.assertIn("not (", sql5.lower())
        self.assertEqual(params5, [39, "%spaarrekening%", 40, "%spaarrekening%"])

    def test_instudo_pairs_one_mirror_per_source(self):
        pairs = spaar_mirrors(5, _FakeBookingCursor())
        self.assertEqual(
            [
                (
                    pair["source_category"],
                    pair["target_category"],
                    pair["source_account_id"],
                )
                for pair in pairs
            ],
            [(11018, 11019, 39), (11020, 11021, 40)],
        )

    def test_instudo_pairing_does_not_cross_centers(self):
        sources = [
            {
                "category_id": 11018,
                "local_code": 1018,
                "account_id": 39,
                "center_id": 7,
                "center": "instudo_sia",
            },
            {
                "category_id": 11020,
                "local_code": 1020,
                "account_id": 40,
                "center_id": 8,
                "center": "instudo_sib",
            },
        ]
        mirrors = [
            {"category_id": 11021, "local_code": 1021, "center_id": 7, "center": "instudo_sia"},
            {"category_id": 11019, "local_code": 1019, "center_id": 8, "center": "instudo_sib"},
        ]
        pairs = _pair_spaar_mirrors(sources, mirrors, [])
        self.assertEqual(
            {(pair["source_category"], pair["target_category"]) for pair in pairs},
            {(11018, 11021), (11020, 11019)},
        )


class BookingSignedAmountTests(unittest.TestCase):
    def test_ranges(self):
        x = Decimal("100")
        self.assertEqual(booking_signed_amount(1110, x), Decimal("-100"))
        self.assertEqual(booking_signed_amount(2500, x), Decimal("100"))
        self.assertEqual(booking_signed_amount(2000, x), Decimal("100"))
        self.assertEqual(booking_signed_amount(2000, x, "remainder"), Decimal("100"))
        self.assertIsNone(booking_signed_amount(1051, x, "source"))
        self.assertEqual(booking_signed_amount(1052, x, "mirror"), Decimal("-100"))
        self.assertIsNone(booking_signed_amount(1056, x, "bank"))
        self.assertIsNone(booking_signed_amount(2000, x, "equity"))
        self.assertIsNone(booking_signed_amount(2199, x, "equity"))
        self.assertIsNone(booking_signed_amount(1056, x, "no_hit"))
        self.assertIsNone(booking_signed_amount(2000, x, "never"))
        self.assertIsNone(booking_signed_amount(2100, x, "profit"))
        self.assertIsNone(booking_signed_amount(2500, x, "profit"))
        self.assertIsNone(booking_signed_amount(3110, x))


class InvarianceClassTests(unittest.TestCase):
    def test_activa_vs_rest(self):
        self.assertTrue(is_activa(1110))
        self.assertFalse(is_activa(2500))
        self.assertFalse(is_activa(3110))
        self.assertFalse(is_activa(4110))

    def test_sheet_excludes_resultaat(self):
        self.assertTrue(is_balance_sheet_code(1110))
        self.assertTrue(is_balance_sheet_code(2000))
        self.assertTrue(is_balance_sheet_code(2500))
        self.assertFalse(is_balance_sheet_code(3110))
        self.assertFalse(is_balance_sheet_code(4110))


class JournalDeltaTests(unittest.TestCase):
    def test_to_always_plus_x(self):
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
            (1052, 4050),
            (4050, 1052),
        ):
            _src_d, dst_d = journal_deltas(src, dst, x)
            self.assertEqual(dst_d, Decimal("9000"), f"{src}->{dst}")

    def test_from_follows_apr_product(self):
        x = Decimal("9000")
        self.assertEqual(journal_deltas(1110, 1111, x), (Decimal("-9000"), Decimal("9000")))
        self.assertEqual(journal_deltas(2500, 2050, x), (Decimal("-9000"), Decimal("9000")))
        self.assertEqual(journal_deltas(3110, 4110, x), (Decimal("-9000"), Decimal("9000")))
        self.assertEqual(journal_deltas(2500, 3110, x), (Decimal("-9000"), Decimal("9000")))
        self.assertEqual(journal_deltas(1110, 2500, x), (Decimal("9000"), Decimal("9000")))
        self.assertEqual(journal_deltas(1110, 3110, x), (Decimal("9000"), Decimal("9000")))
        self.assertEqual(journal_deltas(2500, 1110, x), (Decimal("9000"), Decimal("9000")))
        self.assertEqual(journal_deltas(3110, 1110, x), (Decimal("9000"), Decimal("9000")))

    def test_swap_1052_4050(self):
        x = Decimal("9000")
        self.assertEqual(
            journal_leg_amount(1052, 1052, 4050, x), Decimal("9000")
        )
        self.assertEqual(
            journal_leg_amount(4050, 1052, 4050, x), Decimal("9000")
        )
        self.assertEqual(
            journal_leg_amount(1052, 4050, 1052, x), Decimal("9000")
        )
        self.assertEqual(
            journal_leg_amount(4050, 4050, 1052, x), Decimal("9000")
        )
        self.assertEqual(
            journal_leg_amount(1052, 1052, 4050, -x), Decimal("-9000")
        )


class JournalEffectTests(unittest.TestCase):
    def test_from_activa_to_kosten(self):
        cursor = _FakeJournalCursor(rows=[(1110, 3110, Decimal("9000"))])
        self.assertEqual(
            _journal_effect(4, 2026, cursor),
            {1110: Decimal("9000"), 3110: Decimal("9000")},
        )

    def test_from_activa_to_passiva(self):
        cursor = _FakeJournalCursor(rows=[(1110, 2500, Decimal("9000"))])
        self.assertEqual(
            _journal_effect(4, 2026, cursor),
            {1110: Decimal("9000"), 2500: Decimal("9000")},
        )

    def test_from_passiva_to_activa(self):
        cursor = _FakeJournalCursor(rows=[(2500, 1110, Decimal("9000"))])
        self.assertEqual(
            _journal_effect(4, 2026, cursor),
            {2500: Decimal("9000"), 1110: Decimal("9000")},
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

    def test_activa_to_kosten_increases_saldo(self):
        cursor = _FakeOverlayCursor(journals=[(1110, 3110, Decimal("60"))])
        self.assertEqual(result_overlay_cents(4, 2026, cursor), {3110: 6000})

    def test_passiva_to_kosten_increases_saldo(self):
        cursor = _FakeOverlayCursor(journals=[(2500, 3110, Decimal("60"))])
        self.assertEqual(result_overlay_cents(4, 2026, cursor), {3110: 6000})

    def test_kosten_and_omzet_same_sign(self):
        cursor = _FakeOverlayCursor(journals=[(1110, 4110, Decimal("100"))])
        self.assertEqual(result_overlay_cents(4, 2026, cursor), {4110: 10000})

    def test_from_resultaat_to_activa_increases_saldo(self):
        cursor = _FakeOverlayCursor(journals=[(3200, 1110, Decimal("40"))])
        self.assertEqual(result_overlay_cents(4, 2026, cursor), {3200: 4000})

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


class CategoryRoleTests(unittest.TestCase):
    def test_footers_stay_bare(self):
        self.assertEqual(category_display_name("saldo", 22, "balance"), "saldo")
        self.assertEqual(category_display_name("datum", 23, "last_booked"), "datum")

    def test_equity_and_bank_keep_coded_names(self):
        self.assertEqual(
            category_display_name("Eigen vermogen", 2000, "equity"),
            "2000 Eigen vermogen",
        )
        self.assertEqual(
            category_display_name("Bank algemeen", 1051, "source"),
            "1051 Bank algemeen",
        )
        self.assertEqual(
            category_display_name("Unclassified", 18, "remainder"),
            "0018 Unclassified",
        )

    def test_ordinary_coded(self):
        self.assertEqual(category_display_name("Gebouwen", 1000, None), "1000 Gebouwen")

    def test_hit_and_journal_rules(self):
        self.assertTrue(is_hit_forbidden_code(2000, "equity"))
        self.assertTrue(is_journal_forbidden_code(2000, "equity"))
        self.assertTrue(is_hit_forbidden_code(2000, "never"))
        self.assertTrue(is_journal_forbidden_code(2000, "never"))
        self.assertTrue(is_hit_forbidden_code(1051, "source"))
        self.assertFalse(is_hit_forbidden_code(1052, "mirror"))
        self.assertTrue(is_hit_forbidden_code(1056, "bank"))
        self.assertTrue(is_hit_forbidden_code(1056, "no_hit"))
        self.assertFalse(is_journal_forbidden_code(1051, "source"))
        self.assertFalse(is_journal_forbidden_code(1052, "mirror"))
        self.assertFalse(is_hit_forbidden_code(1110))
        self.assertFalse(is_journal_forbidden_code(1110))
        self.assertFalse(is_hit_forbidden_code(18, "remainder"))
        self.assertFalse(is_journal_forbidden_code(18, "remainder"))
        self.assertTrue(is_hit_forbidden_code(22, "balance"))
        self.assertTrue(is_hit_forbidden_code(2100, "profit"))
        self.assertTrue(is_journal_forbidden_code(2100, "profit"))
        self.assertEqual(
            category_display_name("Verlies", 2100, "profit"),
            "2100 Verlies",
        )

    def test_afschrijving_amount(self):
        self.assertEqual(
            afschrijving_amount("-0.03", Decimal("100000")),
            Decimal("-3000.00"),
        )
        self.assertEqual(
            afschrijving_amount("-0.20", Decimal("50000")),
            Decimal("-10000.00"),
        )

    def test_kosten_bron_range(self):
        self.assertTrue(is_kosten_local(3001))
        self.assertTrue(is_kosten_local(3999))
        self.assertFalse(is_kosten_local(2999))
        self.assertFalse(is_kosten_local(4000))

    def test_parent_tree_nests_groups_and_totals(self):
        posts = [
            {"code": 1050, "label": "Gebouwen", "amount": 500.0},
            {"code": 1000, "label": "Kas Huis", "amount": 10.0},
            {"code": 1001, "label": "Kas Administratie", "amount": 5.0},
            {"code": 1035, "label": "Debiteuren", "amount": 20.0},
            {"code": 2000, "label": "Eigen vermogen", "amount": 535.0},
            {"code": 2300, "label": "Schulden banken", "amount": 0.0},
            {"code": 2301, "label": "ING STD", "amount": 0.0},
        ]
        parents = {
            1050: "Activa/Vaste activa",
            1000: "Activa/Vlottende activa/Kas",
            1001: "Activa/Vlottende activa/Kas",
            1035: "Activa/Vlottende activa",
            2000: "Passiva",
            2300: "Passiva/Schulden",
            2301: "Passiva/schulden",
        }
        roots = build_parent_tree(
            posts, parents, lambda p: "Activa" if p["code"] < 2000 else "Passiva"
        )
        self.assertEqual([r["name"] for r in roots], ["Activa", "Passiva"])
        activa, passiva = roots
        self.assertEqual(activa["total"], 535.0)
        # Children ordered by lowest local_code: Vlottende (1000) before Vaste (1050).
        self.assertEqual(
            [c["name"] for c in activa["children"]], ["Vlottende activa", "Vaste activa"]
        )
        vlottend = activa["children"][0]
        self.assertEqual(vlottend["total"], 35.0)
        kas, debiteuren = vlottend["children"]
        self.assertEqual(kas["kind"], "group")
        self.assertEqual([c["code"] for c in kas["children"]], [1000, 1001])
        self.assertEqual(debiteuren["kind"], "post")
        self.assertEqual(debiteuren["code"], 1035)
        # Case-insensitive group merge keeps the first spelling.
        schulden = [c for c in passiva["children"] if c["kind"] == "group"]
        self.assertEqual(len(schulden), 1)
        self.assertEqual(schulden[0]["name"], "Schulden")
        self.assertEqual([c["code"] for c in schulden[0]["children"]], [2300, 2301])

    def test_parent_tree_sums_columns_per_group(self):
        posts = [
            {"code": 3001, "label": "Huur", "amount": -30.0, "columns": [-10.0, -20.0]},
            {"code": 3002, "label": "Energie", "amount": -5.0, "columns": [-5.0, 0.0]},
            {"code": 4000, "label": "Giften", "amount": 100.0, "columns": [0.0, 100.0]},
        ]
        parents = {
            3001: "Lasten/Huisvesting",
            3002: "Lasten/Huisvesting",
            4000: "Baten",
        }
        lasten, baten = build_parent_tree(posts, parents, "Resultaat")
        self.assertEqual(lasten["total"], -35.0)
        self.assertEqual(lasten["columns"], [-15.0, -20.0])
        self.assertEqual(lasten["children"][0]["columns"], [-15.0, -20.0])
        self.assertEqual(baten["columns"], [0.0, 100.0])

    def test_parent_tree_default_root_for_missing_parent(self):
        roots = build_parent_tree(
            [{"code": 3001, "label": "Huur", "amount": -1.0}], {}, "Resultaat"
        )
        self.assertEqual(len(roots), 1)
        self.assertEqual(roots[0]["name"], "Resultaat")
        self.assertEqual(roots[0]["children"][0]["kind"], "post")
        self.assertEqual(roots[0]["total"], -1.0)


if __name__ == "__main__":
    unittest.main()

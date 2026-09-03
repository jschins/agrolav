"""Country/center egress_ip allowlists."""
import unittest
from unittest import mock

from app.hub_ip import format_egress_list, ip_in_allowlist, parse_egress_list


class EgressListTests(unittest.TestCase):
    def test_parse_splits_and_dedupes(self):
        self.assertEqual(
            parse_egress_list(" 1.1.1.1, 8.8.8.8,1.1.1.1 "),
            ["1.1.1.1", "8.8.8.8"],
        )

    def test_empty_admits_nothing(self):
        self.assertFalse(ip_in_allowlist("9.9.9.9", []))
        self.assertFalse(ip_in_allowlist("9.9.9.9", parse_egress_list("")))

    def test_list_must_contain_client(self):
        allowed = parse_egress_list("10.0.0.1,10.0.0.2")
        self.assertTrue(ip_in_allowlist("10.0.0.1", allowed))
        self.assertFalse(ip_in_allowlist("8.8.8.8", allowed))

    def test_format_roundtrip(self):
        self.assertEqual(format_egress_list(["8.8.8.8", "1.1.1.1", "8.8.8.8"]), "8.8.8.8,1.1.1.1")
        self.assertIsNone(format_egress_list([]))


class AdministratorEgressTests(unittest.TestCase):
    def test_administrator_ip_is_allowed_for_restricted_login(self):
        from app import hub_ip

        user = {"id": 7, "center": "dkg", "country": "nederland", "person": ""}
        with mock.patch.object(
            hub_ip, "administrator_ip_allowed", return_value=True
        ), mock.patch.object(hub_ip, "_egress_raw_for_user") as own_allowlist:
            self.assertTrue(hub_ip.login_ip_allowed(user, "80.12.34.56"))
        own_allowlist.assert_not_called()

    def test_non_administrator_must_pass_own_allowlist(self):
        from app import hub_ip

        user = {"id": 7, "center": "dkg", "country": "nederland", "person": ""}
        with mock.patch.object(
            hub_ip, "administrator_ip_allowed", return_value=False
        ), mock.patch.object(
            hub_ip, "_egress_raw_for_user", return_value="81.23.45.67"
        ):
            self.assertFalse(hub_ip.login_ip_allowed(user, "80.12.34.56"))

    def test_own_list_is_summed_with_the_administrator_table(self):
        from app import hub_ip

        user = {"id": 7, "center": "dkg", "country": "nederland", "person": ""}
        with mock.patch.object(
            hub_ip, "administrator_ip_allowed", return_value=False
        ), mock.patch.object(
            hub_ip, "_egress_raw_for_user", return_value="81.23.45.67"
        ):
            self.assertTrue(hub_ip.login_ip_allowed(user, "81.23.45.67"))

    def test_null_egress_column_admits_nothing(self):
        from app import hub_ip

        user = {"id": 7, "center": "dkg", "country": "nederland", "person": ""}
        with mock.patch.object(
            hub_ip, "administrator_ip_allowed", return_value=False
        ), mock.patch.object(hub_ip, "_egress_raw_for_user", return_value=None):
            self.assertFalse(hub_ip.login_ip_allowed(user, "80.12.34.56"))

    def test_administrator_ip_survives_a_null_egress_column(self):
        from app import hub_ip

        user = {"id": 7, "center": "dkg", "country": "nederland", "person": ""}
        with mock.patch.object(
            hub_ip, "administrator_ip_allowed", return_value=True
        ), mock.patch.object(hub_ip, "_egress_raw_for_user", return_value=None):
            self.assertTrue(hub_ip.login_ip_allowed(user, "80.12.34.56"))

    def test_unusable_client_ip_is_refused(self):
        from app import hub_ip

        user = {"id": 7, "center": "dkg", "country": "nederland", "person": ""}
        with mock.patch.object(hub_ip, "administrator_ip_allowed") as admin:
            self.assertFalse(hub_ip.login_ip_allowed(user, None))
            self.assertFalse(hub_ip.login_ip_allowed(user, "unknown"))
        admin.assert_not_called()

    def test_unreadable_allowlist_is_refused(self):
        from app import hub_ip

        user = {"id": 7, "center": "dkg", "country": "nederland", "person": ""}
        with mock.patch.object(
            hub_ip, "administrator_ip_allowed", return_value=False
        ), mock.patch.object(
            hub_ip, "_egress_raw_for_user", side_effect=RuntimeError("no sql")
        ):
            self.assertFalse(hub_ip.login_ip_allowed(user, "80.12.34.56"))

    def test_person_login_stays_ungated(self):
        from app import hub_ip

        user = {"id": 7, "center": "dkg", "country": "nederland", "person": "jan"}
        with mock.patch.object(hub_ip, "administrator_ip_allowed") as admin:
            self.assertTrue(hub_ip.login_ip_allowed(user, "80.12.34.56"))
        admin.assert_not_called()

    def test_missing_administrator_table_disables_bypass(self):
        from app import hub_ip

        cursor = mock.Mock()
        cursor.fetchone.return_value = (None,)
        with mock.patch.object(hub_ip, "_cursor", return_value=cursor):
            self.assertFalse(hub_ip.administrator_ip_allowed("80.12.34.56"))
        self.assertEqual(len(cursor.execute.call_args_list), 1)

    def test_administrator_table_matches_exact_ip(self):
        from app import hub_ip

        cursor = mock.Mock()
        cursor.fetchone.side_effect = [(123,), (1,)]
        with mock.patch.object(hub_ip, "_cursor", return_value=cursor):
            self.assertTrue(hub_ip.administrator_ip_allowed("80.12.34.56"))
        self.assertEqual(
            cursor.execute.call_args_list[-1].args[1],
            ("80.12.34.56",),
        )


class RecordVisitTests(unittest.TestCase):
    def setUp(self):
        from app import hub_ip

        patcher = mock.patch.object(
            hub_ip, "administrator_ip_allowed", return_value=False
        )
        self.is_administrator = patcher.start()
        self.addCleanup(patcher.stop)

    def test_refused_login_inserts_empty_username(self):
        from app import hub_ip

        cursor = mock.Mock()
        cursor.fetchone.side_effect = [(1,), None]
        conn = mock.Mock()
        with mock.patch.object(hub_ip, "_cursor", return_value=cursor), mock.patch(
            "app.user_store._sql_connect", return_value=conn
        ):
            hub_ip.record_visit("1.2.3.4", None)
        insert_sql, insert_params = cursor.execute.call_args_list[-1][0]
        self.assertIn("INSERT INTO dbo.visitor_ip", insert_sql)
        self.assertEqual(insert_params, ("1.2.3.4", ""))
        conn.commit.assert_called_once()

    def test_refused_login_skips_existing_empty_username(self):
        from app import hub_ip

        cursor = mock.Mock()
        cursor.fetchone.side_effect = [(1,), (9,)]
        conn = mock.Mock()
        with mock.patch.object(hub_ip, "_cursor", return_value=cursor), mock.patch(
            "app.user_store._sql_connect", return_value=conn
        ):
            hub_ip.record_visit("1.2.3.4", None)
        sqls = [call.args[0] for call in cursor.execute.call_args_list]
        self.assertFalse(any("INSERT INTO dbo.visitor_ip" in sql for sql in sqls))
        conn.commit.assert_not_called()

    def test_successful_login_stores_username(self):
        from app import hub_ip

        cursor = mock.Mock()
        cursor.fetchone.side_effect = [(1,), None]
        conn = mock.Mock()
        with mock.patch.object(hub_ip, "_cursor", return_value=cursor), mock.patch(
            "app.user_store._sql_connect", return_value=conn
        ):
            hub_ip.record_visit("1.2.3.4", "beheer")
        insert_sql, insert_params = cursor.execute.call_args_list[-1][0]
        self.assertIn("INSERT INTO dbo.visitor_ip", insert_sql)
        self.assertEqual(insert_params, ("1.2.3.4", "beheer"))

    def test_skips_loopback(self):
        from app import hub_ip

        with mock.patch.object(hub_ip, "_cursor") as cursor_fn:
            hub_ip.record_visit("127.0.0.1", None)
            hub_ip.record_visit("::1", "beheer")
        cursor_fn.assert_not_called()

    def test_skips_lan_addresses(self):
        from app import hub_ip

        with mock.patch.object(hub_ip, "_cursor") as cursor_fn:
            hub_ip.record_visit("192.168.1.50", None)
            hub_ip.record_visit("10.0.0.8", "beheer")
            hub_ip.record_visit("172.16.0.4", None)
        cursor_fn.assert_not_called()

    def test_skips_administrator_addresses(self):
        from app import hub_ip

        self.is_administrator.return_value = True
        with mock.patch.object(hub_ip, "_cursor") as cursor_fn:
            hub_ip.record_visit("80.12.34.56", "beheer")
            hub_ip.record_visit("80.12.34.56", None)
        cursor_fn.assert_not_called()

    def test_logs_visitor_whether_or_not_a_center_lists_it(self):
        from app import hub_ip

        cursor = mock.Mock()
        cursor.fetchone.side_effect = [(1,), None]
        conn = mock.Mock()
        with mock.patch.object(hub_ip, "_cursor", return_value=cursor), mock.patch(
            "app.user_store._sql_connect", return_value=conn
        ), mock.patch.object(hub_ip, "_egress_raw_for_user") as own_list:
            hub_ip.record_visit("80.12.34.56", "dkg")
        insert_sql, insert_params = cursor.execute.call_args_list[-1][0]
        self.assertIn("INSERT INTO dbo.visitor_ip", insert_sql)
        self.assertEqual(insert_params, ("80.12.34.56", "dkg"))
        own_list.assert_not_called()

    def test_unreadable_administrator_table_still_logs(self):
        from app import hub_ip

        self.is_administrator.side_effect = RuntimeError("no sql")
        cursor = mock.Mock()
        cursor.fetchone.side_effect = [(1,), None]
        conn = mock.Mock()
        with mock.patch.object(hub_ip, "_cursor", return_value=cursor), mock.patch(
            "app.user_store._sql_connect", return_value=conn
        ):
            hub_ip.record_visit("80.12.34.56", None)
        insert_sql, insert_params = cursor.execute.call_args_list[-1][0]
        self.assertIn("INSERT INTO dbo.visitor_ip", insert_sql)
        self.assertEqual(insert_params, ("80.12.34.56", ""))


class PublicEgressTests(unittest.TestCase):
    def test_router_wan_is_public_lan_is_not(self):
        from shared.net import first_public_egress, is_public_egress_ip

        self.assertTrue(is_public_egress_ip("80.12.34.56"))
        self.assertFalse(is_public_egress_ip("192.168.1.50"))
        self.assertFalse(is_public_egress_ip("127.0.0.1"))
        self.assertEqual(
            first_public_egress("127.0.0.1", "192.168.1.50", "80.12.34.56"),
            "80.12.34.56",
        )

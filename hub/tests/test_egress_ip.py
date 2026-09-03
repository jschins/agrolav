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

    def test_empty_is_unrestricted(self):
        self.assertTrue(ip_in_allowlist("9.9.9.9", []))
        self.assertTrue(ip_in_allowlist("9.9.9.9", parse_egress_list("")))

    def test_list_must_contain_client(self):
        allowed = parse_egress_list("10.0.0.1,10.0.0.2")
        self.assertTrue(ip_in_allowlist("10.0.0.1", allowed))
        self.assertFalse(ip_in_allowlist("8.8.8.8", allowed))

    def test_format_roundtrip(self):
        self.assertEqual(format_egress_list(["8.8.8.8", "1.1.1.1", "8.8.8.8"]), "8.8.8.8,1.1.1.1")
        self.assertIsNone(format_egress_list([]))


class RecordVisitTests(unittest.TestCase):
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

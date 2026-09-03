"""Country/center egress_ip allowlists."""
import unittest

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

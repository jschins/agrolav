"""Bank download ranges stay within Enable Banking's history limit."""
from __future__ import annotations

import unittest
from datetime import date

from app.bank import default_range


class BankRangeTests(unittest.TestCase):
    def test_default_range_stays_within_the_ninety_day_limit(self) -> None:
        start, end = default_range(date(2026, 10, 18))
        start_day = date.fromisoformat(start)
        end_day = date.fromisoformat(end)

        self.assertEqual(end, "2026-10-18")
        self.assertEqual((end_day - start_day).days, 89)
        self.assertEqual((end_day - start_day).days + 1, 90)


if __name__ == "__main__":
    unittest.main()

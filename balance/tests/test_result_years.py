"""Country-login year list on the resultaat window."""
from __future__ import annotations

import unittest

from app.result import country_years


class CountryYearsTests(unittest.TestCase):
    def test_next_opening_year_is_listed_and_is_not_the_default(self) -> None:
        years, default = country_years([2024, 2026], opening_for_next=True, today=2026)
        self.assertEqual(years, [2024, 2026, 2027])
        self.assertEqual(default, 2026)

    def test_without_an_opening_the_list_stays_on_booking_years(self) -> None:
        years, default = country_years([2026], opening_for_next=False, today=2026)
        self.assertEqual(years, [2026])
        self.assertEqual(default, 2026)

    def test_no_bookings_still_offers_the_next_year_when_an_opening_exists(self) -> None:
        years, default = country_years([], opening_for_next=True, today=2026)
        self.assertEqual(years, [2026, 2027])
        self.assertEqual(default, 2026)


if __name__ == "__main__":
    unittest.main()

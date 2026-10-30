import unittest
from datetime import date, datetime
from zoneinfo import ZoneInfo

from fantasy_scraper.timeutil import (parse_transaction_time, parse_week_ranges, parse_week_spec,
                                      rfc3339, season_start_year, week_for_date)

PT = ZoneInfo("America/Los_Angeles")
NOW = datetime(2026, 10, 29, 21, 0, tzinfo=PT)


class TimeTests(unittest.TestCase):
    def test_season_year(self):
        self.assertEqual(season_start_year(date(2026, 10, 29)), 2026)
        self.assertEqual(season_start_year(date(2027, 2, 1)), 2026)

    def test_week_ranges_cross_year(self):
        r = parse_week_ranges("Week 9 (Dec 29 - Jan 4) Week 10 (Jan 5 - Jan 11)", 2026)
        self.assertEqual(r[9], (date(2026, 12, 29), date(2027, 1, 4)))
        self.assertEqual(r[10][0], date(2027, 1, 5))

    def test_week_for_date(self):
        r = parse_week_ranges("Week 1 (Oct 20 - Oct 26) Week 2 (Oct 27 - Nov 2)", 2026)
        self.assertEqual(week_for_date(date(2026, 10, 28), r, None), 2)
        self.assertEqual(week_for_date(date(2026, 10, 20), r, None), 1)

    def test_transaction_times(self):
        t = parse_transaction_time("Oct 24, 10:23 am", NOW, 2026)
        self.assertEqual(t, datetime(2026, 10, 24, 10, 23, tzinfo=PT))
        self.assertEqual(parse_transaction_time("Today, 12:05 pm", NOW, 2026).hour, 12)
        y = parse_transaction_time("Yesterday, 8:05 pm", NOW, 2026)
        self.assertEqual((y.day, y.hour, y.minute), (28, 20, 5))
        self.assertEqual(parse_transaction_time("Jan 3, 12:00 am", NOW, 2026).year, 2027)
        self.assertIsNone(parse_transaction_time("no date here", NOW, 2026))

    def test_rfc3339(self):
        self.assertEqual(rfc3339(datetime(2026, 10, 24, 10, 23, tzinfo=PT)), "2026-10-24T10:23:00-07:00")

    def test_week_spec(self):
        self.assertEqual(parse_week_spec("last2", 5), [4, 5])
        self.assertEqual(parse_week_spec("last2", 1), [1])
        self.assertEqual(parse_week_spec("current", 5), [5])
        self.assertEqual(parse_week_spec("all", 3), [1, 2, 3])
        self.assertEqual(parse_week_spec("1-3", 9), [1, 2, 3])
        self.assertEqual(parse_week_spec("3,5", 9), [3, 5])


if __name__ == "__main__":
    unittest.main()

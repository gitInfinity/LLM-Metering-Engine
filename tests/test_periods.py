import unittest
from datetime import UTC, datetime, timedelta, timezone

from src.db.periods import quota_period


class QuotaPeriodTests(unittest.TestCase):
    def test_january_31_and_leap_year(self):
        for year, day in ((2026, 2), (2028, 1)):
            with self.subTest(year=year):
                signup = datetime(year, 1, 31, 12, tzinfo=UTC)
                start, end = quota_period(signup, signup)
                self.assertEqual(start, signup)
                self.assertEqual(end, datetime(year, 3, day, 12, tzinfo=UTC))
                self.assertEqual(end - start, timedelta(days=30))

    def test_exclusive_end_and_missed_resets(self):
        signup = datetime(2026, 1, 31, tzinfo=UTC)
        boundary = signup + timedelta(days=30)
        self.assertEqual(quota_period(signup, boundary - timedelta(microseconds=1))[0], signup)
        self.assertEqual(quota_period(signup, boundary)[0], boundary)
        self.assertEqual(
            quota_period(signup, signup + timedelta(days=95)),
            (signup + timedelta(days=90), signup + timedelta(days=120)),
        )

    def test_year_rollover(self):
        signup = datetime(2026, 12, 31, tzinfo=UTC)
        self.assertEqual(quota_period(signup, signup)[1], datetime(2027, 1, 30, tzinfo=UTC))

    def test_different_offsets_preserve_exact_elapsed_time(self):
        signup = datetime(2026, 3, 1, 12, tzinfo=timezone(timedelta(hours=-5)))
        later = datetime(2026, 3, 31, 13, tzinfo=timezone(timedelta(hours=-4)))
        start, end = quota_period(signup, later)
        self.assertEqual(start, datetime(2026, 3, 31, 17, tzinfo=UTC))
        self.assertEqual(end - start, timedelta(hours=720))

    def test_invalid_timestamps(self):
        signup = datetime(2026, 1, 31, tzinfo=UTC)
        for anchor, at in (
            (signup.replace(tzinfo=None), signup),
            (signup, signup.replace(tzinfo=None)),
            (signup, signup - timedelta(seconds=1)),
        ):
            with self.subTest(anchor=anchor, at=at), self.assertRaises(ValueError):
                quota_period(anchor, at)


if __name__ == "__main__":
    unittest.main()

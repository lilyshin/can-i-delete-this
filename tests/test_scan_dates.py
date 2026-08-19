"""Commit dates reach `scan.py` as git wrote them, and git writes `Z`.

`git log --format=%aI` renders a UTC offset as `Z`, not as `+00:00`.
`datetime.fromisoformat` did not accept `Z` until Python 3.11, and this
project supports 3.9, so a UTC-offset commit made every date unparseable
on 3.9 and 3.10: `age_days` came back None and the oldest-first ordering
silently degraded to whatever order the files were listed in.

It went unnoticed because both halves of the trap hide locally. A machine
in a non-UTC timezone gets `+09:00` from its own fixtures, and a machine
on 3.11 parses `Z` anyway. Only CI, which is UTC and runs 3.9, saw it.

So these tests are written to fail on 3.11 too. They pin the string that
reaches `fromisoformat` rather than the result of parsing it, because a
test that only checks the parsed value proves nothing on an interpreter
that accepts both forms.
"""

import os
import sys
import unittest
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(
    os.path.dirname(__file__), "..", "skills", "can-i-delete-this", "scripts"))

import scan as scanmod  # noqa: E402


class TestNormalizeOffset(unittest.TestCase):
    """The guarantee that survives every interpreter version: no `Z` is
    ever handed to `fromisoformat`."""

    def test_trailing_z_becomes_an_explicit_utc_offset(self):
        self.assertEqual(
            scanmod._normalize_offset("2021-06-14T09:12:00Z"),
            "2021-06-14T09:12:00+00:00")

    def test_lowercase_z_is_handled_too(self):
        self.assertEqual(
            scanmod._normalize_offset("2021-06-14T09:12:00z"),
            "2021-06-14T09:12:00+00:00")

    def test_a_numeric_offset_is_left_alone(self):
        for value in ("2021-06-14T09:12:00+09:00",
                      "2021-06-14T09:12:00-05:00",
                      "2021-06-14T09:12:00+00:00"):
            self.assertEqual(scanmod._normalize_offset(value), value)

    def test_a_z_inside_the_string_is_not_touched(self):
        """Only a trailing Z is an offset. Nothing else in a date is."""
        self.assertEqual(scanmod._normalize_offset("2021-06-14TZ9:12:00+09:00"),
                          "2021-06-14TZ9:12:00+09:00")

    def test_non_string_input_is_returned_unchanged(self):
        for value in (None, 0, [], {}):
            self.assertIs(scanmod._normalize_offset(value), value)


class TestParseDate(unittest.TestCase):

    def test_utc_offset_written_as_z_parses(self):
        when = scanmod._parse_date("2021-06-14T09:12:00Z")
        self.assertIsNotNone(when, "git writes a UTC offset as Z")
        self.assertEqual(when.utcoffset().total_seconds(), 0)

    def test_z_and_explicit_utc_are_the_same_instant(self):
        self.assertEqual(scanmod._parse_date("2021-06-14T09:12:00Z"),
                          scanmod._parse_date("2021-06-14T09:12:00+00:00"))

    def test_garbage_is_none_rather_than_an_exception(self):
        for value in ("", "not a date", None, 0):
            self.assertIsNone(scanmod._parse_date(value))


class TestAgeAndOrderingSurviveZ(unittest.TestCase):
    """The two user-visible consequences of the parse failure."""

    NOW = datetime(2026, 8, 13, tzinfo=timezone.utc)

    def test_age_is_computed_from_a_z_date(self):
        self.assertEqual(
            scanmod._age_days("2021-06-14T09:12:00Z", self.NOW), 1885)

    def test_z_dates_sort_by_instant_not_as_unknown(self):
        older = scanmod._instant("2020-03-01T00:00:00Z")
        newer = scanmod._instant("2021-06-14T09:12:00Z")
        self.assertLess(older, newer)
        self.assertNotEqual(older, scanmod._UNKNOWN_INSTANT)
        self.assertNotEqual(newer, scanmod._UNKNOWN_INSTANT)

    def test_a_z_date_and_a_numeric_offset_date_order_correctly(self):
        """Mixed offsets are the case string comparison got wrong, and an
        unparsed `Z` reintroduces it by sending one side to unknown."""
        seoul = scanmod._instant("2020-03-02T02:00:00+09:00")
        utc = scanmod._instant("2020-03-01T20:00:00Z")
        self.assertLess(seoul, utc, "17:00Z precedes 20:00Z")


if __name__ == "__main__":
    unittest.main()

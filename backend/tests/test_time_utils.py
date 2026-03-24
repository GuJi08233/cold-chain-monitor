import unittest
from datetime import datetime

from app.core.time_utils import (
    format_app_datetime,
    from_unix_seconds,
    normalize_app_datetime,
    parse_app_datetime,
    to_unix_seconds,
)


class TimeUtilsTests(unittest.TestCase):
    def test_parse_utc_text_to_app_timezone(self):
        parsed = parse_app_datetime("2026-03-24T00:09:46Z")
        self.assertEqual(parsed, datetime(2026, 3, 24, 8, 9, 46))

    def test_parse_naive_text_keeps_local_clock(self):
        parsed = parse_app_datetime("2026-03-24T08:09:46")
        self.assertEqual(parsed, datetime(2026, 3, 24, 8, 9, 46))

    def test_format_app_datetime_uses_local_text(self):
        text = format_app_datetime(datetime(2026, 3, 24, 8, 9, 46))
        self.assertEqual(text, "2026-03-24 08:09:46")

    def test_unix_roundtrip_uses_app_timezone(self):
        source = datetime(2026, 3, 24, 8, 9, 46)
        ts = to_unix_seconds(source)
        restored = from_unix_seconds(ts)
        self.assertEqual(restored, source)

    def test_normalize_aware_datetime(self):
        source = datetime.fromisoformat("2026-03-24T00:09:46+00:00")
        self.assertEqual(normalize_app_datetime(source), datetime(2026, 3, 24, 8, 9, 46))


if __name__ == "__main__":
    unittest.main()

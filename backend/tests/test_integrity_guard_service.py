import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from app.services.integrity_guard_service import IntegrityGuardService


class IntegrityGuardServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = IntegrityGuardService()

    def test_retry_due_uses_backoff(self):
        now = datetime(2026, 3, 25, 10, 0, 0)
        payload = {
            "retry_count": 2,
            "last_error_at": "2026-03-25 09:58:30",
        }
        with (
            patch.object(self.service, "_retry_interval_seconds", return_value=30),
            patch.object(self.service, "_retry_max_interval_seconds", return_value=900),
        ):
            self.assertFalse(self.service._is_retry_due(payload, None, now))

    def test_retry_due_when_wait_time_elapsed(self):
        now = datetime(2026, 3, 25, 10, 0, 0)
        payload = {
            "retry_count": 1,
            "last_error_at": "2026-03-25 09:58:30",
        }
        future_now = now + timedelta(seconds=61)
        with (
            patch.object(self.service, "_retry_interval_seconds", return_value=30),
            patch.object(self.service, "_retry_max_interval_seconds", return_value=900),
        ):
            self.assertTrue(self.service._is_retry_due(payload, None, future_now))

    def test_read_retry_anchor_falls_back_to_last_retry(self):
        payload = {
            "last_retry_at": "2026-03-25 10:00:00",
        }
        anchor = self.service._read_retry_anchor(payload)
        self.assertEqual(anchor, datetime(2026, 3, 25, 10, 0, 0))


if __name__ == "__main__":
    unittest.main()

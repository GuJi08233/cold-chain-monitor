import json
import unittest

from app.services.order_archive_service import OrderArchiveService


class OrderArchiveServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = OrderArchiveService()

    def test_from_value_returns_none_for_blank(self):
        self.assertIsNone(self.service._from_value("ORD001", ""))

    def test_from_value_parses_archive_payload(self):
        payload = json.dumps(
            {
                "archived": True,
                "reason": "测试归档",
                "archived_at": "2026-03-25 18:30:00",
                "archived_by": 1,
                "archived_by_name": "超级管理员",
            },
            ensure_ascii=False,
        )
        parsed = self.service._from_value("ORD001", payload)
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertTrue(parsed.is_archived)
        self.assertEqual(parsed.reason, "测试归档")
        self.assertEqual(parsed.archived_by, 1)


if __name__ == "__main__":
    unittest.main()

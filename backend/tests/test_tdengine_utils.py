import unittest

from app.services.tdengine_service import TdengineService


class TdengineUtilsTests(unittest.TestCase):
    def test_is_table_not_exists_by_code(self):
        payload = {"code": 9731, "desc": "anything"}
        self.assertTrue(TdengineService.is_table_not_exists(payload))

    def test_is_table_not_exists_by_message(self):
        payload = {"code": -1, "desc": "Fail to get table info, error: Table does not exist"}
        self.assertTrue(TdengineService.is_table_not_exists(payload))

    def test_is_table_not_exists_false_for_other_errors(self):
        payload = {"code": -1, "desc": "connection refused"}
        self.assertFalse(TdengineService.is_table_not_exists(payload))


if __name__ == "__main__":
    unittest.main()

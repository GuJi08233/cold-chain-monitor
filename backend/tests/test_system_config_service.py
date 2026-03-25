import unittest
from unittest.mock import patch

from app.services.system_config_service import ConfigValue, system_config_service


class SystemConfigServiceTests(unittest.TestCase):
    def test_get_text_falls_back_to_default_for_blank(self):
        with patch.object(
            system_config_service,
            "get_value",
            return_value=ConfigValue(key="app_timezone", value=""),
        ):
            self.assertEqual(
                system_config_service.get_text("app_timezone", default="Asia/Shanghai"),
                "Asia/Shanghai",
            )

    def test_get_bool_parses_true_false(self):
        with patch.object(
            system_config_service,
            "get_value",
            return_value=ConfigValue(key="chain_auto_retry_enabled", value="false"),
        ):
            self.assertFalse(
                system_config_service.get_bool("chain_auto_retry_enabled", default=True)
            )

    def test_get_int_enforces_minimum(self):
        with patch.object(
            system_config_service,
            "get_value",
            return_value=ConfigValue(key="hash_audit_interval_seconds", value="5"),
        ):
            self.assertEqual(
                system_config_service.get_int(
                    "hash_audit_interval_seconds",
                    default=300,
                    minimum=30,
                ),
                30,
            )


if __name__ == "__main__":
    unittest.main()

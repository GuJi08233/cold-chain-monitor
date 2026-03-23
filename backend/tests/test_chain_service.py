import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.models import ChainRecordType
from app.services.chain_service import ChainService, ChainWriteError


class ChainServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = ChainService()

    def test_load_contract_abi_from_bundled_file(self):
        abi = self.service._load_contract_abi()
        names = {item.get("name") for item in abi}
        self.assertIn("getOrderHashDigest", names)
        self.assertIn("startAnomalyLiteWithAnchor", names)
        self.assertIn("AnomalyStarted", names)

    def test_parse_anomaly_started_event_falls_back_to_lite_event(self):
        with patch.object(
            ChainService,
            "_process_receipt_events",
            side_effect=[[], [{"args": {"anomalyId": 12}}]],
        ):
            event_id = self.service._parse_anomaly_started_event(object(), object())
        self.assertEqual(event_id, 12)

    def test_dispatch_chain_write_reports_failed_start_dependency(self):
        row = SimpleNamespace(
            type=ChainRecordType.ANOMALY_END,
            anomaly_id=7,
            order_id="ORD_TEST",
        )
        with (
            patch.object(ChainService, "_resolve_chain_anomaly_id", return_value=None),
            patch.object(ChainService, "_has_pending_start_record", return_value=False),
            patch.object(ChainService, "_has_failed_start_record", return_value=True),
        ):
            with self.assertRaises(ChainWriteError) as exc:
                self.service._dispatch_chain_write(object(), row, {})
        self.assertIn("请先重试 anomaly_start", str(exc.exception))


if __name__ == "__main__":
    unittest.main()

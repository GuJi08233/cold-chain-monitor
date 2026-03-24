import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.api import chain as chain_api
from app.models import OrderStatus, UserRole


class ChainApiVerifyTests(unittest.TestCase):
    def test_verify_order_hash_recomputes_current_local_hash(self):
        order = SimpleNamespace(
            order_id="ORD20260324001_00091741",
            device_id="ESP32_A",
            driver_id=7,
            status=OrderStatus.COMPLETED,
            data_hash="stored-hash",
        )
        chain_record = SimpleNamespace(tx_hash="abc123", block_number=12)
        current_user = SimpleNamespace(role=UserRole.ADMIN, user_id=1)
        db = SimpleNamespace(
            scalar=Mock(side_effect=[order, chain_record]),
        )

        with (
            patch.object(
                chain_api.hash_service,
                "compute_order_hash_streaming",
                return_value="recomputed-hash",
            ) as compute_mock,
            patch.object(
                chain_api.chain_service,
                "get_order_hash",
                return_value={
                    "data_hash": "chain-hash",
                    "timestamp": 0,
                    "data_hash_mode": "digest",
                    "uploader": "0xabc",
                },
            ),
            patch.object(
                chain_api.chain_service,
                "verify_order_hash",
                return_value=False,
            ) as verify_mock,
        ):
            result = chain_api.verify_order_hash(
                order.order_id,
                current_user=current_user,
                db=db,
            )

        self.assertEqual(result["data"]["local_hash"], "recomputed-hash")
        self.assertEqual(result["data"]["stored_hash"], "stored-hash")
        self.assertFalse(result["data"]["match"])
        self.assertTrue(result["data"]["local_hash_changed"])
        self.assertEqual(result["data"]["tx_hash"], "0xabc123")
        compute_mock.assert_called_once_with(
            device_id=order.device_id,
            order_id=order.order_id,
        )
        verify_mock.assert_called_once_with(order.order_id, "recomputed-hash")


if __name__ == "__main__":
    unittest.main()

import base64
import json
import os
import unittest
from unittest.mock import patch

from Crypto.Cipher import AES
from Crypto.Util.Padding import pad

from app.services.crypto_service import CryptoService
from app.services.hash_service import HashService
from app.services.tdengine_service import TdengineResult


class CryptoHashTests(unittest.TestCase):
    def setUp(self) -> None:
        self.crypto_service = CryptoService()
        self.hash_service = HashService()
        self.test_key = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"

    def test_encrypt_decrypt_roundtrip(self):
        payload = {
            "driver_name": "zhangsan",
            "id_card": "440000000000000000",
            "phone": "13800000001",
            "cargo_name": "fresh",
        }
        encrypted = self.crypto_service.encrypt_dict(payload, key_hex=self.test_key)
        decrypted = self.crypto_service.decrypt_to_dict(encrypted, key_hex=self.test_key)
        self.assertEqual(decrypted, payload)

    def test_encrypt_uses_gcm_prefix(self):
        encrypted = self.crypto_service.encrypt_dict({"k": "v"}, key_hex=self.test_key)
        self.assertTrue(encrypted.startswith("gcm:"))

    def test_decrypt_legacy_cbc_ciphertext(self):
        payload = {"driver_name": "zhangsan", "id_card": "440000000000000000"}
        key = bytes.fromhex(self.test_key)
        plaintext = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        iv = os.urandom(16)
        cipher = AES.new(key, AES.MODE_CBC, iv)
        ciphertext = cipher.encrypt(pad(plaintext, AES.block_size))
        legacy = base64.b64encode(iv + ciphertext).decode("ascii")

        decrypted = self.crypto_service.decrypt_to_dict(legacy, key_hex=self.test_key)
        self.assertEqual(decrypted, payload)

    def test_gcm_tamper_is_detected(self):
        encrypted = self.crypto_service.encrypt_dict({"driver_name": "zhangsan"}, key_hex=self.test_key)
        raw = base64.b64decode(encrypted[4:].encode("ascii"))
        tampered = raw[:-1] + bytes([raw[-1] ^ 1])
        tampered_text = "gcm:" + base64.b64encode(tampered).decode("ascii")
        with self.assertRaises(Exception):
            self.crypto_service.decrypt_to_dict(tampered_text, key_hex=self.test_key)

    def test_hash_is_deterministic(self):
        records = [
            {
                "ts": "2026-02-13T03:00:00.000Z",
                "temperature": 23.214,
                "humidity": 68.126,
                "pressure": 1018.558,
                "gps_lat": 23.16625111,
                "gps_lng": 113.63529199,
                "uptime": 100,
            },
            {
                "ts": "2026-02-13T03:00:02.000Z",
                "temperature": 23.205,
                "humidity": 68.114,
                "pressure": 1018.551,
                "gps_lat": 23.16625118,
                "gps_lng": 113.63529201,
                "uptime": 102,
            },
        ]
        hash1 = self.hash_service.compute_hash_from_records(records)
        hash2 = self.hash_service.compute_hash_from_records(records)
        self.assertEqual(hash1, hash2)
        self.assertEqual(len(hash1), 64)

    def test_streaming_hash_handles_missing_td_table(self):
        missing_table_result = TdengineResult(
            ok=False,
            payload={"code": 9731, "desc": "Table does not exist"},
        )
        with patch(
            "app.services.hash_service.tdengine_service.query_sensor_after_ts",
            return_value=missing_table_result,
        ):
            digest = self.hash_service.compute_order_hash_streaming(
                device_id="dev_test",
                order_id="ord_test",
                batch_size=10,
            )
        self.assertEqual(digest, self.hash_service.compute_hash_from_records([]))


if __name__ == "__main__":
    unittest.main()

import base64
import json
import os

from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad

from .system_config_service import system_config_service


class CryptoService:
    @staticmethod
    def _key_from_hex(key_hex: str) -> bytes:
        key = bytes.fromhex(key_hex)
        if len(key) != 32:
            raise ValueError("AES-256 密钥必须是 64 位 hex 字符串")
        return key

    def get_chain_aes_key(self) -> str:
        config = system_config_service.get_value("eth_aes_key", decrypt_sensitive=True)
        if not config.value:
            raise ValueError("系统未配置 eth_aes_key")
        return config.value

    def encrypt_dict(self, data: dict, key_hex: str | None = None) -> str:
        key_value = key_hex or self.get_chain_aes_key()
        key = self._key_from_hex(key_value)
        plaintext = json.dumps(data, ensure_ascii=False, sort_keys=True).encode("utf-8")
        nonce = os.urandom(12)
        cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
        ciphertext, tag = cipher.encrypt_and_digest(plaintext)
        payload = nonce + tag + ciphertext
        return f"gcm:{base64.b64encode(payload).decode('ascii')}"

    def decrypt_to_dict(self, encrypted_value: str, key_hex: str | None = None) -> dict:
        key_value = key_hex or self.get_chain_aes_key()
        key = self._key_from_hex(key_value)
        text = encrypted_value.strip()
        if text.startswith("gcm:"):
            raw = base64.b64decode(text[4:].encode("ascii"))
            nonce = raw[:12]
            tag = raw[12:28]
            ciphertext = raw[28:]
            cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
            plaintext = cipher.decrypt_and_verify(ciphertext, tag)
        else:
            # 兼容历史 CBC 密文（Base64(IV + ciphertext)）
            raw = base64.b64decode(text)
            iv = raw[:16]
            ciphertext = raw[16:]
            cipher = AES.new(key, AES.MODE_CBC, iv)
            plaintext = unpad(cipher.decrypt(ciphertext), AES.block_size)
        return json.loads(plaintext.decode("utf-8"))


crypto_service = CryptoService()

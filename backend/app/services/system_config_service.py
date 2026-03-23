import base64
import hashlib
import os
from dataclasses import dataclass

from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import SessionLocal
from ..models import SystemConfig

SENSITIVE_CONFIG_KEYS = {
    "eth_private_key",
    "eth_aes_key",
    "mqtt_password",
    "tdengine_password",
}


def _derive_app_secret_key_bytes() -> bytes:
    raw = get_settings().app_secret_key
    if len(raw) == 64:
        try:
            return bytes.fromhex(raw)
        except ValueError:
            pass
    return hashlib.sha256(raw.encode("utf-8")).digest()


def _encrypt_with_app_key(plaintext: str) -> str:
    key = _derive_app_secret_key_bytes()
    nonce = os.urandom(12)
    cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
    ciphertext, tag = cipher.encrypt_and_digest(plaintext.encode("utf-8"))
    payload = nonce + tag + ciphertext
    return f"gcm:{base64.b64encode(payload).decode('ascii')}"


def _decrypt_with_app_key(ciphertext_base64: str) -> str:
    key = _derive_app_secret_key_bytes()
    if ciphertext_base64.startswith("gcm:"):
        raw = base64.b64decode(ciphertext_base64[4:].encode("ascii"))
        nonce = raw[:12]
        tag = raw[12:28]
        ciphertext = raw[28:]
        cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
        plaintext = cipher.decrypt_and_verify(ciphertext, tag)
        return plaintext.decode("utf-8")

    # 兼容历史 CBC 密文。
    raw = base64.b64decode(ciphertext_base64.encode("ascii"))
    iv = raw[:16]
    ciphertext = raw[16:]
    cipher = AES.new(key, AES.MODE_CBC, iv)
    plaintext = unpad(cipher.decrypt(ciphertext), AES.block_size)
    return plaintext.decode("utf-8")


@dataclass
class ConfigValue:
    key: str
    value: str | None


class SystemConfigService:
    @staticmethod
    def _to_stored_value(key: str, value: str) -> str:
        if key in SENSITIVE_CONFIG_KEYS and value:
            return _encrypt_with_app_key(value)
        return value

    def _upsert_value(self, db: Session, key: str, value: str) -> None:
        row = db.scalar(select(SystemConfig).where(SystemConfig.key == key).limit(1))
        stored_value = self._to_stored_value(key, value)
        if row is None:
            row = SystemConfig(key=key, value=stored_value)
            db.add(row)
            return
        row.value = stored_value
        db.add(row)

    def get_value(self, key: str, decrypt_sensitive: bool = True) -> ConfigValue:
        with SessionLocal() as db:
            row = db.scalar(select(SystemConfig).where(SystemConfig.key == key).limit(1))
            if row is None:
                return ConfigValue(key=key, value=None)
            value = row.value
            if decrypt_sensitive and key in SENSITIVE_CONFIG_KEYS and value:
                try:
                    value = _decrypt_with_app_key(value)
                except Exception:  # noqa: BLE001
                    # 兼容历史明文值
                    pass
            return ConfigValue(key=key, value=value)

    def set_value(
        self,
        key: str,
        value: str,
        *,
        db: Session | None = None,
        commit: bool = True,
    ) -> None:
        if db is not None:
            self._upsert_value(db, key, value)
            if commit:
                db.commit()
            return

        with SessionLocal() as local_db:
            self._upsert_value(local_db, key, value)
            if commit:
                local_db.commit()


system_config_service = SystemConfigService()

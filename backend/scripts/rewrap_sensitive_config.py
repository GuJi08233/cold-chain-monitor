from __future__ import annotations

import argparse
import base64
import hashlib
from pathlib import Path
import sys

from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad
from sqlalchemy import select

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.database import SessionLocal
from app.models import SystemConfig
from app.services.system_config_service import SENSITIVE_CONFIG_KEYS, system_config_service


def _derive_key(raw_secret: str) -> bytes:
    raw = raw_secret.strip()
    if len(raw) == 64:
        try:
            return bytes.fromhex(raw)
        except ValueError:
            pass
    return hashlib.sha256(raw.encode("utf-8")).digest()


def _decrypt_with_secret(ciphertext_base64: str, raw_secret: str) -> str:
    blob = base64.b64decode(ciphertext_base64.encode("ascii"))
    iv = blob[:16]
    ciphertext = blob[16:]
    cipher = AES.new(_derive_key(raw_secret), AES.MODE_CBC, iv)
    plaintext = unpad(cipher.decrypt(ciphertext), AES.block_size)
    return plaintext.decode("utf-8")


def _mask(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "****"
    return f"{value[:4]}...{value[-4:]}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="使用旧 APP_SECRET_KEY 重新包装敏感配置")
    parser.add_argument(
        "--old-app-secret",
        required=True,
        help="旧的 APP_SECRET_KEY 值",
    )
    parser.add_argument(
        "--keys",
        nargs="*",
        default=sorted(SENSITIVE_CONFIG_KEYS),
        help="需要迁移的配置键，默认全部敏感键",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    target_keys = [key for key in args.keys if key in SENSITIVE_CONFIG_KEYS]
    if not target_keys:
        print("[WARN] 未指定有效敏感键，退出")
        return 1

    with SessionLocal() as db:
        rows = {
            row.key: row.value
            for row in db.scalars(select(SystemConfig).where(SystemConfig.key.in_(target_keys))).all()
        }

    migrated = 0
    for key in target_keys:
        raw_value = rows.get(key) or ""
        if not raw_value:
            print(f"[SKIP] {key}=<empty>")
            continue
        try:
            plaintext = _decrypt_with_secret(raw_value, args.old_app_secret)
        except Exception as exc:  # noqa: BLE001
            print(f"[FAIL] {key}: 旧密钥解密失败 -> {exc}")
            continue

        system_config_service.set_value(key, plaintext)
        print(f"[OK] {key}={_mask(plaintext)}")
        migrated += 1

    print(f"[DONE] 迁移完成: {migrated}/{len(target_keys)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

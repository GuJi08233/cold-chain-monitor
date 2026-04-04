from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..core.security import hash_password, validate_password_strength
from ..database import SessionLocal, engine
from ..models import Base, SystemConfig, User, UserRole, UserStatus

SYSTEM_CONFIG_META: dict[str, dict[str, object]] = {
    "app_timezone": {
        "group": "system",
        "label": "应用时区",
        "input_type": "timezone",
    },
    "chain_auto_retry_enabled": {
        "group": "system",
        "label": "启用自动重试",
        "input_type": "boolean",
    },
    "chain_auto_retry_interval_seconds": {
        "group": "system",
        "label": "自动重试扫描间隔（秒）",
        "input_type": "number",
        "min": 5,
    },
    "chain_auto_retry_max_interval_seconds": {
        "group": "system",
        "label": "自动重试最大退避（秒）",
        "input_type": "number",
        "min": 5,
    },
    "chain_auto_retry_batch_size": {
        "group": "system",
        "label": "自动重试单轮批量数",
        "input_type": "number",
        "min": 1,
    },
    "hash_audit_enabled": {
        "group": "system",
        "label": "启用自动哈希巡检",
        "input_type": "boolean",
    },
    "hash_audit_interval_seconds": {
        "group": "system",
        "label": "哈希巡检间隔（秒）",
        "input_type": "number",
        "min": 30,
    },
    "hash_audit_batch_size": {
        "group": "system",
        "label": "哈希巡检单轮批量数",
        "input_type": "number",
        "min": 1,
    },
    "eth_rpc_url": {
        "group": "eth",
        "label": "ETH RPC URL（主）",
        "input_type": "text",
    },
    "eth_rpc_url_backup": {
        "group": "eth",
        "label": "ETH RPC URL（备用）",
        "input_type": "text",
    },
    "eth_contract_address": {
        "group": "eth",
        "label": "合约地址",
        "input_type": "text",
    },
    "eth_private_key": {
        "group": "eth",
        "label": "链上私钥",
        "input_type": "password",
    },
    "eth_aes_key": {
        "group": "eth",
        "label": "链上 AES 密钥",
        "input_type": "password",
    },
    "tdengine_host": {
        "group": "tdengine",
        "label": "TDengine 主机",
        "input_type": "text",
    },
    "tdengine_port": {
        "group": "tdengine",
        "label": "TDengine 端口（兼容项）",
        "input_type": "number",
        "min": 1,
    },
    "tdengine_native_port": {
        "group": "tdengine",
        "label": "TDengine 原生端口",
        "input_type": "number",
        "min": 1,
    },
    "tdengine_rest_port": {
        "group": "tdengine",
        "label": "TDengine REST 端口",
        "input_type": "number",
        "min": 1,
    },
    "tdengine_db": {
        "group": "tdengine",
        "label": "TDengine 数据库",
        "input_type": "text",
    },
    "tdengine_user": {
        "group": "tdengine",
        "label": "TDengine 用户名",
        "input_type": "text",
    },
    "tdengine_password": {
        "group": "tdengine",
        "label": "TDengine 密码",
        "input_type": "password",
    },
    "mqtt_broker": {
        "group": "mqtt",
        "label": "MQTT Broker",
        "input_type": "text",
    },
    "mqtt_port": {
        "group": "mqtt",
        "label": "MQTT 端口",
        "input_type": "number",
        "min": 1,
    },
    "mqtt_username": {
        "group": "mqtt",
        "label": "MQTT 用户名",
        "input_type": "text",
    },
    "mqtt_password": {
        "group": "mqtt",
        "label": "MQTT 密码",
        "input_type": "password",
    },
    "mqtt_topic": {
        "group": "mqtt",
        "label": "MQTT 主题",
        "input_type": "text",
    },
    "mqtt_client_id": {
        "group": "mqtt",
        "label": "MQTT Client ID",
        "input_type": "text",
    },
}

DEFAULT_SYSTEM_CONFIG_KEYS = list(SYSTEM_CONFIG_META.keys())
BOOLEAN_SYSTEM_CONFIG_KEYS = {
    key for key, meta in SYSTEM_CONFIG_META.items() if meta.get("input_type") == "boolean"
}
NUMBER_SYSTEM_CONFIG_KEYS = {
    key for key, meta in SYSTEM_CONFIG_META.items() if meta.get("input_type") == "number"
}


def initialize_database() -> None:
    Base.metadata.create_all(bind=engine)


def initialize_app_state() -> None:
    initialize_database()
    with SessionLocal() as db:
        create_super_admin_if_missing(db)
        ensure_system_config_keys(db)


def create_super_admin_if_missing(db: Session) -> None:
    settings = get_settings()

    existing_super_admin = db.scalar(
        select(User).where(User.role == UserRole.SUPER_ADMIN).limit(1)
    )
    if existing_super_admin:
        return

    username_exists = db.scalar(
        select(User).where(User.username == settings.super_admin_username).limit(1)
    )
    if username_exists:
        raise RuntimeError(
            f"用户名 `{settings.super_admin_username}` 已存在，无法初始化 super_admin。"
        )

    insecure_passwords = {"replace-with-strong-admin-password"}
    if settings.super_admin_password.strip() in insecure_passwords:
        raise RuntimeError(
            "检测到占位 SUPER_ADMIN_PASSWORD，请先修改 .env 后再启动服务。"
        )

    validate_password_strength(settings.super_admin_password)
    new_admin = User(
        username=settings.super_admin_username,
        password_hash=hash_password(settings.super_admin_password),
        role=UserRole.SUPER_ADMIN,
        status=UserStatus.ACTIVE,
        display_name="超级管理员",
    )
    db.add(new_admin)
    db.commit()


def ensure_system_config_keys(db: Session) -> None:
    existing_rows = db.execute(select(SystemConfig.key)).all()
    existing_keys = {row[0] for row in existing_rows}

    missing_keys = [key for key in DEFAULT_SYSTEM_CONFIG_KEYS if key not in existing_keys]
    if not missing_keys:
        return

    for key in missing_keys:
        db.add(SystemConfig(key=key, value=""))
    db.commit()

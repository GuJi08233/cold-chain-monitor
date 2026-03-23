from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..core.security import hash_password, validate_password_strength
from ..database import SessionLocal, engine
from ..models import Base, SystemConfig, User, UserRole, UserStatus

DEFAULT_SYSTEM_CONFIG_KEYS = [
    "eth_rpc_url",
    "eth_contract_address",
    "eth_private_key",
    "tdengine_host",
    "tdengine_port",
    "tdengine_native_port",
    "tdengine_rest_port",
    "tdengine_db",
    "tdengine_user",
    "tdengine_password",
    "mqtt_broker",
    "mqtt_port",
    "mqtt_username",
    "mqtt_password",
    "mqtt_topic",
    "mqtt_client_id",
    "eth_aes_key",
]


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

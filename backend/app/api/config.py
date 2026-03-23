import base64
import json
import threading
import uuid
from urllib import error, request

import paho.mqtt.client as mqtt
from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..core.auth import require_role
from ..core.deps import get_db_session
from ..core.response import success_response
from ..models import SystemConfig, User, UserRole
from ..services.chain_service import ChainServiceError, chain_service
from ..services.init_service import DEFAULT_SYSTEM_CONFIG_KEYS
from ..services.system_config_service import SENSITIVE_CONFIG_KEYS, system_config_service

router = APIRouter(prefix="/config", tags=["config"])
settings = get_settings()


def _serialize_config_item(key: str, value: str, *, stored_value: str) -> dict:
    is_sensitive = key in SENSITIVE_CONFIG_KEYS
    is_set = bool((stored_value or "").strip())
    # 敏感项只返回占位信息，禁止回显历史值（即使是密文也不返回）。
    safe_value = "" if is_sensitive else (value or "")
    return {
        "key": key,
        "value": safe_value,
        "is_sensitive": is_sensitive,
        "is_set": is_set,
    }


def _load_config_items(db: Session) -> list[dict]:
    rows = db.scalars(select(SystemConfig).order_by(SystemConfig.key.asc())).all()
    items: list[dict] = []
    for row in rows:
        items.append(_serialize_config_item(row.key, row.value, stored_value=row.value))
    return items


def _load_config_map(db: Session) -> dict[str, str]:
    """用于内部读取配置（如联通性测试），敏感项会解密用于连接，不对外回显。"""
    rows = db.scalars(select(SystemConfig).order_by(SystemConfig.key.asc())).all()
    result: dict[str, str] = {}
    for row in rows:
        if row.key in SENSITIVE_CONFIG_KEYS:
            result[row.key] = system_config_service.get_value(
                row.key,
                decrypt_sensitive=True,
            ).value or ""
        else:
            result[row.key] = row.value
    return result


def _read_config_or_default(config_map: dict[str, str], key: str, default_value) -> str:
    value = (config_map.get(key) or "").strip()
    if value:
        return value
    return str(default_value)


@router.get("")
def get_system_config(
    db: Session = Depends(get_db_session),
    _: User = Depends(require_role(UserRole.SUPER_ADMIN)),
) -> dict:
    return success_response(data=_load_config_items(db))


@router.put("")
def update_system_config(
    payload: dict[str, str] = Body(...),
    db: Session = Depends(get_db_session),
    _: User = Depends(require_role(UserRole.SUPER_ADMIN)),
) -> dict:
    if not payload:
        raise HTTPException(status_code=400, detail="配置内容不能为空")

    unknown_keys = sorted(set(payload.keys()) - set(DEFAULT_SYSTEM_CONFIG_KEYS))
    if unknown_keys:
        raise HTTPException(status_code=400, detail=f"存在未知配置键: {', '.join(unknown_keys)}")

    try:
        for key, value in payload.items():
            text = str(value)
            # 敏感项留空表示“不修改”，避免前端空值覆盖导致配置丢失。
            if key in SENSITIVE_CONFIG_KEYS and not text.strip():
                continue
            system_config_service.set_value(key, text, db=db, commit=False)
        db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        raise HTTPException(status_code=500, detail=f"系统配置更新失败: {exc}") from exc

    db.expire_all()
    refreshed = _load_config_items(db)
    return success_response(
        data=refreshed,
        msg="系统配置更新成功",
    )


@router.post("/test-mqtt")
def test_mqtt_config(
    db: Session = Depends(get_db_session),
    _: User = Depends(require_role(UserRole.SUPER_ADMIN)),
) -> dict:
    config_map = _load_config_map(db)
    broker = _read_config_or_default(config_map, "mqtt_broker", settings.mqtt_broker)
    port = int(_read_config_or_default(config_map, "mqtt_port", settings.mqtt_port))
    username = (config_map.get("mqtt_username") or "").strip() or None
    password = (config_map.get("mqtt_password") or "").strip() or None

    def _reason_code_value(reason_code) -> int:
        value = getattr(reason_code, "value", reason_code)
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            if value.isdigit():
                return int(value)
            return 0 if value.lower() == "success" else -1
        return -1

    connected_event = threading.Event()
    connect_result = {"code": None}

    def _on_connect(_client, _userdata, _flags, reason_code, _properties=None):
        connect_result["code"] = _reason_code_value(reason_code)
        connected_event.set()

    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id=f"cfg_test_{uuid.uuid4().hex[:8]}",
        clean_session=True,
    )
    client.on_connect = _on_connect
    if username:
        client.username_pw_set(username, password)

    try:
        result_code = client.connect(broker, port, keepalive=10)
        if result_code != 0:
            raise RuntimeError(f"MQTT 连接失败，返回码: {result_code}")
        client.loop_start()
        if not connected_event.wait(timeout=6):
            raise RuntimeError("MQTT 连接超时（未收到 CONNACK）")
        reason_code = connect_result["code"]
        if reason_code != 0:
            raise RuntimeError(f"MQTT 连接被拒绝，返回码: {reason_code}")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"MQTT 连接测试失败: {exc}") from exc
    finally:
        try:
            client.loop_stop()
            client.disconnect()
        except Exception:  # noqa: BLE001
            pass

    return success_response(data={"broker": broker, "port": port}, msg="MQTT 连接测试通过")


@router.post("/test-tdengine")
def test_tdengine_config(
    db: Session = Depends(get_db_session),
    _: User = Depends(require_role(UserRole.SUPER_ADMIN)),
) -> dict:
    config_map = _load_config_map(db)
    host = _read_config_or_default(config_map, "tdengine_host", settings.tdengine_host)
    port = int(_read_config_or_default(config_map, "tdengine_rest_port", settings.tdengine_rest_port))
    username = _read_config_or_default(config_map, "tdengine_user", settings.tdengine_username)
    password = _read_config_or_default(config_map, "tdengine_password", settings.tdengine_password)
    rest_url = f"http://{host}:{port}/rest/sql"

    auth_raw = f"{username}:{password}"
    auth = base64.b64encode(auth_raw.encode("utf-8")).decode("utf-8")
    req = request.Request(
        rest_url,
        data=b"SHOW DATABASES;",
        method="POST",
        headers={
            "Content-Type": "text/plain; charset=utf-8",
            "Authorization": f"Basic {auth}",
        },
    )
    try:
        with request.urlopen(req, timeout=8) as resp:
            body = resp.read().decode("utf-8")
            payload = json.loads(body) if body else {}
            if int(payload.get("code", -1)) != 0:
                raise RuntimeError(payload.get("desc") or payload)
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise HTTPException(status_code=400, detail=f"TDengine 连接测试失败: {detail}") from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"TDengine 连接测试失败: {exc}") from exc

    return success_response(data={"host": host, "port": port}, msg="TDengine 连接测试通过")


@router.post("/test-eth")
def test_eth_config(
    _: User = Depends(require_role(UserRole.SUPER_ADMIN)),
) -> dict:
    try:
        result = chain_service.test_connection()
    except ChainServiceError as exc:
        raise HTTPException(status_code=400, detail=f"ETH 连接测试失败: {exc}") from exc
    return success_response(data=result, msg="ETH 连接测试通过")

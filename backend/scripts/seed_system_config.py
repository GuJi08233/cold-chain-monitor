from pathlib import Path
import json
import sys

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.config import get_settings
from app.services.system_config_service import SENSITIVE_CONFIG_KEYS, system_config_service


def _deployment_files_for_rpc(rpc_url: str | None) -> list[Path]:
    rpc_text = (rpc_url or "").strip().lower()
    chain_ids = ["chain-11155111", "chain-233"]
    if "chain-233" in rpc_text or "aly" in rpc_text or ":2333" in rpc_text:
        chain_ids = ["chain-233", "chain-11155111"]
    elif "11155111" in rpc_text or "sepolia" in rpc_text:
        chain_ids = ["chain-11155111", "chain-233"]

    return [
        ROOT_DIR.parent / "hardhat" / "ignition" / "deployments" / chain_id / "deployed_addresses.json"
        for chain_id in chain_ids
    ]


def _read_contract_address_from_hardhat(rpc_url: str | None) -> str:
    for deployment_file in _deployment_files_for_rpc(rpc_url):
        if not deployment_file.exists():
            continue
        try:
            data = json.loads(deployment_file.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        for key in (
            "ColdChainMonitorV3R2Module#ColdChainMonitorV3",
            "ColdChainMonitorV3Module#ColdChainMonitorV3",
            "ColdChainMonitorV2Module#ColdChainMonitorV2",
            "ColdChainMonitorModule#ColdChainMonitor",
        ):
            value = str(data.get(key) or "").strip()
            if value:
                return value
    return ""


def _mask_value(key: str, value: str) -> str:
    if key not in SENSITIVE_CONFIG_KEYS:
        return value
    if not value:
        return ""
    if len(value) <= 8:
        return "****"
    return f"{value[:4]}...{value[-4:]}"


def main() -> int:
    settings = get_settings()
    config_map = {
        "app_timezone": settings.app_timezone,
        "chain_auto_retry_enabled": str(settings.chain_auto_retry_enabled).lower(),
        "chain_auto_retry_interval_seconds": str(settings.chain_auto_retry_interval_seconds),
        "chain_auto_retry_max_interval_seconds": str(settings.chain_auto_retry_max_interval_seconds),
        "chain_auto_retry_batch_size": str(settings.chain_auto_retry_batch_size),
        "hash_audit_enabled": str(settings.hash_audit_enabled).lower(),
        "hash_audit_interval_seconds": str(settings.hash_audit_interval_seconds),
        "hash_audit_batch_size": str(settings.hash_audit_batch_size),
        "mqtt_broker": settings.mqtt_broker,
        "mqtt_port": str(settings.mqtt_port),
        "mqtt_username": settings.mqtt_username or "",
        "mqtt_password": settings.mqtt_password or "",
        "mqtt_topic": settings.mqtt_topic,
        "mqtt_client_id": settings.mqtt_client_id,
        "tdengine_host": settings.tdengine_host,
        "tdengine_native_port": str(settings.tdengine_native_port),
        "tdengine_rest_port": str(settings.tdengine_rest_port),
        "tdengine_port": str(settings.tdengine_rest_port),
        "tdengine_user": settings.tdengine_username,
        "tdengine_password": settings.tdengine_password,
        "tdengine_db": settings.tdengine_db,
        "eth_rpc_url": (settings.eth_rpc_url or "").strip(),
        "eth_contract_address": (
            (settings.eth_contract_address or "").strip()
            or _read_contract_address_from_hardhat(settings.eth_rpc_url)
        ),
        "eth_private_key": (settings.eth_private_key or "").strip(),
        "eth_aes_key": (settings.eth_aes_key or "").strip(),
    }

    for key, value in config_map.items():
        system_config_service.set_value(key, value)
        print(f"[OK] {key}={_mask_value(key, value)}")

    print("[DONE] system_config 已同步系统运行/MQTT/TDengine/ETH 配置")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

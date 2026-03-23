import argparse
import json
import time
from dataclasses import dataclass
from pathlib import Path
import sys

import paho.mqtt.client as mqtt

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.config import get_settings


@dataclass
class ProbeState:
    connected: bool = False
    connect_error: str | None = None
    message_count: int = 0
    last_payload: str | None = None
    last_topic: str | None = None


def main() -> int:
    parser = argparse.ArgumentParser(description="MQTT 订阅探活")
    parser.add_argument(
        "--seconds",
        type=int,
        default=10,
        help="订阅监听秒数（默认 10）",
    )
    args = parser.parse_args()

    settings = get_settings()
    state = ProbeState()

    def normalize_reason_code(reason_code) -> int:
        value = getattr(reason_code, "value", reason_code)
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            if value.isdigit():
                return int(value)
            return 0 if value.lower() == "success" else -1
        return -1

    def on_connect(
        client: mqtt.Client,
        _userdata,
        _flags,
        reason_code,
        _properties=None,
    ) -> None:
        code = normalize_reason_code(reason_code)
        if code != 0:
            state.connect_error = f"连接失败，reason_code={reason_code}"
            return
        state.connected = True
        client.subscribe(settings.mqtt_topic, qos=1)

    def on_message(_client: mqtt.Client, _userdata, msg: mqtt.MQTTMessage) -> None:
        state.message_count += 1
        state.last_topic = msg.topic
        state.last_payload = msg.payload.decode("utf-8", errors="replace")

    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id=settings.mqtt_client_id,
        clean_session=True,
    )
    if settings.mqtt_username:
        client.username_pw_set(settings.mqtt_username, settings.mqtt_password)

    client.on_connect = on_connect
    client.on_message = on_message

    print(f"[MQTT] Broker: {settings.mqtt_broker}:{settings.mqtt_port}")
    print(f"[MQTT] Topic: {settings.mqtt_topic}")
    print(f"[MQTT] Client ID: {settings.mqtt_client_id}")

    try:
        client.connect(settings.mqtt_broker, settings.mqtt_port, keepalive=30)
    except Exception as exc:  # noqa: BLE001
        print(f"[FAIL] MQTT 连接异常: {exc}")
        return 1

    client.loop_start()
    wait_start = time.time()
    while not state.connected and time.time() - wait_start < 5:
        if state.connect_error:
            break
        time.sleep(0.1)

    if not state.connected:
        client.loop_stop()
        client.disconnect()
        print(f"[FAIL] MQTT 未连接成功: {state.connect_error or '超时'}")
        return 1

    print(f"[INFO] 已连接，开始监听 {args.seconds} 秒...")
    time.sleep(max(1, args.seconds))
    client.loop_stop()
    client.disconnect()

    print(f"[DONE] 收到消息数: {state.message_count}")
    if state.last_payload:
        print(f"[DONE] 最后一条 Topic: {state.last_topic}")
        try:
            parsed = json.loads(state.last_payload)
            print(
                "[DONE] 最后一条消息(JSON预览):",
                json.dumps(parsed, ensure_ascii=False)[:500],
            )
        except json.JSONDecodeError:
            print(f"[DONE] 最后一条消息(文本预览): {state.last_payload[:500]}")

    if state.message_count == 0:
        print("[WARN] 已连接但未收到消息，请检查 Topic/设备发布状态。")
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

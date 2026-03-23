import asyncio
import json
import logging
import threading
from datetime import datetime, timedelta

import paho.mqtt.client as mqtt
from sqlalchemy import select

from ..config import get_settings
from ..database import SessionLocal
from ..models import Device, DeviceStatus, Order, OrderStatus
from .anomaly_engine import anomaly_engine_service
from .tdengine_service import tdengine_service
from ..ws.monitor import monitor_connection_manager

logger = logging.getLogger(__name__)


class MqttIngestionService:
    MAX_INGEST_QUEUE_SIZE = 2000

    def __init__(self) -> None:
        self.settings = get_settings()
        self._client: mqtt.Client | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._ingest_queue: asyncio.Queue[dict] | None = None
        self._worker_task: asyncio.Task | None = None
        self._seen_device_lock = threading.Lock()
        self._seen_devices: dict[str, datetime] = {}

    async def start(self) -> None:
        if self._client is not None:
            return
        self._loop = asyncio.get_running_loop()
        self._ingest_queue = asyncio.Queue(maxsize=self.MAX_INGEST_QUEUE_SIZE)
        if self._worker_task is None or self._worker_task.done():
            self._worker_task = asyncio.create_task(self._ingest_worker_loop())

        client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=self.settings.mqtt_client_id,
            clean_session=True,
        )
        if self.settings.mqtt_username:
            client.username_pw_set(self.settings.mqtt_username, self.settings.mqtt_password)

        client.on_connect = self._on_connect
        client.on_message = self._on_message
        client.on_disconnect = self._on_disconnect

        try:
            client.connect(self.settings.mqtt_broker, self.settings.mqtt_port, keepalive=30)
        except Exception as exc:  # noqa: BLE001
            logger.warning("MQTT connect failed: %s", exc)
            self._client = None
            return

        client.loop_start()
        self._client = client

    async def stop(self) -> None:
        if self._client is not None:
            try:
                self._client.loop_stop()
                self._client.disconnect()
            except Exception:  # noqa: BLE001
                pass
            self._client = None
        if self._worker_task is not None:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
            self._worker_task = None
        self._ingest_queue = None
        self._loop = None

    @staticmethod
    def _reason_code_value(reason_code) -> int:
        value = getattr(reason_code, "value", reason_code)
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            if value.isdigit():
                return int(value)
            return 0 if value.lower() == "success" else -1
        return -1

    def _on_connect(self, client: mqtt.Client, _userdata, _flags, reason_code, _properties=None):
        code = self._reason_code_value(reason_code)
        if code != 0:
            logger.warning("MQTT connect rejected: %s", reason_code)
            return
        client.subscribe(self.settings.mqtt_topic, qos=1)
        logger.info("MQTT connected and subscribed topic: %s", self.settings.mqtt_topic)

    def _on_disconnect(self, _client: mqtt.Client, _userdata, _flags, reason_code, _properties=None):
        if self._reason_code_value(reason_code) != 0:
            logger.warning("MQTT disconnected unexpectedly: %s", reason_code)

    def _on_message(self, _client: mqtt.Client, _userdata, msg: mqtt.MQTTMessage):
        self._handle_message(msg.payload)

    def _enqueue_message(self, parsed: dict) -> None:
        if self._ingest_queue is None:
            return
        try:
            self._ingest_queue.put_nowait(parsed)
        except asyncio.QueueFull:
            logger.warning("MQTT ingest queue is full, dropping payload for %s", parsed.get("device_id"))

    def _mark_device_seen(self, device_id: str) -> None:
        now = datetime.now()
        with self._seen_device_lock:
            self._seen_devices[device_id] = now
            # 仅保留最近 24 小时出现过的设备，避免内存长期累积。
            expire_before = now - timedelta(hours=24)
            stale_ids = [item for item, ts in self._seen_devices.items() if ts < expire_before]
            for stale_id in stale_ids:
                self._seen_devices.pop(stale_id, None)

    def list_discovered_devices(self, online_window_seconds: int = 120) -> list[dict]:
        cutoff = datetime.now() - timedelta(seconds=online_window_seconds)
        with self._seen_device_lock:
            rows = [
                {
                    "device_id": device_id,
                    "last_seen": ts.isoformat(sep=" ", timespec="seconds"),
                }
                for device_id, ts in self._seen_devices.items()
                if ts >= cutoff
            ]
        rows.sort(key=lambda row: row["last_seen"], reverse=True)
        return rows

    def _handle_message(self, payload: bytes) -> None:
        try:
            raw = json.loads(payload.decode("utf-8"))
        except Exception:  # noqa: BLE001
            logger.warning("MQTT payload decode failed")
            return

        parsed = self._parse_message(raw)
        if parsed is None:
            return
        self._mark_device_seen(parsed["device_id"])
        if self._loop is None or self._ingest_queue is None:
            logger.warning("MQTT message dropped because ingest worker is not ready")
            return
        self._loop.call_soon_threadsafe(self._enqueue_message, parsed)

    def _process_payload_sync(self, parsed: dict) -> dict | None:
        result = self._process_business(parsed)
        if result is None:
            return None

        order_id = result["order_id"]
        ts = result["ts"]
        device_id = parsed["device_id"]
        insert_result = tdengine_service.insert_sensor_data(
            device_id,
            order_id,
            ts,
            parsed["temperature"],
            parsed["humidity"],
            parsed["pressure"],
            parsed["gps_lat"],
            parsed["gps_lng"],
            parsed["uptime"],
        )
        if not insert_result.ok:
            logger.warning("TDengine insert failed: %s", insert_result.payload)
            return None

        anomaly_engine_service.process_sensor_data(
            order_id=order_id,
            device_id=device_id,
            ts=ts,
            metrics={
                "temperature": parsed["temperature"],
                "humidity": parsed["humidity"],
                "pressure": parsed["pressure"],
            },
        )

        return {
            "type": "sensor_data",
            "order_id": order_id,
            "data": {
                "order_id": order_id,
                "ts": ts.isoformat(sep=" ", timespec="seconds"),
                "temperature": parsed["temperature"],
                "humidity": parsed["humidity"],
                "pressure": parsed["pressure"],
                "gps_lat": parsed["gps_lat"],
                "gps_lng": parsed["gps_lng"],
                "uptime": parsed["uptime"],
            },
        }

    async def _ingest_worker_loop(self) -> None:
        while True:
            if self._ingest_queue is None:
                await asyncio.sleep(0.2)
                continue
            parsed = await self._ingest_queue.get()
            try:
                payload = await asyncio.to_thread(self._process_payload_sync, parsed)
                if payload is None:
                    continue
                await monitor_connection_manager.broadcast(payload["order_id"], payload)
            except Exception as exc:  # noqa: BLE001
                logger.warning("MQTT ingest worker failed: %s", exc)
            finally:
                self._ingest_queue.task_done()

    @staticmethod
    def _parse_float(value):
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _parse_int(value):
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _parse_timestamp(self, timestamp_text: str | None) -> datetime:
        if not timestamp_text:
            return datetime.now()
        try:
            return datetime.fromisoformat(timestamp_text.replace("Z", "+00:00")).replace(
                tzinfo=None
            )
        except ValueError:
            return datetime.now()

    def _parse_message(self, raw: dict) -> dict | None:
        device_id = str(raw.get("device_id") or "").strip()
        sensors = raw.get("sensors") if isinstance(raw.get("sensors"), dict) else {}
        gps = raw.get("gps") if isinstance(raw.get("gps"), dict) else {}
        if not device_id:
            return None

        sensors_valid = bool(sensors.get("valid", True))
        gps_valid = bool(gps.get("valid", True))

        return {
            "device_id": device_id,
            "ts": self._parse_timestamp(raw.get("timestamp")),
            "uptime": self._parse_int(raw.get("uptime")),
            "temperature": self._parse_float(sensors.get("temperature")) if sensors_valid else None,
            "humidity": self._parse_float(sensors.get("humidity")) if sensors_valid else None,
            "pressure": self._parse_float(sensors.get("pressure")) if sensors_valid else None,
            "gps_lat": self._parse_float(gps.get("lat")) if gps_valid else None,
            "gps_lng": self._parse_float(gps.get("lng")) if gps_valid else None,
        }

    def _process_business(self, parsed: dict) -> dict | None:
        with SessionLocal() as db:
            device = db.scalar(
                select(Device).where(Device.device_id == parsed["device_id"]).limit(1)
            )
            if device is None:
                return None

            device.last_seen = parsed["ts"]
            if device.driver_id is None:
                device.status = DeviceStatus.UNBOUND
            else:
                device.status = DeviceStatus.ONLINE
            db.add(device)

            active_order = db.scalar(
                select(Order)
                .where(
                    Order.device_id == parsed["device_id"],
                    Order.status == OrderStatus.IN_TRANSIT,
                )
                .order_by(Order.created_at.desc())
                .limit(1)
            )
            db.commit()

            if active_order is None:
                return None

            return {"order_id": active_order.order_id, "ts": parsed["ts"]}


mqtt_ingestion_service = MqttIngestionService()

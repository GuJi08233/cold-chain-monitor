import asyncio
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select

from ..database import SessionLocal
from ..models import (
    AlertRule,
    Anomaly,
    AnomalyMetric,
    AnomalyStatus,
    Device,
    DeviceStatus,
    Order,
    OrderStatus,
)
from ..ws.monitor import monitor_connection_manager
from .chain_service import chain_service
from .notification_service import notification_service


@dataclass
class MetricAlertState:
    anomaly_id: int
    peak_value: float
    direction: str
    recovery_count: int = 0


class AnomalyEngineService:
    RECOVERY_THRESHOLD = 3
    OFFLINE_TIMEOUT_SECONDS = 10
    OFFLINE_CHECK_INTERVAL_SECONDS = 5

    def __init__(self) -> None:
        self._metric_states: dict[tuple[str, str], MetricAlertState] = {}
        self._offline_states: dict[str, int] = {}
        self._lock = threading.RLock()
        self._offline_task: asyncio.Task | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        await asyncio.to_thread(self._load_ongoing_states)
        if self._offline_task is None or self._offline_task.done():
            self._offline_task = asyncio.create_task(self._offline_checker_loop())

    async def stop(self) -> None:
        if self._offline_task is not None:
            self._offline_task.cancel()
            try:
                await self._offline_task
            except asyncio.CancelledError:
                pass
            self._offline_task = None

    def process_sensor_data(
        self,
        order_id: str,
        device_id: str,
        ts: datetime,
        metrics: dict[str, float | None],
    ) -> None:
        pending_notifications: list[dict] = []
        pending_chain_events: list[tuple[str, int]] = []
        with SessionLocal() as db:
            rules = db.scalars(
                select(AlertRule).where(AlertRule.order_id == order_id)
            ).all()
            if not rules:
                return

            for rule in rules:
                metric_name = self._enum_value(rule.metric)
                value = metrics.get(metric_name)
                if value is None:
                    continue
                self._process_metric_rule(
                    db=db,
                    order_id=order_id,
                    device_id=device_id,
                    ts=ts,
                    rule=rule,
                    value=value,
                    pending_notifications=pending_notifications,
                    pending_chain_events=pending_chain_events,
                )

            db.commit()

        for item in pending_notifications:
            self._notify_driver(
                order_id=item["order_id"],
                notification_type=item["notification_type"],
                title=item["title"],
                content=item["content"],
            )
        self._submit_chain_events(pending_chain_events)

    @staticmethod
    def _enum_value(value) -> str:
        return value.value if hasattr(value, "value") else str(value)

    def _process_metric_rule(
        self,
        db,
        order_id: str,
        device_id: str,
        ts: datetime,
        rule: AlertRule,
        value: float,
        pending_notifications: list[dict],
        pending_chain_events: list[tuple[str, int]],
    ) -> None:
        metric_name = self._enum_value(rule.metric)
        key = (order_id, metric_name)
        is_violation, direction = self._judge_violation(value, rule.min_value, rule.max_value)

        with self._lock:
            state = self._metric_states.get(key)

        if is_violation:
            if state is None:
                anomaly = Anomaly(
                    order_id=order_id,
                    device_id=device_id,
                    rule_id=rule.rule_id,
                    metric=AnomalyMetric(metric_name),
                    trigger_value=value,
                    threshold_min=rule.min_value,
                    threshold_max=rule.max_value,
                    start_time=ts,
                    status=AnomalyStatus.ONGOING,
                    peak_value=value,
                )
                db.add(anomaly)
                db.flush()
                pending_chain_events.append(("start", anomaly.anomaly_id))
                with self._lock:
                    self._metric_states[key] = MetricAlertState(
                        anomaly_id=anomaly.anomaly_id,
                        peak_value=value,
                        direction=direction,
                        recovery_count=0,
                    )
                self._emit_monitor_event(
                    order_id,
                    {
                        "type": "anomaly_start",
                        "data": {
                            "anomaly_id": anomaly.anomaly_id,
                            "metric": metric_name,
                            "trigger_value": value,
                            "threshold_min": rule.min_value,
                            "threshold_max": rule.max_value,
                            "ts": ts.isoformat(sep=" ", timespec="seconds"),
                        },
                    },
                )
                pending_notifications.append(
                    {
                        "order_id": order_id,
                        "notification_type": "anomaly_start",
                        "title": "检测到异常",
                        "content": {
                            "metric": metric_name,
                            "trigger_value": value,
                            "threshold_min": rule.min_value,
                            "threshold_max": rule.max_value,
                            "ts": ts.isoformat(sep=" ", timespec="seconds"),
                        },
                    }
                )
                return

            if state.direction == direction:
                state.recovery_count = 0
                if direction == "above":
                    state.peak_value = max(state.peak_value, value)
                else:
                    state.peak_value = min(state.peak_value, value)
                with self._lock:
                    self._metric_states[key] = state
                return

            self._resolve_metric_anomaly(
                db,
                key,
                ts,
                pending_notifications,
                pending_chain_events,
            )
            anomaly = Anomaly(
                order_id=order_id,
                device_id=device_id,
                rule_id=rule.rule_id,
                metric=AnomalyMetric(metric_name),
                trigger_value=value,
                threshold_min=rule.min_value,
                threshold_max=rule.max_value,
                start_time=ts,
                status=AnomalyStatus.ONGOING,
                peak_value=value,
            )
            db.add(anomaly)
            db.flush()
            pending_chain_events.append(("start", anomaly.anomaly_id))
            with self._lock:
                self._metric_states[key] = MetricAlertState(
                    anomaly_id=anomaly.anomaly_id,
                    peak_value=value,
                    direction=direction,
                    recovery_count=0,
                )
            self._emit_monitor_event(
                order_id,
                {
                    "type": "anomaly_start",
                    "data": {
                        "anomaly_id": anomaly.anomaly_id,
                        "metric": metric_name,
                        "trigger_value": value,
                        "threshold_min": rule.min_value,
                        "threshold_max": rule.max_value,
                        "ts": ts.isoformat(sep=" ", timespec="seconds"),
                    },
                },
            )
            pending_notifications.append(
                {
                    "order_id": order_id,
                    "notification_type": "anomaly_start",
                    "title": "检测到异常",
                    "content": {
                        "metric": metric_name,
                        "trigger_value": value,
                        "threshold_min": rule.min_value,
                        "threshold_max": rule.max_value,
                        "ts": ts.isoformat(sep=" ", timespec="seconds"),
                    },
                }
            )
            return

        if state is None:
            return

        state.recovery_count += 1
        if state.recovery_count < self.RECOVERY_THRESHOLD:
            with self._lock:
                self._metric_states[key] = state
            return

        self._resolve_metric_anomaly(
            db,
            key,
            ts,
            pending_notifications,
            pending_chain_events,
        )

    @staticmethod
    def _judge_violation(value: float, min_value: float | None, max_value: float | None) -> tuple[bool, str]:
        if min_value is not None and value < min_value:
            return True, "below"
        if max_value is not None and value > max_value:
            return True, "above"
        return False, ""

    def _resolve_metric_anomaly(
        self,
        db,
        key: tuple[str, str],
        ts: datetime,
        pending_notifications: list[dict],
        pending_chain_events: list[tuple[str, int]],
    ) -> None:
        with self._lock:
            state = self._metric_states.get(key)
        if state is None:
            return

        anomaly = db.get(Anomaly, state.anomaly_id)
        if anomaly is None:
            with self._lock:
                self._metric_states.pop(key, None)
            return

        anomaly.status = AnomalyStatus.RESOLVED
        anomaly.end_time = ts
        anomaly.peak_value = state.peak_value
        db.add(anomaly)
        pending_chain_events.append(("end", anomaly.anomaly_id))
        with self._lock:
            self._metric_states.pop(key, None)

        self._emit_monitor_event(
            anomaly.order_id,
            {
                "type": "anomaly_end",
                "data": {
                    "anomaly_id": anomaly.anomaly_id,
                    "metric": self._enum_value(anomaly.metric),
                    "peak_value": state.peak_value,
                    "ts": ts.isoformat(sep=" ", timespec="seconds"),
                },
            },
        )
        pending_notifications.append(
            {
                "order_id": anomaly.order_id,
                "notification_type": "anomaly_end",
                "title": "异常已恢复",
                "content": {
                    "anomaly_id": anomaly.anomaly_id,
                    "metric": self._enum_value(anomaly.metric),
                    "peak_value": state.peak_value,
                    "ts": ts.isoformat(sep=" ", timespec="seconds"),
                },
            }
        )

    async def _offline_checker_loop(self) -> None:
        while True:
            await asyncio.sleep(self.OFFLINE_CHECK_INTERVAL_SECONDS)
            await asyncio.to_thread(self._check_offline_once)

    def _check_offline_once(self) -> None:
        now = datetime.now()
        pending_notifications: list[dict] = []
        pending_chain_events: list[tuple[str, int]] = []
        with SessionLocal() as db:
            rows = db.execute(
                select(Order, Device)
                .join(Device, Order.device_id == Device.device_id)
                .where(Order.status == OrderStatus.IN_TRANSIT)
            ).all()

            for order, device in rows:
                last_seen = device.last_seen
                seconds = (
                    (now - last_seen).total_seconds()
                    if last_seen is not None
                    else self.OFFLINE_TIMEOUT_SECONDS + 1
                )
                is_offline = seconds > self.OFFLINE_TIMEOUT_SECONDS
                device_id = device.device_id
                with self._lock:
                    active_offline_anomaly_id = self._offline_states.get(device_id)

                if is_offline:
                    if device.status != DeviceStatus.OFFLINE:
                        device.status = DeviceStatus.OFFLINE
                        db.add(device)
                    if active_offline_anomaly_id is None:
                        anomaly = Anomaly(
                            order_id=order.order_id,
                            device_id=device_id,
                            rule_id=None,
                            metric=AnomalyMetric.DEVICE_OFFLINE,
                            trigger_value=float(seconds),
                            threshold_min=None,
                            threshold_max=float(self.OFFLINE_TIMEOUT_SECONDS),
                            start_time=now,
                            status=AnomalyStatus.ONGOING,
                            peak_value=float(seconds),
                        )
                        db.add(anomaly)
                        db.flush()
                        pending_chain_events.append(("start", anomaly.anomaly_id))
                        with self._lock:
                            self._offline_states[device_id] = anomaly.anomaly_id
                        self._emit_monitor_event(
                            order.order_id,
                            {
                                "type": "anomaly_start",
                                "data": {
                                    "anomaly_id": anomaly.anomaly_id,
                                    "metric": "device_offline",
                                    "trigger_value": float(seconds),
                                    "threshold_max": float(self.OFFLINE_TIMEOUT_SECONDS),
                                    "ts": now.isoformat(sep=" ", timespec="seconds"),
                                },
                            },
                        )
                        pending_notifications.append(
                            {
                                "order_id": order.order_id,
                                "notification_type": "anomaly_start",
                                "title": "设备离线告警",
                                "content": {
                                    "metric": "device_offline",
                                    "trigger_value": float(seconds),
                                    "threshold_max": float(self.OFFLINE_TIMEOUT_SECONDS),
                                    "ts": now.isoformat(sep=" ", timespec="seconds"),
                                },
                            }
                        )
                    continue

                if device.status == DeviceStatus.OFFLINE:
                    device.status = DeviceStatus.ONLINE
                    db.add(device)
                if active_offline_anomaly_id is not None:
                    anomaly = db.get(Anomaly, active_offline_anomaly_id)
                    if anomaly is not None and anomaly.status == AnomalyStatus.ONGOING:
                        anomaly.status = AnomalyStatus.RESOLVED
                        anomaly.end_time = now
                        anomaly.peak_value = max(
                            anomaly.peak_value or anomaly.trigger_value,
                            float(seconds),
                        )
                        db.add(anomaly)
                        pending_chain_events.append(("end", anomaly.anomaly_id))
                        self._emit_monitor_event(
                            order.order_id,
                            {
                                "type": "anomaly_end",
                                "data": {
                                    "anomaly_id": anomaly.anomaly_id,
                                    "metric": "device_offline",
                                    "peak_value": anomaly.peak_value,
                                    "ts": now.isoformat(sep=" ", timespec="seconds"),
                                },
                            },
                        )
                        pending_notifications.append(
                            {
                                "order_id": order.order_id,
                                "notification_type": "anomaly_end",
                                "title": "设备已恢复在线",
                                "content": {
                                    "metric": "device_offline",
                                    "anomaly_id": anomaly.anomaly_id,
                                    "peak_value": anomaly.peak_value,
                                    "ts": now.isoformat(sep=" ", timespec="seconds"),
                                },
                            }
                        )
                    with self._lock:
                        self._offline_states.pop(device_id, None)

            db.commit()

        for item in pending_notifications:
            self._notify_driver(
                order_id=item["order_id"],
                notification_type=item["notification_type"],
                title=item["title"],
                content=item["content"],
            )
        self._submit_chain_events(pending_chain_events)

    def _load_ongoing_states(self) -> None:
        with SessionLocal() as db:
            rows = db.scalars(
                select(Anomaly).where(Anomaly.status == AnomalyStatus.ONGOING)
            ).all()
            with self._lock:
                self._metric_states.clear()
                self._offline_states.clear()
                for anomaly in rows:
                    metric_name = self._enum_value(anomaly.metric)
                    if metric_name == AnomalyMetric.DEVICE_OFFLINE.value:
                        self._offline_states[anomaly.device_id] = anomaly.anomaly_id
                        continue
                    direction = "above"
                    if (
                        anomaly.threshold_min is not None
                        and anomaly.trigger_value < anomaly.threshold_min
                    ):
                        direction = "below"
                    peak = (
                        anomaly.peak_value
                        if anomaly.peak_value is not None
                        else anomaly.trigger_value
                    )
                    self._metric_states[(anomaly.order_id, metric_name)] = MetricAlertState(
                        anomaly_id=anomaly.anomaly_id,
                        peak_value=peak,
                        direction=direction,
                        recovery_count=0,
                    )

    def _emit_monitor_event(self, order_id: str, payload: dict) -> None:
        if self._loop is None:
            return
        self._loop.call_soon_threadsafe(
            asyncio.create_task,
            monitor_connection_manager.broadcast(order_id, payload),
        )

    def _notify_driver(
        self,
        order_id: str,
        notification_type: str,
        title: str,
        content: dict,
    ) -> None:
        try:
            with SessionLocal() as db:
                order = db.scalar(select(Order).where(Order.order_id == order_id).limit(1))
                if order is None:
                    return
                driver_id = order.driver_id
            notification_service.create_notification(
                user_id=driver_id,
                notification_type=notification_type,
                title=title,
                content={"order_id": order_id, **content},
            )
        except Exception:  # noqa: BLE001
            # 通知失败不应影响主流程
            return

    @staticmethod
    def _submit_chain_events(events: list[tuple[str, int]]) -> None:
        for action, anomaly_id in events:
            try:
                if action == "start":
                    chain_service.submit_anomaly_start(anomaly_id)
                elif action == "end":
                    chain_service.submit_anomaly_end(anomaly_id)
            except Exception:  # noqa: BLE001
                # 上链失败仅影响链路，不阻塞主业务。
                continue


anomaly_engine_service = AnomalyEngineService()

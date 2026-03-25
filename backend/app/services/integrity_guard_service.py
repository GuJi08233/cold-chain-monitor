import asyncio
import json
import logging
from datetime import datetime

from sqlalchemy import select

from ..config import get_settings
from ..core.time_utils import app_now, format_app_datetime, get_app_timezone, parse_app_datetime
from ..database import SessionLocal
from ..models import (
    ChainRecord,
    ChainRecordStatus,
    ChainRecordType,
    Notification,
    NotificationType,
    Order,
    OrderStatus,
    User,
    UserRole,
    UserStatus,
)
from .chain_service import ChainServiceError, chain_service
from .hash_service import hash_service
from .notification_service import notification_service
from .order_archive_service import order_archive_service
from .system_config_service import system_config_service

logger = logging.getLogger(__name__)


def _safe_parse_json(raw_value: str | None) -> dict:
    if not raw_value:
        return {}
    try:
        data = json.loads(raw_value)
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _normalize_hash_text(value: str | None) -> str:
    text = (value or "").strip().lower()
    return text[2:] if text.startswith("0x") else text


class IntegrityGuardService:
    def __init__(self) -> None:
        self._retry_task: asyncio.Task | None = None
        self._hash_audit_task: asyncio.Task | None = None

    async def start(self) -> None:
        await asyncio.to_thread(self._retry_failed_chain_records_once)
        await asyncio.to_thread(self._audit_order_hashes_once)
        if self._retry_task is None or self._retry_task.done():
            self._retry_task = asyncio.create_task(self._retry_loop())
        if self._hash_audit_task is None or self._hash_audit_task.done():
            self._hash_audit_task = asyncio.create_task(self._hash_audit_loop())

    async def stop(self) -> None:
        for attr_name in ("_retry_task", "_hash_audit_task"):
            task = getattr(self, attr_name)
            if task is None:
                continue
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            setattr(self, attr_name, None)

    async def _retry_loop(self) -> None:
        while True:
            interval = self._retry_interval_seconds()
            await asyncio.sleep(interval)
            await asyncio.to_thread(self._retry_failed_chain_records_once)

    async def _hash_audit_loop(self) -> None:
        while True:
            interval = self._hash_audit_interval_seconds()
            await asyncio.sleep(interval)
            await asyncio.to_thread(self._audit_order_hashes_once)

    def _retry_failed_chain_records_once(self) -> None:
        if not self._retry_enabled():
            return
        now = app_now()
        batch_size = self._retry_batch_size()
        with SessionLocal() as db:
            rows = db.scalars(
                select(ChainRecord)
                .where(ChainRecord.status == ChainRecordStatus.FAILED)
                .order_by(ChainRecord.record_id.asc())
                .limit(batch_size)
            ).all()

        for row in rows:
            payload = _safe_parse_json(row.payload)
            if row.type == ChainRecordType.ORDER_HASH and self._reconcile_order_hash_record(row.record_id):
                continue
            if not self._is_retry_due(payload, row.created_at, now):
                continue
            try:
                chain_service.retry_record(row.record_id)
                logger.info("Auto retried chain record %s", row.record_id)
            except ChainServiceError as exc:
                logger.warning("Auto retry skipped for chain record %s: %s", row.record_id, exc)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Auto retry failed for chain record %s: %s", row.record_id, exc)

    def _reconcile_order_hash_record(self, record_id: int) -> bool:
        with SessionLocal() as db:
            row = db.get(ChainRecord, record_id)
            if row is None or row.type != ChainRecordType.ORDER_HASH:
                return False
            payload = _safe_parse_json(row.payload)
            order_id = str(payload.get("order_id") or row.order_id or "")
            expected_hash = str(payload.get("data_hash") or row.data_hash or "")

        if not order_id or not expected_hash:
            return False

        try:
            chain_data = chain_service.get_order_hash(order_id)
        except Exception:  # noqa: BLE001
            return False
        if chain_data is None:
            return False
        if _normalize_hash_text(chain_data.get("data_hash")) != _normalize_hash_text(expected_hash):
            return False

        with SessionLocal() as db:
            row = db.get(ChainRecord, record_id)
            if row is None:
                return False
            payload = _safe_parse_json(row.payload)
            payload.pop("last_error", None)
            payload.pop("last_error_at", None)
            payload["data_hash_mode"] = chain_data.get("data_hash_mode")
            payload["recovered_by"] = "chain_readback"
            row.payload = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            row.status = ChainRecordStatus.CONFIRMED
            db.add(row)
            db.commit()
        logger.info("Auto reconciled order hash record %s from on-chain state", record_id)
        return True

    def _audit_order_hashes_once(self) -> None:
        if not self._hash_audit_enabled():
            return
        batch_size = self._hash_audit_batch_size()
        with SessionLocal() as db:
            rows = db.execute(
                select(Order, ChainRecord)
                .join(
                    ChainRecord,
                    (ChainRecord.order_id == Order.order_id)
                    & (ChainRecord.type == ChainRecordType.ORDER_HASH)
                    & (ChainRecord.status == ChainRecordStatus.CONFIRMED),
                )
                .where(
                    Order.status == OrderStatus.COMPLETED,
                    Order.data_hash.is_not(None),
                )
                .order_by(ChainRecord.record_id.desc())
                .limit(batch_size)
            ).all()
            archive_map = order_archive_service.list_order_archives(
                [order.order_id for order, _ in rows],
                db=db,
            )

        for order, chain_record in rows:
            if archive_map.get(order.order_id) is not None:
                continue
            try:
                chain_data = chain_service.get_order_hash(order.order_id)
                if chain_data is None:
                    continue
                current_local_hash = hash_service.compute_order_hash_streaming(
                    device_id=order.device_id,
                    order_id=order.order_id,
                    batch_size=5000,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Hash audit failed for %s: %s", order.order_id, exc)
                continue

            current_hash = _normalize_hash_text(current_local_hash)
            chain_hash = _normalize_hash_text(chain_data.get("data_hash"))
            if current_hash == chain_hash:
                continue
            self._notify_hash_mismatch(order, chain_record, current_local_hash, chain_data)

    def _is_retry_due(self, payload: dict, created_at: datetime | None, now: datetime) -> bool:
        anchor = self._read_retry_anchor(payload) or created_at or now
        retry_count = self._read_retry_count(payload)
        delay_seconds = self._retry_delay_seconds(retry_count)
        return (now - anchor).total_seconds() >= delay_seconds

    @staticmethod
    def _read_retry_count(payload: dict) -> int:
        try:
            return max(0, int(payload.get("retry_count") or 0))
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _read_retry_anchor(payload: dict) -> datetime | None:
        for key in ("last_error_at", "last_retry_at"):
            parsed = parse_app_datetime(str(payload.get(key) or ""))
            if parsed is not None:
                return parsed
        return None

    def _retry_delay_seconds(self, retry_count: int) -> int:
        base = self._retry_interval_seconds()
        max_delay = max(base, self._retry_max_interval_seconds())
        factor = 2 ** min(max(0, retry_count), 6)
        return min(base * factor, max_delay)

    def _notify_hash_mismatch(
        self,
        order: Order,
        chain_record: ChainRecord,
        current_local_hash: str,
        chain_data: dict,
    ) -> None:
        content = {
            "order_id": order.order_id,
            "device_id": order.device_id,
            "stored_hash": order.data_hash,
            "local_hash": current_local_hash,
            "chain_hash": chain_data.get("data_hash"),
            "local_hash_changed": _normalize_hash_text(current_local_hash)
            != _normalize_hash_text(order.data_hash),
            "chain_record_id": chain_record.record_id,
            "chain_timestamp": self._format_chain_timestamp(chain_data.get("timestamp")),
            "message": "检测到本地监控数据与链上存证哈希不一致，请立即排查数据篡改或补录行为。",
        }
        title = f"运单 {order.order_id} 哈希校验异常"

        try:
            if not self._has_same_hash_alert(order.driver_id, order.order_id, current_local_hash):
                notification_service.create_notification(
                    user_id=order.driver_id,
                    notification_type=NotificationType.HASH_MISMATCH.value,
                    title=title,
                    content=content,
                )
            self._notify_admins_once(order.order_id, current_local_hash, title, content)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Hash mismatch notification failed for %s: %s", order.order_id, exc)

        logger.warning(
            "Order hash mismatch detected for %s: local=%s chain=%s",
            order.order_id,
            current_local_hash,
            chain_data.get("data_hash"),
        )

    @staticmethod
    def _format_chain_timestamp(ts: int | None) -> str | None:
        if ts is None:
            return None
        try:
            value = int(ts)
        except (TypeError, ValueError):
            return None
        if value <= 0:
            return None
        try:
            dt = datetime.fromtimestamp(value, tz=get_app_timezone())
            return format_app_datetime(dt)
        except Exception:  # noqa: BLE001
            return None

    @staticmethod
    def _retry_enabled() -> bool:
        settings = get_settings()
        return system_config_service.get_bool(
            "chain_auto_retry_enabled",
            default=settings.chain_auto_retry_enabled,
        )

    @staticmethod
    def _retry_interval_seconds() -> int:
        settings = get_settings()
        return system_config_service.get_int(
            "chain_auto_retry_interval_seconds",
            default=settings.chain_auto_retry_interval_seconds,
            minimum=5,
        )

    @staticmethod
    def _retry_max_interval_seconds() -> int:
        settings = get_settings()
        return system_config_service.get_int(
            "chain_auto_retry_max_interval_seconds",
            default=settings.chain_auto_retry_max_interval_seconds,
            minimum=5,
        )

    @staticmethod
    def _retry_batch_size() -> int:
        settings = get_settings()
        return system_config_service.get_int(
            "chain_auto_retry_batch_size",
            default=settings.chain_auto_retry_batch_size,
            minimum=1,
        )

    @staticmethod
    def _hash_audit_enabled() -> bool:
        settings = get_settings()
        return system_config_service.get_bool(
            "hash_audit_enabled",
            default=settings.hash_audit_enabled,
        )

    @staticmethod
    def _hash_audit_interval_seconds() -> int:
        settings = get_settings()
        return system_config_service.get_int(
            "hash_audit_interval_seconds",
            default=settings.hash_audit_interval_seconds,
            minimum=30,
        )

    @staticmethod
    def _hash_audit_batch_size() -> int:
        settings = get_settings()
        return system_config_service.get_int(
            "hash_audit_batch_size",
            default=settings.hash_audit_batch_size,
            minimum=1,
        )

    @staticmethod
    def _has_same_hash_alert(user_id: int, order_id: str, local_hash: str) -> bool:
        with SessionLocal() as db:
            rows = db.scalars(
                select(Notification)
                .where(
                    Notification.user_id == user_id,
                    Notification.type == NotificationType.HASH_MISMATCH,
                )
                .order_by(Notification.notification_id.desc())
                .limit(20)
            ).all()
        target_hash = _normalize_hash_text(local_hash)
        for row in rows:
            content = _safe_parse_json(row.content)
            if str(content.get("order_id") or "") != order_id:
                continue
            if _normalize_hash_text(str(content.get("local_hash") or "")) == target_hash:
                return True
        return False

    def _notify_admins_once(
        self,
        order_id: str,
        local_hash: str,
        title: str,
        content: dict,
    ) -> None:
        with SessionLocal() as db:
            admin_ids = db.scalars(
                select(User.user_id).where(
                    User.role.in_([UserRole.SUPER_ADMIN, UserRole.ADMIN]),
                    User.status == UserStatus.ACTIVE,
                )
            ).all()
        for user_id in admin_ids:
            if self._has_same_hash_alert(user_id, order_id, local_hash):
                continue
            notification_service.create_notification(
                user_id=user_id,
                notification_type=NotificationType.HASH_MISMATCH.value,
                title=title,
                content=content,
            )


integrity_guard_service = IntegrityGuardService()

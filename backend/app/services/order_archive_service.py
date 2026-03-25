import json
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.time_utils import app_now, format_app_datetime
from ..database import SessionLocal
from ..models import SystemConfig, User


@dataclass
class OrderArchiveInfo:
    order_id: str
    is_archived: bool
    reason: str | None = None
    archived_at: str | None = None
    archived_by: int | None = None
    archived_by_name: str | None = None


class OrderArchiveService:
    KEY_PREFIX = "order_archive:"

    @classmethod
    def _key(cls, order_id: str) -> str:
        return f"{cls.KEY_PREFIX}{order_id}"

    @staticmethod
    def _from_value(order_id: str, raw_value: str | None) -> OrderArchiveInfo | None:
        text = (raw_value or "").strip()
        if not text:
            return None
        try:
            payload = json.loads(text)
        except Exception:  # noqa: BLE001
            return None
        if not isinstance(payload, dict):
            return None
        if payload.get("archived") is not True:
            return None
        archived_by = payload.get("archived_by")
        try:
            archived_by_value = int(archived_by) if archived_by is not None else None
        except (TypeError, ValueError):
            archived_by_value = None
        return OrderArchiveInfo(
            order_id=order_id,
            is_archived=True,
            reason=str(payload.get("reason") or "").strip() or None,
            archived_at=str(payload.get("archived_at") or "").strip() or None,
            archived_by=archived_by_value,
            archived_by_name=str(payload.get("archived_by_name") or "").strip() or None,
        )

    def get_order_archive(
        self,
        order_id: str,
        *,
        db: Session | None = None,
    ) -> OrderArchiveInfo | None:
        if db is not None:
            row = db.get(SystemConfig, self._key(order_id))
            return self._from_value(order_id, row.value if row is not None else None)

        with SessionLocal() as local_db:
            row = local_db.get(SystemConfig, self._key(order_id))
            return self._from_value(order_id, row.value if row is not None else None)

    def list_order_archives(
        self,
        order_ids: list[str],
        *,
        db: Session,
    ) -> dict[str, OrderArchiveInfo]:
        clean_ids = [item for item in order_ids if item]
        if not clean_ids:
            return {}
        key_map = {self._key(order_id): order_id for order_id in clean_ids}
        rows = db.scalars(select(SystemConfig).where(SystemConfig.key.in_(list(key_map.keys())))).all()
        result: dict[str, OrderArchiveInfo] = {}
        for row in rows:
            order_id = key_map.get(row.key)
            if not order_id:
                continue
            parsed = self._from_value(order_id, row.value)
            if parsed is not None:
                result[order_id] = parsed
        return result

    def set_order_archive(
        self,
        order_id: str,
        *,
        archived: bool,
        reason: str | None,
        operator: User,
        db: Session,
    ) -> OrderArchiveInfo | None:
        key = self._key(order_id)
        row = db.get(SystemConfig, key)
        if not archived:
            if row is not None:
                db.delete(row)
            return None

        payload = {
            "archived": True,
            "reason": (reason or "").strip() or "测试归档",
            "archived_at": format_app_datetime(app_now()),
            "archived_by": operator.user_id,
            "archived_by_name": operator.display_name or operator.username,
        }
        value = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if row is None:
            row = SystemConfig(key=key, value=value)
        else:
            row.value = value
        db.add(row)
        return self._from_value(order_id, value)


order_archive_service = OrderArchiveService()

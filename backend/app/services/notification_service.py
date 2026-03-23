import asyncio
import json
import time

from sqlalchemy.exc import OperationalError
from sqlalchemy import select

from ..database import SessionLocal
from ..models import Notification, NotificationType, User, UserRole, UserStatus
from ..ws.notifications import notification_connection_manager


class NotificationService:
    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None

    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()

    async def stop(self) -> None:
        self._loop = None

    @staticmethod
    def _enum_value(value) -> str:
        return value.value if hasattr(value, "value") else str(value)

    @staticmethod
    def _to_notification_type(raw_type: str) -> NotificationType:
        try:
            return NotificationType(raw_type)
        except ValueError:
            # 兜底为 anomaly_start，避免脏值导致写入失败
            return NotificationType.ANOMALY_START

    def create_notification(
        self,
        user_id: int,
        notification_type: str,
        title: str,
        content: dict | str,
    ) -> int | None:
        content_text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
        payload = None
        for attempt in range(6):
            try:
                with SessionLocal() as db:
                    user = db.scalar(select(User).where(User.user_id == user_id).limit(1))
                    if user is None:
                        return None
                    if user.status in (UserStatus.PENDING, UserStatus.DISABLED):
                        return None

                    row = Notification(
                        user_id=user_id,
                        type=self._to_notification_type(notification_type),
                        title=title,
                        content=content_text,
                        is_read=False,
                    )
                    db.add(row)
                    db.commit()
                    db.refresh(row)

                    payload = {
                        "type": "notification",
                        "data": {
                            "notification_id": row.notification_id,
                            "user_id": row.user_id,
                            "type": self._enum_value(row.type),
                            "title": row.title,
                            "content": content if isinstance(content, dict) else content_text,
                            "is_read": row.is_read,
                            "created_at": row.created_at.isoformat(sep=" ", timespec="seconds"),
                        },
                    }
                break
            except OperationalError as exc:
                if "database is locked" not in str(exc).lower() or attempt == 5:
                    return None
                time.sleep(0.2)

        if payload is None:
            return None

        self._push_ws(user_id, payload)
        return payload["data"]["notification_id"]

    def notify_admins(self, notification_type: str, title: str, content: dict | str) -> None:
        with SessionLocal() as db:
            admin_ids = db.scalars(
                select(User.user_id).where(
                    User.role.in_([UserRole.SUPER_ADMIN, UserRole.ADMIN]),
                    User.status == UserStatus.ACTIVE,
                )
            ).all()
        for user_id in admin_ids:
            self.create_notification(user_id, notification_type, title, content)

    def _push_ws(self, user_id: int, payload: dict) -> None:
        if self._loop is None:
            return
        self._loop.call_soon_threadsafe(
            asyncio.create_task,
            notification_connection_manager.send_to_user(user_id, payload),
        )


notification_service = NotificationService()

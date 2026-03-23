import json

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ..core.auth import get_current_user
from ..core.deps import get_db_session
from ..core.response import success_response
from ..models import Notification, User

router = APIRouter(prefix="/notifications", tags=["notifications"])


def _enum_value(value) -> str:
    return value.value if hasattr(value, "value") else str(value)


def _parse_content(text: str):
    try:
        return json.loads(text)
    except Exception:  # noqa: BLE001
        return text


def _serialize_notification(row: Notification) -> dict:
    return {
        "notification_id": row.notification_id,
        "user_id": row.user_id,
        "type": _enum_value(row.type),
        "title": row.title,
        "content": _parse_content(row.content),
        "is_read": row.is_read,
        "created_at": row.created_at.isoformat(sep=" ", timespec="seconds"),
    }


@router.get("")
def list_notifications(
    is_read: bool | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> dict:
    stmt = select(Notification).where(Notification.user_id == current_user.user_id)
    if is_read is not None:
        stmt = stmt.where(Notification.is_read == is_read)

    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(
        stmt.order_by(Notification.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return success_response(
        data={
            "items": [_serialize_notification(row) for row in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    )


@router.patch("/{notification_id}/read")
def mark_notification_read(
    notification_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> dict:
    row = db.get(Notification, notification_id)
    if row is None:
        raise HTTPException(status_code=404, detail="通知不存在")
    if row.user_id != current_user.user_id:
        raise HTTPException(status_code=403, detail="无权操作此通知")
    row.is_read = True
    db.add(row)
    db.commit()
    db.refresh(row)
    return success_response(data=_serialize_notification(row), msg="已标记为已读")


@router.patch("/read-all")
def mark_all_notification_read(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> dict:
    db.execute(
        update(Notification)
        .where(Notification.user_id == current_user.user_id, Notification.is_read.is_(False))
        .values(is_read=True)
    )
    db.commit()
    return success_response(msg="已全部标记为已读")


@router.get("/unread-count")
def get_unread_count(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> dict:
    count = db.scalar(
        select(func.count(Notification.notification_id)).where(
            Notification.user_id == current_user.user_id,
            Notification.is_read.is_(False),
        )
    )
    return success_response(data={"unread_count": count})


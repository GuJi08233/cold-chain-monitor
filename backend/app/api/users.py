from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from ..core.auth import get_current_user, require_role
from ..core.deps import get_db_session
from ..core.response import success_response
from ..core.time_utils import format_app_datetime
from ..core.security import hash_password, validate_password_strength
from ..models import (
    Device,
    DeviceStatus,
    Notification,
    Order,
    OrderStatus,
    Ticket,
    User,
    UserRole,
    UserStatus,
)
from ..schemas.user import AdminCreateRequest, UserApproveRequest

router = APIRouter(prefix="/users", tags=["users"])


def _enum_value(value) -> str:
    return value.value if hasattr(value, "value") else str(value)


def _datetime_text(value: datetime | None) -> str | None:
    return format_app_datetime(value)


def _serialize_user(row: User) -> dict:
    profile = None
    if row.driver_profile is not None:
        profile = {
            "real_name": row.driver_profile.real_name,
            "id_card": row.driver_profile.id_card,
            "phone": row.driver_profile.phone,
            "plate_number": row.driver_profile.plate_number,
            "vehicle_type": row.driver_profile.vehicle_type,
        }

    bound_device_id = None
    if row.role == UserRole.DRIVER:
        for device in row.bound_devices:
            if device.driver_id == row.user_id:
                bound_device_id = device.device_id
                break

    return {
        "user_id": row.user_id,
        "username": row.username,
        "role": _enum_value(row.role),
        "status": _enum_value(row.status),
        "display_name": row.display_name,
        "created_at": _datetime_text(row.created_at),
        "driver_profile": profile,
        "bound_device_id": bound_device_id,
    }


@router.get("")
def list_users(
    role: UserRole | None = Query(default=None),
    status: UserStatus | None = Query(default=None),
    search: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    _: User = Depends(require_role(UserRole.SUPER_ADMIN, UserRole.ADMIN)),
    db: Session = Depends(get_db_session),
) -> dict:
    stmt = select(User).options(
        selectinload(User.driver_profile),
        selectinload(User.bound_devices),
    )
    if role is not None:
        stmt = stmt.where(User.role == role)
    if status is not None:
        stmt = stmt.where(User.status == status)
    if search:
        keyword = f"%{search}%"
        stmt = stmt.where(or_(User.username.like(keyword), User.display_name.like(keyword)))

    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(
        stmt.order_by(User.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return success_response(
        data={
            "items": [_serialize_user(row) for row in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    )


@router.post("")
def create_admin_user(
    payload: AdminCreateRequest,
    _: User = Depends(require_role(UserRole.SUPER_ADMIN)),
    db: Session = Depends(get_db_session),
) -> dict:
    validate_password_strength(payload.password)
    exists = db.scalar(select(User).where(User.username == payload.username).limit(1))
    if exists is not None:
        raise HTTPException(status_code=400, detail="用户名已存在")

    row = User(
        username=payload.username,
        password_hash=hash_password(payload.password),
        role=UserRole.ADMIN,
        status=UserStatus.ACTIVE,
        display_name=payload.display_name or payload.username,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return success_response(data=_serialize_user(row), msg="管理员创建成功")


@router.get("/{user_id}")
def get_user_detail(
    user_id: int,
    _: User = Depends(require_role(UserRole.SUPER_ADMIN, UserRole.ADMIN)),
    db: Session = Depends(get_db_session),
) -> dict:
    row = db.scalar(
        select(User)
        .options(
            selectinload(User.driver_profile),
            selectinload(User.bound_devices),
        )
        .where(User.user_id == user_id)
        .limit(1)
    )
    if row is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    return success_response(data=_serialize_user(row))


@router.patch("/{user_id}/approve")
def approve_driver(
    user_id: int,
    payload: UserApproveRequest,
    _: User = Depends(require_role(UserRole.SUPER_ADMIN, UserRole.ADMIN)),
    db: Session = Depends(get_db_session),
) -> dict:
    row = db.get(User, user_id)
    if row is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    if row.role != UserRole.DRIVER:
        raise HTTPException(status_code=400, detail="仅司机用户可审批")
    if row.status != UserStatus.PENDING:
        raise HTTPException(status_code=400, detail="用户状态不允许审批")

    device = db.scalar(select(Device).where(Device.device_id == payload.device_id).limit(1))
    if device is None:
        raise HTTPException(status_code=404, detail="设备不存在")
    if device.driver_id is not None and device.driver_id != user_id:
        raise HTTPException(status_code=400, detail="设备已绑定其他司机")

    occupied_device = db.scalar(
        select(Device)
        .where(Device.driver_id == user_id, Device.device_id != payload.device_id)
        .limit(1)
    )
    if occupied_device is not None:
        raise HTTPException(status_code=400, detail="该司机已绑定其他设备")

    active_order = db.scalar(
        select(Order)
        .where(
            Order.device_id == payload.device_id,
            Order.status.in_([OrderStatus.PENDING, OrderStatus.IN_TRANSIT]),
        )
        .limit(1)
    )
    if active_order is not None and active_order.driver_id != user_id:
        raise HTTPException(status_code=400, detail="设备存在活跃运单，暂不允许更换司机")

    row.status = UserStatus.ACTIVE
    if not row.display_name and row.driver_profile is not None:
        row.display_name = row.driver_profile.real_name
    device.driver_id = row.user_id
    device.status = (
        DeviceStatus.ONLINE
        if device.status == DeviceStatus.ONLINE and device.last_seen is not None
        else DeviceStatus.OFFLINE
    )
    db.add(row)
    db.add(device)
    db.commit()
    db.refresh(row)
    row = db.scalar(
        select(User)
        .options(
            selectinload(User.driver_profile),
            selectinload(User.bound_devices),
        )
        .where(User.user_id == user_id)
        .limit(1)
    )
    return success_response(data=_serialize_user(row), msg="司机审批通过")


@router.patch("/{user_id}/reject")
def reject_driver(
    user_id: int,
    _: User = Depends(require_role(UserRole.SUPER_ADMIN, UserRole.ADMIN)),
    db: Session = Depends(get_db_session),
) -> dict:
    row = db.get(User, user_id)
    if row is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    if row.role != UserRole.DRIVER:
        raise HTTPException(status_code=400, detail="仅司机用户可拒绝")
    if row.status != UserStatus.PENDING:
        raise HTTPException(status_code=400, detail="用户状态不允许拒绝")

    row.status = UserStatus.DISABLED
    db.add(row)
    db.commit()
    db.refresh(row)
    row = db.scalar(
        select(User)
        .options(
            selectinload(User.driver_profile),
            selectinload(User.bound_devices),
        )
        .where(User.user_id == user_id)
        .limit(1)
    )
    return success_response(data=_serialize_user(row), msg="已拒绝该司机注册")


@router.patch("/{user_id}/disable")
def disable_user(
    user_id: int,
    current_user: User = Depends(require_role(UserRole.SUPER_ADMIN, UserRole.ADMIN)),
    db: Session = Depends(get_db_session),
) -> dict:
    row = db.get(User, user_id)
    if row is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    if row.role == UserRole.SUPER_ADMIN:
        raise HTTPException(status_code=400, detail="不允许禁用 super_admin")
    if row.user_id == current_user.user_id:
        raise HTTPException(status_code=400, detail="不允许禁用当前登录用户")

    if row.role == UserRole.DRIVER:
        active_order = db.scalar(
            select(Order)
            .where(
                Order.driver_id == row.user_id,
                Order.status.in_([OrderStatus.PENDING, OrderStatus.IN_TRANSIT]),
            )
            .limit(1)
        )
        if active_order is not None:
            raise HTTPException(status_code=400, detail="司机存在活跃运单，无法禁用")

    row.status = UserStatus.DISABLED
    db.add(row)
    db.commit()
    db.refresh(row)
    row = db.scalar(
        select(User)
        .options(
            selectinload(User.driver_profile),
            selectinload(User.bound_devices),
        )
        .where(User.user_id == user_id)
        .limit(1)
    )
    return success_response(data=_serialize_user(row), msg="用户已禁用")


@router.delete("/{user_id}")
def delete_user(
    user_id: int,
    current_user: User = Depends(require_role(UserRole.SUPER_ADMIN)),
    db: Session = Depends(get_db_session),
) -> dict:
    row = db.get(User, user_id)
    if row is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    if row.role == UserRole.SUPER_ADMIN:
        raise HTTPException(status_code=400, detail="不允许删除 super_admin")
    if row.user_id == current_user.user_id:
        raise HTTPException(status_code=400, detail="不允许删除当前登录用户")

    related_count = 0
    related_count += db.scalar(select(func.count(Order.order_id)).where(Order.driver_id == user_id))
    related_count += db.scalar(select(func.count(Order.order_id)).where(Order.created_by == user_id))
    related_count += db.scalar(select(func.count(Device.device_id)).where(Device.driver_id == user_id))
    related_count += db.scalar(
        select(func.count(Notification.notification_id)).where(Notification.user_id == user_id)
    )
    related_count += db.scalar(select(func.count(Ticket.ticket_id)).where(Ticket.submitter_id == user_id))
    related_count += db.scalar(select(func.count(Ticket.ticket_id)).where(Ticket.reviewer_id == user_id))
    if related_count > 0:
        raise HTTPException(status_code=400, detail="用户存在关联业务数据，无法删除")

    db.delete(row)
    db.commit()
    return success_response(msg="用户删除成功")

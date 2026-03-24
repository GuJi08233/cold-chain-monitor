from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..core.auth import require_role
from ..core.deps import get_db_session
from ..core.response import success_response
from ..core.time_utils import format_app_datetime
from ..models import Device, DeviceStatus, Order, OrderStatus, User, UserRole, UserStatus
from ..schemas.device import DeviceBindRequest, DeviceCreateRequest
from ..services.mqtt_service import mqtt_ingestion_service

router = APIRouter(prefix="/devices", tags=["devices"])


def _serialize_device(device: Device) -> dict:
    driver = None
    if device.driver is not None:
        driver = {
            "user_id": device.driver.user_id,
            "username": device.driver.username,
            "display_name": device.driver.display_name,
            "status": device.driver.status.value
            if hasattr(device.driver.status, "value")
            else str(device.driver.status),
        }

    return {
        "device_id": device.device_id,
        "name": device.name,
        "driver_id": device.driver_id,
        "status": device.status.value if hasattr(device.status, "value") else str(device.status),
        "last_seen": format_app_datetime(device.last_seen),
        "created_at": format_app_datetime(device.created_at),
        "driver": driver,
    }


@router.get("")
def list_devices(
    status: DeviceStatus | None = Query(default=None),
    driver_id: int | None = Query(default=None, ge=1),
    _: User = Depends(require_role(UserRole.SUPER_ADMIN, UserRole.ADMIN)),
    db: Session = Depends(get_db_session),
) -> dict:
    stmt = select(Device).options(selectinload(Device.driver)).order_by(Device.created_at.desc())
    if status is not None:
        stmt = stmt.where(Device.status == status)
    if driver_id is not None:
        stmt = stmt.where(Device.driver_id == driver_id)

    devices = db.scalars(stmt).all()
    return success_response(data=[_serialize_device(device) for device in devices])


@router.post("")
def create_device(
    payload: DeviceCreateRequest,
    _: User = Depends(require_role(UserRole.SUPER_ADMIN, UserRole.ADMIN)),
    db: Session = Depends(get_db_session),
) -> dict:
    exists = db.scalar(select(Device).where(Device.device_id == payload.device_id).limit(1))
    if exists is not None:
        raise HTTPException(status_code=400, detail="设备 ID 已存在")

    device = Device(
        device_id=payload.device_id,
        name=payload.name,
        status=DeviceStatus.UNBOUND,
    )
    db.add(device)
    db.commit()
    db.refresh(device)

    return success_response(data=_serialize_device(device), msg="设备创建成功")


@router.get("/discovered")
def list_discovered_devices(
    online_window_seconds: int = Query(default=120, ge=10, le=3600),
    include_registered: bool = Query(default=False),
    _: User = Depends(require_role(UserRole.SUPER_ADMIN, UserRole.ADMIN)),
    db: Session = Depends(get_db_session),
) -> dict:
    discovered = mqtt_ingestion_service.list_discovered_devices(
        online_window_seconds=online_window_seconds
    )
    if not discovered:
        return success_response(data=[])

    existing_ids = {row[0] for row in db.execute(select(Device.device_id)).all()}
    rows: list[dict] = []
    for item in discovered:
        already_registered = item["device_id"] in existing_ids
        if already_registered and not include_registered:
            continue
        rows.append(
            {
                "device_id": item["device_id"],
                "last_seen": item["last_seen"],
                "already_registered": already_registered,
            }
        )
    return success_response(data=rows)


@router.get("/{device_id}")
def get_device(
    device_id: str,
    _: User = Depends(require_role(UserRole.SUPER_ADMIN, UserRole.ADMIN)),
    db: Session = Depends(get_db_session),
) -> dict:
    device = db.scalar(
        select(Device)
        .options(selectinload(Device.driver))
        .where(Device.device_id == device_id)
        .limit(1)
    )
    if device is None:
        raise HTTPException(status_code=404, detail="设备不存在")
    return success_response(data=_serialize_device(device))


@router.patch("/{device_id}/bind")
def bind_device(
    device_id: str,
    payload: DeviceBindRequest,
    _: User = Depends(require_role(UserRole.SUPER_ADMIN, UserRole.ADMIN)),
    db: Session = Depends(get_db_session),
) -> dict:
    device = db.scalar(
        select(Device)
        .options(selectinload(Device.driver))
        .where(Device.device_id == device_id)
        .limit(1)
    )
    if device is None:
        raise HTTPException(status_code=404, detail="设备不存在")

    if payload.driver_id is None:
        device.driver_id = None
        device.status = DeviceStatus.UNBOUND
        db.add(device)
        db.commit()
        db.refresh(device)
        device = db.scalar(
            select(Device)
            .options(selectinload(Device.driver))
            .where(Device.device_id == device_id)
            .limit(1)
        )
        return success_response(data=_serialize_device(device), msg="设备解绑成功")

    driver = db.scalar(select(User).where(User.user_id == payload.driver_id).limit(1))
    if driver is None:
        raise HTTPException(status_code=404, detail="司机不存在")
    if driver.role != UserRole.DRIVER:
        raise HTTPException(status_code=400, detail="该用户不是司机")
    if driver.status != UserStatus.ACTIVE:
        raise HTTPException(status_code=400, detail="司机未激活，无法绑定设备")

    occupied_device = db.scalar(
        select(Device)
        .where(Device.driver_id == payload.driver_id, Device.device_id != device_id)
        .limit(1)
    )
    if occupied_device is not None:
        raise HTTPException(status_code=400, detail="该司机已绑定其他设备")

    active_order = db.scalar(
        select(Order)
        .where(
            Order.device_id == device_id,
            Order.status.in_([OrderStatus.PENDING, OrderStatus.IN_TRANSIT]),
        )
        .limit(1)
    )
    if active_order is not None and device.driver_id != payload.driver_id:
        raise HTTPException(status_code=400, detail="设备存在活跃运单，暂不允许更换司机")

    device.driver_id = payload.driver_id
    device.status = (
        DeviceStatus.ONLINE
        if device.status == DeviceStatus.ONLINE and device.last_seen is not None
        else DeviceStatus.OFFLINE
    )
    db.add(device)
    db.commit()
    db.refresh(device)
    device = db.scalar(
        select(Device)
        .options(selectinload(Device.driver))
        .where(Device.device_id == device_id)
        .limit(1)
    )

    return success_response(data=_serialize_device(device), msg="设备绑定成功")


@router.delete("/{device_id}")
def delete_device(
    device_id: str,
    _: User = Depends(require_role(UserRole.SUPER_ADMIN, UserRole.ADMIN)),
    db: Session = Depends(get_db_session),
) -> dict:
    device = db.scalar(select(Device).where(Device.device_id == device_id).limit(1))
    if device is None:
        raise HTTPException(status_code=404, detail="设备不存在")

    active_order = db.scalar(
        select(Order)
        .where(
            Order.device_id == device_id,
            Order.status.in_([OrderStatus.PENDING, OrderStatus.IN_TRANSIT]),
        )
        .limit(1)
    )
    if active_order is not None:
        raise HTTPException(status_code=400, detail="设备存在活跃运单，无法删除")

    db.delete(device)
    db.commit()
    return success_response(msg="设备删除成功")

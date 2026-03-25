import json
import logging
import random
import re
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core.auth import get_current_user, require_role
from ..core.deps import get_db_session
from ..core.response import success_response
from ..core.time_utils import app_now, format_app_datetime, normalize_app_datetime
from ..database import SessionLocal
from ..models import (
    AlertRule,
    Anomaly,
    AnomalyStatus,
    Device,
    Order,
    OrderStatus,
    User,
    UserRole,
    UserStatus,
)
from ..schemas.order import OrderCreateRequest
from ..services.chain_service import chain_service
from ..services.hash_service import hash_service
from ..services.notification_service import notification_service
from ..services.order_archive_service import OrderArchiveInfo, order_archive_service
from ..schemas.order import OrderArchiveRequest

router = APIRouter(prefix="/orders", tags=["orders"])
logger = logging.getLogger(__name__)


def _role_value(value) -> str:
    return value.value if hasattr(value, "value") else str(value)


def _datetime_text(value: datetime | None) -> str | None:
    return format_app_datetime(value)


def _parse_cargo_info(raw_value: str | None):
    if not raw_value:
        return None
    try:
        return json.loads(raw_value)
    except json.JSONDecodeError:
        return raw_value


def _serialize_alert_rule(rule: AlertRule) -> dict:
    return {
        "rule_id": rule.rule_id,
        "metric": _role_value(rule.metric),
        "min_value": rule.min_value,
        "max_value": rule.max_value,
    }


def _serialize_archive(archive_info: OrderArchiveInfo | None) -> dict:
    if archive_info is None or not archive_info.is_archived:
        return {
            "is_archived": False,
            "archive_reason": None,
            "archived_at": None,
            "archived_by": None,
            "archived_by_name": None,
        }
    return {
        "is_archived": True,
        "archive_reason": archive_info.reason,
        "archived_at": archive_info.archived_at,
        "archived_by": archive_info.archived_by,
        "archived_by_name": archive_info.archived_by_name,
    }


def _serialize_order(
    order: Order,
    include_alert_rules: bool = False,
    archive_info: OrderArchiveInfo | None = None,
) -> dict:
    data = {
        "order_id": order.order_id,
        "device_id": order.device_id,
        "driver_id": order.driver_id,
        "cargo_name": order.cargo_name,
        "cargo_info": _parse_cargo_info(order.cargo_info),
        "origin": order.origin,
        "destination": order.destination,
        "planned_start": _datetime_text(order.planned_start),
        "actual_start": _datetime_text(order.actual_start),
        "actual_end": _datetime_text(order.actual_end),
        "status": _role_value(order.status),
        "data_hash": order.data_hash,
        "created_by": order.created_by,
        "created_at": _datetime_text(order.created_at),
    }
    data.update(_serialize_archive(archive_info))
    if include_alert_rules:
        data["alert_rules"] = [_serialize_alert_rule(rule) for rule in order.alert_rules]
    return data


def _ensure_order_access(current_user: User, order: Order) -> None:
    if current_user.role == UserRole.DRIVER and order.driver_id != current_user.user_id:
        raise HTTPException(status_code=403, detail="无权访问此运单")


def _device_suffix(device_id: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9]", "", device_id)
    raw_suffix = normalized[-3:] if normalized else device_id[-3:]
    return raw_suffix.rjust(3, "0")[-3:]


def _generate_order_id(db: Session, device_id: str) -> str:
    now = app_now()
    prefix = f"ORD{now:%Y%m%d}{_device_suffix(device_id)}_{now:%H%M%S}"
    for _ in range(100):
        candidate = f"{prefix}{random.randint(0, 99):02d}"
        exists = db.scalar(select(Order.order_id).where(Order.order_id == candidate).limit(1))
        if exists is None:
            return candidate
    raise HTTPException(status_code=500, detail="运单编号生成失败，请重试")


def _build_order_query(
    current_user: User,
    status: OrderStatus | None,
    driver_id: int | None,
    device_id: str | None,
    search: str | None,
):
    stmt = select(Order)

    if current_user.role == UserRole.DRIVER:
        stmt = stmt.where(Order.driver_id == current_user.user_id)
    elif driver_id is not None:
        stmt = stmt.where(Order.driver_id == driver_id)

    if status is not None:
        stmt = stmt.where(Order.status == status)
    if device_id:
        stmt = stmt.where(Order.device_id == device_id)
    if search:
        stmt = stmt.where(Order.order_id.like(f"%{search}%"))

    return stmt


def _close_ongoing_anomalies(db: Session, order_id: str, end_time: datetime) -> list[int]:
    rows = db.scalars(
        select(Anomaly).where(
            Anomaly.order_id == order_id,
            Anomaly.status == AnomalyStatus.ONGOING,
        )
    ).all()
    closed_ids: list[int] = []
    for row in rows:
        row.status = AnomalyStatus.RESOLVED
        row.end_time = end_time
        if row.peak_value is None:
            row.peak_value = row.trigger_value
        db.add(row)
        closed_ids.append(row.anomaly_id)
    return closed_ids


def _finalize_completed_order(order_id: str) -> None:
    closed_anomaly_ids: list[int] = []
    data_hash: str | None = None
    with SessionLocal() as db:
        order = db.scalar(select(Order).where(Order.order_id == order_id).limit(1))
        if order is None:
            return

        end_time = order.actual_end or app_now()
        closed_anomaly_ids = _close_ongoing_anomalies(db, order.order_id, end_time)
        try:
            data_hash = hash_service.compute_order_hash_streaming(
                device_id=order.device_id,
                order_id=order.order_id,
                batch_size=5000,
            )
            order.data_hash = data_hash
            db.add(order)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Order hash compute failed for %s: %s", order.order_id, exc)
        db.commit()

    for anomaly_id in closed_anomaly_ids:
        try:
            chain_service.submit_anomaly_end(anomaly_id)
        except Exception:  # noqa: BLE001
            continue
    if data_hash:
        try:
            chain_service.submit_order_hash(order_id, data_hash)
        except Exception:  # noqa: BLE001
            pass


@router.post("")
def create_order(
    payload: OrderCreateRequest,
    current_user: User = Depends(require_role(UserRole.SUPER_ADMIN, UserRole.ADMIN)),
    db: Session = Depends(get_db_session),
) -> dict:
    device = db.scalar(select(Device).where(Device.device_id == payload.device_id).limit(1))
    if device is None:
        raise HTTPException(status_code=404, detail="设备不存在")

    driver = db.scalar(select(User).where(User.user_id == payload.driver_id).limit(1))
    if driver is None:
        raise HTTPException(status_code=404, detail="司机不存在")
    if driver.role != UserRole.DRIVER:
        raise HTTPException(status_code=400, detail="driver_id 对应用户不是司机")
    if driver.status != UserStatus.ACTIVE:
        raise HTTPException(status_code=400, detail="司机未激活，无法创建运单")

    if device.driver_id != payload.driver_id:
        raise HTTPException(status_code=400, detail="设备未绑定到该司机")

    active_order = db.scalar(
        select(Order)
        .where(Order.device_id == payload.device_id, Order.status == OrderStatus.IN_TRANSIT)
        .limit(1)
    )
    if active_order is not None:
        raise HTTPException(status_code=400, detail="设备存在运输中运单，无法重复创建")

    planned_start = normalize_app_datetime(payload.planned_start)

    order_id = _generate_order_id(db, payload.device_id)
    order = Order(
        order_id=order_id,
        device_id=payload.device_id,
        driver_id=payload.driver_id,
        cargo_name=payload.cargo_name,
        cargo_info=json.dumps(payload.cargo_info, ensure_ascii=False)
        if payload.cargo_info is not None
        else None,
        origin=payload.origin,
        destination=payload.destination,
        planned_start=planned_start,
        status=OrderStatus.PENDING,
        created_by=current_user.user_id,
    )
    db.add(order)

    for item in payload.alert_rules:
        db.add(
            AlertRule(
                order_id=order_id,
                metric=item.metric,
                min_value=item.min_value,
                max_value=item.max_value,
            )
        )

    db.commit()
    db.refresh(order)

    order = db.scalar(select(Order).where(Order.order_id == order_id).limit(1))
    notification_service.create_notification(
        user_id=order.driver_id,
        notification_type="order_assigned",
        title="收到新运单",
        content={
            "order_id": order.order_id,
            "device_id": order.device_id,
            "cargo_name": order.cargo_name,
            "origin": order.origin,
            "destination": order.destination,
            "planned_start": _datetime_text(order.planned_start),
        },
    )
    return success_response(data=_serialize_order(order, include_alert_rules=True), msg="运单创建成功")


@router.get("")
def list_orders(
    status: OrderStatus | None = Query(default=None),
    driver_id: int | None = Query(default=None, ge=1),
    device_id: str | None = Query(default=None),
    search: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> dict:
    base_stmt = _build_order_query(current_user, status, driver_id, device_id, search)
    total = db.scalar(select(func.count()).select_from(base_stmt.subquery()))

    orders = db.scalars(
        base_stmt.order_by(Order.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    archive_map = order_archive_service.list_order_archives(
        [order.order_id for order in orders],
        db=db,
    )
    items = [
        _serialize_order(
            order,
            include_alert_rules=False,
            archive_info=archive_map.get(order.order_id),
        )
        for order in orders
    ]
    return success_response(
        data={"items": items, "total": total, "page": page, "page_size": page_size}
    )


@router.get("/{order_id}")
def get_order_detail(
    order_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> dict:
    order = db.scalar(select(Order).where(Order.order_id == order_id).limit(1))
    if order is None:
        raise HTTPException(status_code=404, detail="运单不存在")

    _ensure_order_access(current_user, order)
    archive_info = order_archive_service.get_order_archive(order.order_id, db=db)
    return success_response(
        data=_serialize_order(order, include_alert_rules=True, archive_info=archive_info)
    )


@router.get("/{order_id}/alert-rules")
def get_order_alert_rules(
    order_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> dict:
    order = db.scalar(select(Order).where(Order.order_id == order_id).limit(1))
    if order is None:
        raise HTTPException(status_code=404, detail="运单不存在")

    _ensure_order_access(current_user, order)
    return success_response(data=[_serialize_alert_rule(rule) for rule in order.alert_rules])


@router.patch("/{order_id}/start")
def start_order(
    order_id: str,
    current_user: User = Depends(require_role(UserRole.DRIVER)),
    db: Session = Depends(get_db_session),
) -> dict:
    order = db.scalar(select(Order).where(Order.order_id == order_id).limit(1))
    if order is None:
        raise HTTPException(status_code=404, detail="运单不存在")
    if order.driver_id != current_user.user_id:
        raise HTTPException(status_code=403, detail="无权操作此运单")
    if order.status != OrderStatus.PENDING:
        raise HTTPException(status_code=400, detail="运单状态不允许此操作")

    order.status = OrderStatus.IN_TRANSIT
    if order.actual_start is None:
        order.actual_start = app_now()
    db.add(order)
    db.commit()
    db.refresh(order)
    return success_response(data=_serialize_order(order), msg="运单已开始运输")


@router.patch("/{order_id}/complete")
def complete_order(
    order_id: str,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(require_role(UserRole.DRIVER)),
    db: Session = Depends(get_db_session),
) -> dict:
    order = db.scalar(select(Order).where(Order.order_id == order_id).limit(1))
    if order is None:
        raise HTTPException(status_code=404, detail="运单不存在")
    if order.driver_id != current_user.user_id:
        raise HTTPException(status_code=403, detail="无权操作此运单")
    if order.status != OrderStatus.IN_TRANSIT:
        raise HTTPException(status_code=400, detail="运单状态不允许此操作")

    order.status = OrderStatus.COMPLETED
    order.actual_end = app_now()
    db.add(order)
    db.commit()
    db.refresh(order)
    background_tasks.add_task(_finalize_completed_order, order.order_id)
    return success_response(data=_serialize_order(order), msg="运单已完成，后台处理中")


@router.patch("/{order_id}/cancel")
def cancel_order(
    order_id: str,
    _: User = Depends(require_role(UserRole.SUPER_ADMIN, UserRole.ADMIN)),
    db: Session = Depends(get_db_session),
) -> dict:
    order = db.scalar(select(Order).where(Order.order_id == order_id).limit(1))
    if order is None:
        raise HTTPException(status_code=404, detail="运单不存在")
    if order.status in (OrderStatus.CANCELLED, OrderStatus.COMPLETED, OrderStatus.ABNORMAL_CLOSED):
        raise HTTPException(status_code=400, detail="当前运单状态不允许取消")

    order.status = OrderStatus.CANCELLED
    closed_anomaly_ids = _close_ongoing_anomalies(db, order.order_id, app_now())
    db.add(order)
    db.commit()
    db.refresh(order)
    for anomaly_id in closed_anomaly_ids:
        try:
            chain_service.submit_anomaly_end(anomaly_id)
        except Exception:  # noqa: BLE001
            continue
    return success_response(data=_serialize_order(order), msg="运单已取消")


@router.patch("/{order_id}/archive")
def archive_order(
    order_id: str,
    payload: OrderArchiveRequest,
    current_user: User = Depends(require_role(UserRole.SUPER_ADMIN)),
    db: Session = Depends(get_db_session),
) -> dict:
    order = db.scalar(select(Order).where(Order.order_id == order_id).limit(1))
    if order is None:
        raise HTTPException(status_code=404, detail="运单不存在")
    if payload.archived and order.status != OrderStatus.COMPLETED:
        raise HTTPException(status_code=400, detail="仅已完成运单支持测试归档")

    archive_info = order_archive_service.set_order_archive(
        order_id=order.order_id,
        archived=payload.archived,
        reason=payload.reason,
        operator=current_user,
        db=db,
    )
    db.commit()
    db.refresh(order)
    return success_response(
        data=_serialize_order(order, include_alert_rules=True, archive_info=archive_info),
        msg="运单已归档，后续自动哈希巡检将跳过"
        if payload.archived
        else "运单已取消归档，后续将恢复自动哈希巡检",
    )

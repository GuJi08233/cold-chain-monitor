from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core.auth import require_role
from ..core.deps import get_db_session
from ..core.response import success_response
from ..core.time_utils import format_app_datetime
from ..models import (
    Anomaly,
    AnomalyStatus,
    ChainRecord,
    Device,
    DeviceStatus,
    Order,
    OrderStatus,
    Ticket,
    TicketStatus,
    User,
    UserRole,
)

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


def _enum_value(value) -> str:
    return value.value if hasattr(value, "value") else str(value)


def _datetime_text(value: datetime | None) -> str | None:
    return format_app_datetime(value)


@router.get("/stats")
def get_dashboard_stats(
    _: User = Depends(require_role(UserRole.SUPER_ADMIN, UserRole.ADMIN)),
    db: Session = Depends(get_db_session),
) -> dict:
    devices_total = db.scalar(select(func.count(Device.device_id)))
    devices_online = db.scalar(
        select(func.count(Device.device_id)).where(Device.status == DeviceStatus.ONLINE)
    )
    orders_total = db.scalar(select(func.count(Order.order_id)))
    orders_in_transit = db.scalar(
        select(func.count(Order.order_id)).where(Order.status == OrderStatus.IN_TRANSIT)
    )
    anomalies_total = db.scalar(select(func.count(Anomaly.anomaly_id)))
    anomalies_ongoing = db.scalar(
        select(func.count(Anomaly.anomaly_id)).where(Anomaly.status == AnomalyStatus.ONGOING)
    )
    chain_records_total = db.scalar(select(func.count(ChainRecord.record_id)))

    return success_response(
        data={
            "devices_online": devices_online or 0,
            "devices_total": devices_total or 0,
            "orders_in_transit": orders_in_transit or 0,
            "orders_total": orders_total or 0,
            "anomalies_ongoing": anomalies_ongoing or 0,
            "anomalies_total": anomalies_total or 0,
            "chain_records_total": chain_records_total or 0,
        }
    )


@router.get("/recent-orders")
def get_recent_orders(
    _: User = Depends(require_role(UserRole.SUPER_ADMIN, UserRole.ADMIN)),
    db: Session = Depends(get_db_session),
) -> dict:
    rows = db.scalars(select(Order).order_by(Order.created_at.desc()).limit(10)).all()
    return success_response(
        data=[
            {
                "order_id": row.order_id,
                "device_id": row.device_id,
                "driver_id": row.driver_id,
                "status": _enum_value(row.status),
                "origin": row.origin,
                "destination": row.destination,
                "created_at": _datetime_text(row.created_at),
                "actual_start": _datetime_text(row.actual_start),
                "actual_end": _datetime_text(row.actual_end),
            }
            for row in rows
        ]
    )


@router.get("/recent-anomalies")
def get_recent_anomalies(
    _: User = Depends(require_role(UserRole.SUPER_ADMIN, UserRole.ADMIN)),
    db: Session = Depends(get_db_session),
) -> dict:
    rows = db.scalars(select(Anomaly).order_by(Anomaly.start_time.desc()).limit(10)).all()
    return success_response(
        data=[
            {
                "anomaly_id": row.anomaly_id,
                "order_id": row.order_id,
                "device_id": row.device_id,
                "metric": _enum_value(row.metric),
                "status": _enum_value(row.status),
                "trigger_value": row.trigger_value,
                "peak_value": row.peak_value,
                "start_time": _datetime_text(row.start_time),
                "end_time": _datetime_text(row.end_time),
                "is_reported": row.is_reported,
            }
            for row in rows
        ]
    )


@router.get("/pending-tickets")
def get_pending_tickets_count(
    _: User = Depends(require_role(UserRole.SUPER_ADMIN, UserRole.ADMIN)),
    db: Session = Depends(get_db_session),
) -> dict:
    count = db.scalar(
        select(func.count(Ticket.ticket_id)).where(Ticket.status == TicketStatus.PENDING)
    )
    return success_response(data={"pending_tickets": count or 0})

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core.auth import get_current_user
from ..core.deps import get_db_session
from ..core.response import success_response
from ..models import Anomaly, AnomalyMetric, AnomalyStatus, Order, User, UserRole

router = APIRouter(tags=["anomalies"])


def _enum_value(value) -> str:
    return value.value if hasattr(value, "value") else str(value)


def _datetime_text(value):
    return value.isoformat(sep=" ", timespec="seconds") if value else None


def _serialize_anomaly(anomaly: Anomaly) -> dict:
    return {
        "anomaly_id": anomaly.anomaly_id,
        "order_id": anomaly.order_id,
        "device_id": anomaly.device_id,
        "rule_id": anomaly.rule_id,
        "metric": _enum_value(anomaly.metric),
        "trigger_value": anomaly.trigger_value,
        "threshold_min": anomaly.threshold_min,
        "threshold_max": anomaly.threshold_max,
        "start_time": _datetime_text(anomaly.start_time),
        "end_time": _datetime_text(anomaly.end_time),
        "status": _enum_value(anomaly.status),
        "peak_value": anomaly.peak_value,
        "is_reported": anomaly.is_reported,
    }


def _ensure_anomaly_access(db: Session, current_user: User, anomaly: Anomaly) -> None:
    if current_user.role != UserRole.DRIVER:
        return
    order = db.scalar(select(Order).where(Order.order_id == anomaly.order_id).limit(1))
    if order is None or order.driver_id != current_user.user_id:
        raise HTTPException(status_code=403, detail="无权访问此异常记录")


@router.get("/anomalies")
def list_anomalies(
    order_id: str | None = Query(default=None),
    status: AnomalyStatus | None = Query(default=None),
    metric: AnomalyMetric | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> dict:
    stmt = select(Anomaly)
    if current_user.role == UserRole.DRIVER:
        stmt = stmt.join(Order, Anomaly.order_id == Order.order_id).where(
            Order.driver_id == current_user.user_id
        )
    if order_id:
        stmt = stmt.where(Anomaly.order_id == order_id)
    if status is not None:
        stmt = stmt.where(Anomaly.status == status)
    if metric is not None:
        stmt = stmt.where(Anomaly.metric == metric)

    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(
        stmt.order_by(Anomaly.start_time.desc()).offset((page - 1) * page_size).limit(page_size)
    ).all()
    return success_response(
        data={
            "items": [_serialize_anomaly(row) for row in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    )


@router.get("/anomalies/{anomaly_id}")
def get_anomaly_detail(
    anomaly_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> dict:
    anomaly = db.get(Anomaly, anomaly_id)
    if anomaly is None:
        raise HTTPException(status_code=404, detail="异常记录不存在")
    _ensure_anomaly_access(db, current_user, anomaly)
    return success_response(data=_serialize_anomaly(anomaly))


@router.get("/orders/{order_id}/anomalies")
def list_order_anomalies(
    order_id: str,
    status: AnomalyStatus | None = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> dict:
    order = db.scalar(select(Order).where(Order.order_id == order_id).limit(1))
    if order is None:
        raise HTTPException(status_code=404, detail="运单不存在")
    if current_user.role == UserRole.DRIVER and order.driver_id != current_user.user_id:
        raise HTTPException(status_code=403, detail="无权访问此运单")

    stmt = select(Anomaly).where(Anomaly.order_id == order_id)
    if status is not None:
        stmt = stmt.where(Anomaly.status == status)
    rows = db.scalars(stmt.order_by(Anomaly.start_time.desc())).all()
    return success_response(data=[_serialize_anomaly(row) for row in rows])


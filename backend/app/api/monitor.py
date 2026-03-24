from datetime import datetime, timedelta
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.auth import get_current_user
from ..core.deps import get_db_session
from ..core.response import success_response
from ..core.time_utils import app_now, normalize_app_datetime, parse_app_datetime
from ..models import Order, OrderStatus, User, UserRole
from ..services.tdengine_service import tdengine_service

router = APIRouter(prefix="/monitor", tags=["monitor"])
logger = logging.getLogger(__name__)

ALLOWED_METRICS = {"all", "temperature", "humidity", "pressure"}
ALLOWED_INTERVALS = {"raw", "1m", "5m", "10m", "1h", "auto"}


def _enum_value(value) -> str:
    return value.value if hasattr(value, "value") else str(value)


def _parse_datetime(raw_value: str | None, field_name: str) -> datetime | None:
    parsed = parse_app_datetime(raw_value)
    if parsed is None and raw_value and raw_value.strip():
        raise HTTPException(status_code=400, detail=f"{field_name} 时间格式错误")
    return parsed


def _auto_interval(start: datetime, end: datetime) -> str:
    span = end - start
    if span <= timedelta(minutes=30):
        return "raw"
    if span <= timedelta(hours=2):
        return "1m"
    if span <= timedelta(hours=12):
        return "5m"
    if span <= timedelta(hours=48):
        return "10m"
    return "1h"


def _resolve_time_window(
    mode: str,
    recent: str,
    start_text: str | None,
    end_text: str | None,
) -> tuple[datetime, datetime]:
    now = app_now()
    if mode == "realtime":
        return now - timedelta(minutes=5), now

    if mode == "recent":
        recent_map = {
            "30m": timedelta(minutes=30),
            "1h": timedelta(hours=1),
            "6h": timedelta(hours=6),
            "12h": timedelta(hours=12),
            "24h": timedelta(hours=24),
        }
        duration = recent_map.get(recent)
        if duration is None:
            raise HTTPException(status_code=400, detail="recent 参数不合法")
        return now - duration, now

    if mode == "custom":
        start_dt = _parse_datetime(start_text, "start_time")
        end_dt = _parse_datetime(end_text, "end_time")
        if start_dt is None or end_dt is None:
            raise HTTPException(status_code=400, detail="custom 模式必须提供 start_time 与 end_time")
        if start_dt >= end_dt:
            raise HTTPException(status_code=400, detail="start_time 必须早于 end_time")
        return normalize_app_datetime(start_dt), normalize_app_datetime(end_dt)

    raise HTTPException(status_code=400, detail="mode 参数不合法")


def _ensure_order_access(db: Session, current_user: User, order_id: str) -> Order:
    order = db.scalar(select(Order).where(Order.order_id == order_id).limit(1))
    if order is None:
        raise HTTPException(status_code=404, detail="运单不存在")
    if current_user.role == UserRole.DRIVER and order.driver_id != current_user.user_id:
        raise HTTPException(status_code=403, detail="无权访问此运单")
    return order


def _set_cache_header(response: Response, order: Order) -> None:
    if order.status == OrderStatus.COMPLETED:
        response.headers["Cache-Control"] = "max-age=86400"
    else:
        response.headers["Cache-Control"] = "no-cache"


def _raise_tdengine_query_error(payload: dict) -> None:
    logger.warning("TDengine query failed: %s", payload)
    raise HTTPException(status_code=502, detail="监控数据查询失败，请稍后重试")


@router.get("/{order_id}/latest")
def get_latest_sensor_data(
    order_id: str,
    response: Response,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> dict:
    order = _ensure_order_access(db, current_user, order_id)
    result = tdengine_service.query_latest_sensor(order.device_id, order.order_id)
    if not result.ok and not tdengine_service.is_table_not_exists(result.payload):
        _raise_tdengine_query_error(result.payload)
    rows = [] if not result.ok else tdengine_service.payload_to_rows(result.payload)
    latest = rows[0] if rows else None
    _set_cache_header(response, order)
    return success_response(data={"order_id": order_id, "latest": latest})


@router.get("/{order_id}/sensor")
def get_sensor_data(
    order_id: str,
    response: Response,
    mode: str = Query(default="recent"),
    metric: str = Query(default="all"),
    recent: str = Query(default="1h"),
    start_time: str | None = Query(default=None),
    end_time: str | None = Query(default=None),
    interval: str = Query(default="auto"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> dict:
    if metric not in ALLOWED_METRICS:
        raise HTTPException(status_code=400, detail="metric 参数不合法")
    if interval not in ALLOWED_INTERVALS:
        raise HTTPException(status_code=400, detail="interval 参数不合法")

    order = _ensure_order_access(db, current_user, order_id)
    window_start, window_end = _resolve_time_window(mode, recent, start_time, end_time)
    selected_interval = "raw" if mode == "realtime" else (
        _auto_interval(window_start, window_end) if interval == "auto" else interval
    )

    metrics = ["temperature", "humidity", "pressure"]
    if metric != "all":
        metrics = [metric]

    if selected_interval == "raw":
        query_result = tdengine_service.query_sensor_raw(
            order.device_id, order.order_id, window_start, window_end, limit=2000
        )
        if not query_result.ok and not tdengine_service.is_table_not_exists(query_result.payload):
            _raise_tdengine_query_error(query_result.payload)
        rows = [] if not query_result.ok else tdengine_service.payload_to_rows(query_result.payload)
        metric_payload = {m: [] for m in metrics}
        for row in rows:
            ts = str(row.get("ts"))
            for m in metrics:
                metric_payload[m].append({"ts": ts, "value": row.get(m)})
    else:
        query_result = tdengine_service.query_sensor_agg(
            order.device_id,
            order.order_id,
            window_start,
            window_end,
            interval=selected_interval,
            limit=2000,
        )
        if not query_result.ok and not tdengine_service.is_table_not_exists(query_result.payload):
            _raise_tdengine_query_error(query_result.payload)
        rows = [] if not query_result.ok else tdengine_service.payload_to_rows(query_result.payload)
        metric_payload = {m: [] for m in metrics}
        for row in rows:
            ts = str(row.get("ts"))
            for m in metrics:
                metric_payload[m].append(
                    {
                        "ts": ts,
                        "avg": row.get(f"{m}_avg"),
                        "min": row.get(f"{m}_min"),
                        "max": row.get(f"{m}_max"),
                    }
                )

    _set_cache_header(response, order)
    return success_response(
        data={
            "order_id": order_id,
            "mode": mode,
            "interval": selected_interval,
            "total_points": len(rows),
            "metrics": metric_payload,
        }
    )


@router.get("/{order_id}/track")
def get_track_data(
    order_id: str,
    response: Response,
    start_time: str | None = Query(default=None),
    end_time: str | None = Query(default=None),
    simplify: bool = Query(default=True),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> dict:
    order = _ensure_order_access(db, current_user, order_id)
    start_dt = _parse_datetime(start_time, "start_time")
    end_dt = _parse_datetime(end_time, "end_time")

    query_result = tdengine_service.query_track(
        device_id=order.device_id,
        order_id=order.order_id,
        start_time=start_dt,
        end_time=end_dt,
        limit=5000,
    )
    if not query_result.ok and not tdengine_service.is_table_not_exists(query_result.payload):
        _raise_tdengine_query_error(query_result.payload)
    rows = [] if not query_result.ok else tdengine_service.payload_to_rows(query_result.payload)
    points = [
        {"ts": str(row.get("ts")), "lat": row.get("gps_lat"), "lng": row.get("gps_lng")}
        for row in rows
    ]

    if simplify and len(points) > 800:
        step = max(1, len(points) // 800)
        sampled = points[::step]
        if sampled[-1] != points[-1]:
            sampled.append(points[-1])
        points = sampled

    _set_cache_header(response, order)
    return success_response(data={"order_id": order_id, "points": points})

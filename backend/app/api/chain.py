import json
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core.auth import get_current_user, require_role
from ..core.deps import get_db_session
from ..core.response import success_response
from ..core.time_utils import format_app_datetime, from_unix_seconds
from ..models import (
    Anomaly,
    ChainRecord,
    ChainRecordStatus,
    ChainRecordType,
    DriverProfile,
    Order,
    OrderStatus,
    User,
    UserRole,
)
from ..services.chain_service import ChainServiceError, chain_service

router = APIRouter(prefix="/chain", tags=["chain"])
logger = logging.getLogger(__name__)


def _raise_chain_service_error(action: str, exc: Exception) -> None:
    logger.warning("chain action failed (%s): %s", action, exc)
    raise HTTPException(status_code=502, detail="区块链服务暂不可用，请稍后重试")


def _enum_value(value) -> str:
    return value.value if hasattr(value, "value") else str(value)


def _datetime_text(value: datetime | None) -> str | None:
    return format_app_datetime(value)


def _datetime_from_unix(ts: int | None) -> str | None:
    if ts is None or ts <= 0:
        return None
    return format_app_datetime(from_unix_seconds(ts))


def _parse_payload(raw_text: str):
    try:
        return json.loads(raw_text)
    except Exception:  # noqa: BLE001
        return raw_text


def _normalize_tx_hash(value: str | None) -> str | None:
    if not value:
        return value
    return value if value.startswith("0x") else f"0x{value}"


def _normalize_hash_text(value: str | None) -> str:
    if not value:
        return ""
    text = str(value).strip().lower()
    if text.startswith("0x"):
        text = text[2:]
    return text


def _ensure_order_access(current_user: User, order: Order) -> None:
    if current_user.role == UserRole.DRIVER and order.driver_id != current_user.user_id:
        raise HTTPException(status_code=403, detail="无权访问此运单")


def _ensure_anomaly_access(db: Session, current_user: User, anomaly: Anomaly) -> None:
    if current_user.role != UserRole.DRIVER:
        return
    order = db.scalar(select(Order).where(Order.order_id == anomaly.order_id).limit(1))
    if order is None or order.driver_id != current_user.user_id:
        raise HTTPException(status_code=403, detail="无权访问此异常记录")


def _serialize_chain_record(row: ChainRecord) -> dict:
    return {
        "record_id": row.record_id,
        "type": _enum_value(row.type),
        "order_id": row.order_id,
        "anomaly_id": row.anomaly_id,
        "payload": _parse_payload(row.payload),
        "data_hash": row.data_hash,
        "tx_hash": _normalize_tx_hash(row.tx_hash),
        "block_number": row.block_number,
        "status": _enum_value(row.status),
        "created_at": _datetime_text(row.created_at),
    }


@router.get("/order/{order_id}")
def get_order_chain_detail(
    order_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> dict:
    order = db.scalar(select(Order).where(Order.order_id == order_id).limit(1))
    if order is None:
        raise HTTPException(status_code=404, detail="运单不存在")
    _ensure_order_access(current_user, order)
    if order.status != OrderStatus.COMPLETED:
        raise HTTPException(status_code=400, detail="运单未完成，暂无可查询的链上哈希")

    record = db.scalar(
        select(ChainRecord)
        .where(
            ChainRecord.type == ChainRecordType.ORDER_HASH,
            ChainRecord.order_id == order_id,
            ChainRecord.status == ChainRecordStatus.CONFIRMED,
        )
        .order_by(ChainRecord.record_id.desc())
        .limit(1)
    )

    try:
        chain_data = chain_service.get_order_hash(order_id)
    except ChainServiceError as exc:
        _raise_chain_service_error("get_order_hash", exc)
    if chain_data is None:
        raise HTTPException(status_code=404, detail="链上不存在该运单哈希")

    return success_response(
        data={
            "order_id": order.order_id,
            "local_hash": order.data_hash,
            "chain_hash": chain_data["data_hash"],
            "data_hash_mode": chain_data.get("data_hash_mode"),
            "chain_timestamp": _datetime_from_unix(chain_data["timestamp"]),
            "uploader": chain_data["uploader"],
            "tx_hash": _normalize_tx_hash(record.tx_hash) if record is not None else None,
            "block_number": record.block_number if record is not None else None,
        }
    )


@router.get("/order/{order_id}/verify")
def verify_order_hash(
    order_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> dict:
    order = db.scalar(select(Order).where(Order.order_id == order_id).limit(1))
    if order is None:
        raise HTTPException(status_code=404, detail="运单不存在")
    _ensure_order_access(current_user, order)
    if order.status != OrderStatus.COMPLETED:
        raise HTTPException(status_code=400, detail="运单未完成，暂无可校验哈希")

    chain_record = db.scalar(
        select(ChainRecord)
        .where(
            ChainRecord.type == ChainRecordType.ORDER_HASH,
            ChainRecord.order_id == order_id,
            ChainRecord.status == ChainRecordStatus.CONFIRMED,
        )
        .order_by(ChainRecord.record_id.desc())
        .limit(1)
    )

    try:
        chain_data = chain_service.get_order_hash(order_id)
    except ChainServiceError as exc:
        _raise_chain_service_error("get_order_hash", exc)

    match = False
    if chain_data is not None and order.data_hash:
        try:
            match = chain_service.verify_order_hash(order_id, order.data_hash)
        except ChainServiceError as exc:
            _raise_chain_service_error("verify_order_hash", exc)

    return success_response(
        data={
            "order_id": order.order_id,
            "local_hash": order.data_hash,
            "chain_hash": chain_data["data_hash"] if chain_data else None,
            "data_hash_mode": chain_data.get("data_hash_mode") if chain_data else None,
            "match": match,
            "chain_timestamp": _datetime_from_unix(chain_data["timestamp"]) if chain_data else None,
            "tx_hash": _normalize_tx_hash(chain_record.tx_hash) if chain_record is not None else None,
            "block_number": chain_record.block_number if chain_record is not None else None,
        }
    )


@router.get("/anomaly/{anomaly_id}")
def get_anomaly_chain_detail(
    anomaly_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> dict:
    anomaly = db.get(Anomaly, anomaly_id)
    if anomaly is None:
        raise HTTPException(status_code=404, detail="异常记录不存在")
    _ensure_anomaly_access(db, current_user, anomaly)

    start_record = db.scalar(
        select(ChainRecord)
        .where(
            ChainRecord.type == ChainRecordType.ANOMALY_START,
            ChainRecord.anomaly_id == anomaly_id,
            ChainRecord.status == ChainRecordStatus.CONFIRMED,
        )
        .order_by(ChainRecord.record_id.desc())
        .limit(1)
    )
    if start_record is None:
        raise HTTPException(status_code=404, detail="链上不存在该异常的开始记录")

    start_payload = _parse_payload(start_record.payload)
    if not isinstance(start_payload, dict):
        raise HTTPException(status_code=500, detail="异常上链记录格式错误")

    chain_anomaly_id = start_payload.get("chain_anomaly_id")
    if chain_anomaly_id is None:
        raise HTTPException(status_code=404, detail="未找到 chain_anomaly_id")

    try:
        chain_data = chain_service.get_anomaly(int(chain_anomaly_id))
    except ChainServiceError as exc:
        _raise_chain_service_error("get_anomaly", exc)
    if chain_data is None:
        raise HTTPException(status_code=404, detail="链上不存在该异常记录")

    end_record = db.scalar(
        select(ChainRecord)
        .where(
            ChainRecord.type == ChainRecordType.ANOMALY_END,
            ChainRecord.anomaly_id == anomaly_id,
            ChainRecord.status == ChainRecordStatus.CONFIRMED,
        )
        .order_by(ChainRecord.record_id.desc())
        .limit(1)
    )

    decrypted_info = chain_service.decrypt_anomaly_info(chain_data.get("encrypted_info") or "")
    decrypted_info_source = "chain"
    if decrypted_info is None:
        local_encrypted_info = str(start_payload.get("encrypted_info") or "")
        if local_encrypted_info:
            decrypted_info = chain_service.decrypt_anomaly_info(local_encrypted_info)
            if decrypted_info is not None:
                decrypted_info_source = "local_start_payload"
            else:
                decrypted_info_source = "none"
        else:
            decrypted_info_source = "none"

    order = db.scalar(select(Order).where(Order.order_id == anomaly.order_id).limit(1))
    driver_user = None
    driver_profile = None
    if order is not None:
        driver_user = db.get(User, order.driver_id)
        driver_profile = db.scalar(
            select(DriverProfile).where(DriverProfile.driver_id == order.driver_id).limit(1)
        )

    driver_identity = None
    if order is not None:
        driver_identity = {
            "driver_id": order.driver_id,
            "username": driver_user.username if driver_user is not None else None,
            "display_name": driver_user.display_name if driver_user is not None else None,
            "real_name": driver_profile.real_name if driver_profile is not None else None,
        }

    local_anchor = {}
    try:
        local_anchor = chain_service._build_anomaly_start_payload(db, anomaly)  # noqa: SLF001
    except Exception:  # noqa: BLE001
        local_anchor = {}

    def _anchor_match(chain_value: str | None, local_value: str | None) -> bool | None:
        chain_hash = _normalize_hash_text(chain_value)
        local_hash = _normalize_hash_text(local_value)
        if not chain_hash or not local_hash:
            return None
        return chain_hash == local_hash

    driver_anchor_match = {
        "driver_ref_hash": _anchor_match(
            chain_data.get("driver_ref_hash"),
            local_anchor.get("driver_ref_hash"),
        ),
        "id_commit": _anchor_match(
            chain_data.get("id_commit"),
            local_anchor.get("id_commit"),
        ),
        "profile_hash": _anchor_match(
            chain_data.get("profile_hash"),
            local_anchor.get("profile_hash"),
        ),
    }

    return success_response(
        data={
            "anomaly_id": anomaly_id,
            "chain_anomaly_id": int(chain_anomaly_id),
            "order_id": chain_data["order_id"],
            "anomaly_type": chain_data["anomaly_type"],
            "trigger_value": chain_data["trigger_value_scaled"] / 100.0,
            "start_time": _datetime_from_unix(chain_data["start_time"]),
            "end_time": _datetime_from_unix(chain_data["end_time"]),
            "peak_value": chain_data["peak_value_scaled"] / 100.0,
            "closed": chain_data["closed"],
            "encrypted_info": chain_data["encrypted_info"],
            "encrypted_info_hash": chain_data.get("encrypted_info_hash"),
            "has_inline_encrypted_info": chain_data.get("has_inline_encrypted_info"),
            "driver_anchor_exists": chain_data.get("driver_anchor_exists"),
            "driver_ref_hash": chain_data.get("driver_ref_hash"),
            "id_commit": chain_data.get("id_commit"),
            "profile_hash": chain_data.get("profile_hash"),
            "driver_anchor_updated_at": _datetime_from_unix(
                chain_data.get("driver_anchor_updated_at")
            ),
            "driver_anchor_uploader": chain_data.get("driver_anchor_uploader"),
            "decrypted_info": decrypted_info,
            "decrypted_info_source": decrypted_info_source,
            "driver_identity": driver_identity,
            "driver_anchor_match": driver_anchor_match,
            "uploader": chain_data["uploader"],
            "start_tx_hash": _normalize_tx_hash(start_record.tx_hash),
            "start_block_number": start_record.block_number,
            "end_tx_hash": _normalize_tx_hash(end_record.tx_hash) if end_record is not None else None,
            "end_block_number": end_record.block_number if end_record is not None else None,
        }
    )


@router.get("/records")
def list_chain_records(
    status: ChainRecordStatus | None = Query(default=None),
    record_type: ChainRecordType | None = Query(default=None, alias="type"),
    order_id: str | None = Query(default=None),
    anomaly_id: int | None = Query(default=None, ge=1),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    _: User = Depends(require_role(UserRole.SUPER_ADMIN, UserRole.ADMIN)),
    db: Session = Depends(get_db_session),
) -> dict:
    stmt = select(ChainRecord)
    if status is not None:
        stmt = stmt.where(ChainRecord.status == status)
    if record_type is not None:
        stmt = stmt.where(ChainRecord.type == record_type)
    if order_id:
        stmt = stmt.where(ChainRecord.order_id == order_id)
    if anomaly_id is not None:
        stmt = stmt.where(ChainRecord.anomaly_id == anomaly_id)

    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(
        stmt.order_by(ChainRecord.record_id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return success_response(
        data={
            "items": [_serialize_chain_record(row) for row in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    )


@router.post("/records/{record_id}/retry")
def retry_chain_record(
    record_id: int,
    _: User = Depends(require_role(UserRole.SUPER_ADMIN, UserRole.ADMIN)),
    db: Session = Depends(get_db_session),
) -> dict:
    row = db.get(ChainRecord, record_id)
    if row is None:
        raise HTTPException(status_code=404, detail="上链记录不存在")
    if row.status != ChainRecordStatus.FAILED:
        raise HTTPException(status_code=400, detail="仅支持重试 failed 状态记录")
    try:
        chain_service.retry_record(record_id)
    except ChainServiceError as exc:
        _raise_chain_service_error("retry_record", exc)

    db.expire_all()
    refreshed = db.get(ChainRecord, record_id)
    return success_response(data=_serialize_chain_record(refreshed), msg="已提交重试")

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ..core.auth import get_current_user, require_role
from ..core.deps import get_db_session
from ..core.response import success_response
from ..models import (
    Anomaly,
    AnomalyStatus,
    Order,
    OrderStatus,
    Ticket,
    TicketStatus,
    TicketType,
    User,
    UserRole,
)
from ..schemas.ticket import TicketCreateRequest, TicketReviewRequest
from ..services.chain_service import chain_service
from ..services.notification_service import notification_service

router = APIRouter(prefix="/tickets", tags=["tickets"])


def _enum_value(value) -> str:
    return value.value if hasattr(value, "value") else str(value)


def _datetime_text(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat(sep=" ", timespec="seconds")


def _serialize_ticket(row: Ticket) -> dict:
    submitter = None
    if row.submitter is not None:
        submitter = {
            "user_id": row.submitter.user_id,
            "username": row.submitter.username,
            "display_name": row.submitter.display_name,
        }

    reviewer = None
    if row.reviewer is not None:
        reviewer = {
            "user_id": row.reviewer.user_id,
            "username": row.reviewer.username,
            "display_name": row.reviewer.display_name,
        }

    return {
        "ticket_id": row.ticket_id,
        "type": _enum_value(row.type),
        "submitter_id": row.submitter_id,
        "order_id": row.order_id,
        "reason": row.reason,
        "status": _enum_value(row.status),
        "reviewer_id": row.reviewer_id,
        "review_comment": row.review_comment,
        "reviewed_at": _datetime_text(row.reviewed_at),
        "created_at": _datetime_text(row.created_at),
        "submitter": submitter,
        "reviewer": reviewer,
    }


def _ensure_ticket_access(current_user: User, row: Ticket) -> None:
    if current_user.role == UserRole.DRIVER and row.submitter_id != current_user.user_id:
        raise HTTPException(status_code=403, detail="无权访问此工单")


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


@router.post("")
def create_ticket(
    payload: TicketCreateRequest,
    current_user: User = Depends(require_role(UserRole.DRIVER)),
    db: Session = Depends(get_db_session),
) -> dict:
    if payload.order_id:
        order = db.scalar(select(Order).where(Order.order_id == payload.order_id).limit(1))
        if order is None:
            raise HTTPException(status_code=404, detail="运单不存在")
        if order.driver_id != current_user.user_id:
            raise HTTPException(status_code=403, detail="无权对该运单发起工单")

    ticket = Ticket(
        type=payload.type,
        submitter_id=current_user.user_id,
        order_id=payload.order_id,
        reason=payload.reason,
        status=TicketStatus.PENDING,
    )
    db.add(ticket)
    db.commit()
    db.refresh(ticket)

    notification_service.notify_admins(
        notification_type="new_ticket",
        title="收到新工单",
        content={
            "ticket_id": ticket.ticket_id,
            "type": _enum_value(ticket.type),
            "order_id": ticket.order_id,
            "submitter_id": ticket.submitter_id,
        },
    )

    ticket = db.get(Ticket, ticket.ticket_id)
    return success_response(data=_serialize_ticket(ticket), msg="工单提交成功")


@router.get("")
def list_tickets(
    status: TicketStatus | None = Query(default=None),
    ticket_type: TicketType | None = Query(default=None, alias="type"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> dict:
    stmt = select(Ticket)
    if current_user.role == UserRole.DRIVER:
        stmt = stmt.where(Ticket.submitter_id == current_user.user_id)
    if status is not None:
        stmt = stmt.where(Ticket.status == status)
    if ticket_type is not None:
        stmt = stmt.where(Ticket.type == ticket_type)

    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(
        stmt.order_by(Ticket.ticket_id.desc()).offset((page - 1) * page_size).limit(page_size)
    ).all()
    return success_response(
        data={
            "items": [_serialize_ticket(row) for row in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    )


@router.get("/{ticket_id}")
def get_ticket_detail(
    ticket_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> dict:
    row = db.get(Ticket, ticket_id)
    if row is None:
        raise HTTPException(status_code=404, detail="工单不存在")
    _ensure_ticket_access(current_user, row)
    return success_response(data=_serialize_ticket(row))


@router.patch("/{ticket_id}/approve")
def approve_ticket(
    ticket_id: int,
    payload: TicketReviewRequest,
    current_user: User = Depends(require_role(UserRole.SUPER_ADMIN, UserRole.ADMIN)),
    db: Session = Depends(get_db_session),
) -> dict:
    row = db.get(Ticket, ticket_id)
    if row is None:
        raise HTTPException(status_code=404, detail="工单不存在")
    if row.status != TicketStatus.PENDING:
        raise HTTPException(status_code=400, detail="仅 pending 工单可审批")

    closed_anomaly_ids: list[int] = []
    if row.type == TicketType.CANCEL_ORDER:
        if not row.order_id:
            raise HTTPException(status_code=400, detail="cancel_order 工单缺少 order_id")
        order = db.scalar(select(Order).where(Order.order_id == row.order_id).limit(1))
        if order is None:
            raise HTTPException(status_code=404, detail="工单关联运单不存在")
        if order.status in (OrderStatus.COMPLETED, OrderStatus.ABNORMAL_CLOSED):
            raise HTTPException(status_code=400, detail="运单已结束，无法取消")
        if order.status != OrderStatus.CANCELLED:
            now = datetime.now()
            order.status = OrderStatus.CANCELLED
            if order.actual_end is None:
                order.actual_end = now
            closed_anomaly_ids = _close_ongoing_anomalies(db, order.order_id, now)
            db.add(order)
    elif row.type == TicketType.ANOMALY_REPORT:
        if not row.order_id:
            raise HTTPException(status_code=400, detail="anomaly_report 工单缺少 order_id")
        db.execute(
            update(Anomaly).where(Anomaly.order_id == row.order_id).values(is_reported=True)
        )

    row.status = TicketStatus.APPROVED
    row.reviewer_id = current_user.user_id
    row.review_comment = payload.comment
    row.reviewed_at = datetime.now()
    db.add(row)
    db.commit()
    db.refresh(row)

    for anomaly_id in closed_anomaly_ids:
        try:
            chain_service.submit_anomaly_end(anomaly_id)
        except Exception:  # noqa: BLE001
            continue

    notification_service.create_notification(
        user_id=row.submitter_id,
        notification_type="ticket_result",
        title="工单审批通过",
        content={
            "ticket_id": row.ticket_id,
            "status": _enum_value(row.status),
            "comment": row.review_comment,
            "type": _enum_value(row.type),
            "order_id": row.order_id,
        },
    )
    return success_response(data=_serialize_ticket(row), msg="工单审批通过")


@router.patch("/{ticket_id}/reject")
def reject_ticket(
    ticket_id: int,
    payload: TicketReviewRequest,
    current_user: User = Depends(require_role(UserRole.SUPER_ADMIN, UserRole.ADMIN)),
    db: Session = Depends(get_db_session),
) -> dict:
    row = db.get(Ticket, ticket_id)
    if row is None:
        raise HTTPException(status_code=404, detail="工单不存在")
    if row.status != TicketStatus.PENDING:
        raise HTTPException(status_code=400, detail="仅 pending 工单可审批")

    row.status = TicketStatus.REJECTED
    row.reviewer_id = current_user.user_id
    row.review_comment = payload.comment
    row.reviewed_at = datetime.now()
    db.add(row)
    db.commit()
    db.refresh(row)

    notification_service.create_notification(
        user_id=row.submitter_id,
        notification_type="ticket_result",
        title="工单审批拒绝",
        content={
            "ticket_id": row.ticket_id,
            "status": _enum_value(row.status),
            "comment": row.review_comment,
            "type": _enum_value(row.type),
            "order_id": row.order_id,
        },
    )
    return success_response(data=_serialize_ticket(row), msg="工单审批拒绝")

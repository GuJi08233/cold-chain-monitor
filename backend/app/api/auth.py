from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..core.auth import create_access_token, get_current_user
from ..core.deps import get_db_session
from ..core.response import success_response
from ..core.time_utils import format_app_datetime
from ..core.security import hash_password, validate_password_strength, verify_password
from ..models import DriverProfile, Order, User, UserRole, UserStatus
from ..schemas.auth import ChangePasswordRequest, LoginRequest, RegisterRequest, WsTicketRequest
from ..services.login_security_service import login_security_service
from ..services.notification_service import notification_service
from ..services.ws_ticket_service import (
    WS_TICKET_SCOPE_MONITOR,
    WS_TICKET_SCOPE_NOTIFICATIONS,
    ws_ticket_service,
)

router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()


@router.post("/register")
def register_driver(payload: RegisterRequest, db: Session = Depends(get_db_session)) -> dict:
    try:
        validate_password_strength(payload.password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    username_exists = db.scalar(select(User).where(User.username == payload.username).limit(1))
    if username_exists:
        raise HTTPException(status_code=400, detail="用户名已存在")

    id_card_exists = db.scalar(
        select(DriverProfile).where(DriverProfile.id_card == payload.id_card).limit(1)
    )
    if id_card_exists:
        raise HTTPException(status_code=400, detail="身份证号已存在")

    user = User(
        username=payload.username,
        password_hash=hash_password(payload.password),
        role=UserRole.DRIVER,
        status=UserStatus.PENDING,
        display_name=payload.real_name,
    )
    user.driver_profile = DriverProfile(
        real_name=payload.real_name,
        id_card=payload.id_card,
        phone=payload.phone,
        plate_number=payload.plate_number,
        vehicle_type=payload.vehicle_type,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    notification_service.notify_admins(
        notification_type="driver_pending",
        title="新司机待审批",
        content={
            "user_id": user.user_id,
            "username": user.username,
            "real_name": payload.real_name,
        },
    )

    return success_response(
        data={
            "user_id": user.user_id,
            "username": user.username,
            "status": user.status.value if hasattr(user.status, "value") else str(user.status),
        },
        msg="注册成功，等待管理员审批",
    )


@router.post("/login")
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db_session)) -> dict:
    client_ip = request.client.host if request.client and request.client.host else "unknown"
    login_security_service.check_request_allowed(payload.username, client_ip)

    user = db.scalar(select(User).where(User.username == payload.username).limit(1))
    if user is None or not verify_password(payload.password, user.password_hash):
        login_security_service.record_failure(payload.username)
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    if user.status == UserStatus.PENDING:
        raise HTTPException(status_code=403, detail="账户审批中，请联系管理员")
    if user.status == UserStatus.DISABLED:
        raise HTTPException(status_code=403, detail="账户已禁用")

    login_security_service.record_success(payload.username)
    access_token = create_access_token(user)
    role = user.role.value if hasattr(user.role, "value") else str(user.role)

    return success_response(
        data={
            "access_token": access_token,
            "token_type": "bearer",
            "expires_in": settings.jwt_expire_minutes * 60,
            "user": {
                "user_id": user.user_id,
                "username": user.username,
                "role": role,
                "display_name": user.display_name,
            },
        }
    )


@router.get("/me")
def get_me(current_user: User = Depends(get_current_user)) -> dict:
    role = (
        current_user.role.value
        if hasattr(current_user.role, "value")
        else str(current_user.role)
    )
    status = (
        current_user.status.value
        if hasattr(current_user.status, "value")
        else str(current_user.status)
    )

    profile = None
    if current_user.driver_profile is not None:
        profile = {
            "real_name": current_user.driver_profile.real_name,
            "id_card": current_user.driver_profile.id_card,
            "phone": current_user.driver_profile.phone,
            "plate_number": current_user.driver_profile.plate_number,
            "vehicle_type": current_user.driver_profile.vehicle_type,
        }

    return success_response(
        data={
            "user_id": current_user.user_id,
            "username": current_user.username,
            "role": role,
            "display_name": current_user.display_name,
            "status": status,
            "created_at": format_app_datetime(current_user.created_at),
            "driver_profile": profile,
        }
    )


@router.patch("/password")
def change_password(
    payload: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> dict:
    if not verify_password(payload.old_password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="旧密码错误")
    if payload.old_password == payload.new_password:
        raise HTTPException(status_code=400, detail="新密码不能与旧密码相同")

    try:
        validate_password_strength(payload.new_password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    current_user.password_hash = hash_password(payload.new_password)
    current_user.password_changed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.add(current_user)
    db.commit()

    return success_response(msg="密码修改成功")


@router.post("/ws-ticket")
def create_ws_ticket(
    payload: WsTicketRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> dict:
    if payload.scope == WS_TICKET_SCOPE_MONITOR:
        if not payload.order_id:
            raise HTTPException(status_code=400, detail="monitor scope 需要提供 order_id")
        order = db.scalar(select(Order).where(Order.order_id == payload.order_id).limit(1))
        if order is None:
            raise HTTPException(status_code=404, detail="运单不存在")
        if current_user.role == UserRole.DRIVER and order.driver_id != current_user.user_id:
            raise HTTPException(status_code=403, detail="无权订阅该运单监控")
        order_id = order.order_id
    elif payload.scope == WS_TICKET_SCOPE_NOTIFICATIONS:
        order_id = None
    else:
        raise HTTPException(status_code=400, detail="不支持的 ws scope")

    ticket, expires_in = ws_ticket_service.issue(
        user_id=current_user.user_id,
        scope=payload.scope,
        order_id=order_id,
    )
    return success_response(data={"ticket": ticket, "expires_in": expires_in, "scope": payload.scope})

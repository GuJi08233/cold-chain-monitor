from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import User, UserRole, UserStatus
from .deps import get_db_session

settings = get_settings()
security_scheme = HTTPBearer(auto_error=False)


def create_access_token(user: User) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "user_id": user.user_id,
        "username": user.username,
        "role": user.role.value if isinstance(user.role, UserRole) else user.role,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.jwt_expire_minutes)).timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm="HS256")


def decode_access_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.jwt_secret_key, algorithms=["HS256"])
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token 已过期，请重新登录",
        ) from exc
    except jwt.InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token 无效",
        ) from exc


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security_scheme),
    db: Session = Depends(get_db_session),
) -> User:
    if credentials is None:
        raise HTTPException(status_code=401, detail="未提供认证令牌")

    payload = decode_access_token(credentials.credentials)
    user_id = payload.get("user_id")
    iat = payload.get("iat")

    if user_id is None:
        raise HTTPException(status_code=401, detail="Token 缺少用户信息")

    user = db.scalar(select(User).where(User.user_id == user_id).limit(1))
    if user is None:
        raise HTTPException(status_code=401, detail="用户不存在")

    if user.status == UserStatus.PENDING:
        raise HTTPException(status_code=401, detail="账户审批中，请联系管理员")
    if user.status == UserStatus.DISABLED:
        raise HTTPException(status_code=401, detail="账户已禁用")

    if user.password_changed_at is not None and iat is not None:
        changed_at_ts = int(
            user.password_changed_at.replace(tzinfo=timezone.utc).timestamp()
        )
        if iat < changed_at_ts:
            raise HTTPException(status_code=401, detail="密码已更新，请重新登录")

    return user


def require_role(*allowed_roles: UserRole):
    allowed = {role.value if isinstance(role, UserRole) else str(role) for role in allowed_roles}

    def dependency(current_user: User = Depends(get_current_user)) -> User:
        current_role = (
            current_user.role.value
            if isinstance(current_user.role, UserRole)
            else str(current_user.role)
        )
        if current_role not in allowed:
            raise HTTPException(status_code=403, detail="权限不足")
        return current_user

    return dependency


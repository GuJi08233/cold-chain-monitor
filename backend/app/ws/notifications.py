import asyncio
from collections import defaultdict

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from ..database import SessionLocal
from ..models import User, UserStatus
from ..services.ws_ticket_service import WS_TICKET_SCOPE_NOTIFICATIONS, ws_ticket_service

router = APIRouter()


class NotificationConnectionManager:
    def __init__(self) -> None:
        self._connections: dict[int, set[WebSocket]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def connect(self, user_id: int, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections[user_id].add(websocket)

    async def disconnect(self, user_id: int, websocket: WebSocket) -> None:
        async with self._lock:
            sockets = self._connections.get(user_id)
            if not sockets:
                return
            sockets.discard(websocket)
            if not sockets:
                self._connections.pop(user_id, None)

    async def send_to_user(self, user_id: int, payload: dict) -> None:
        async with self._lock:
            targets = list(self._connections.get(user_id, []))
        for ws in targets:
            try:
                await ws.send_json(payload)
            except Exception:  # noqa: BLE001
                await self.disconnect(user_id, ws)


notification_connection_manager = NotificationConnectionManager()


def _auth_user(ticket: str) -> tuple[bool, int, int]:
    user_id = ws_ticket_service.consume(ticket=ticket, scope=WS_TICKET_SCOPE_NOTIFICATIONS)
    if user_id is None:
        return False, 0, 4001
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.user_id == user_id).limit(1))
        if user is None:
            return False, 0, 4001
        if user.status in (UserStatus.PENDING, UserStatus.DISABLED):
            return False, 0, 4001
    return True, int(user_id), 1000


@router.websocket("/ws/notifications")
async def notifications_ws(websocket: WebSocket):
    ticket = websocket.query_params.get("ticket", "")
    if not ticket:
        await websocket.close(code=4001, reason="缺少 ws ticket")
        return

    ok, user_id, close_code = _auth_user(ticket)
    if not ok:
        await websocket.close(code=close_code, reason="鉴权失败")
        return

    await notification_connection_manager.connect(user_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        await notification_connection_manager.disconnect(user_id, websocket)

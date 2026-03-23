import asyncio
from collections import defaultdict

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from ..database import SessionLocal
from ..models import Order, User, UserRole, UserStatus
from ..services.ws_ticket_service import WS_TICKET_SCOPE_MONITOR, ws_ticket_service

router = APIRouter()


class MonitorConnectionManager:
    def __init__(self) -> None:
        self._connections: dict[str, set[WebSocket]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def connect(self, order_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections[order_id].add(websocket)

    async def disconnect(self, order_id: str, websocket: WebSocket) -> None:
        async with self._lock:
            sockets = self._connections.get(order_id)
            if not sockets:
                return
            sockets.discard(websocket)
            if not sockets:
                self._connections.pop(order_id, None)

    async def broadcast(self, order_id: str, payload: dict) -> None:
        async with self._lock:
            targets = list(self._connections.get(order_id, []))

        for ws in targets:
            try:
                await ws.send_json(payload)
            except Exception:  # noqa: BLE001
                await self.disconnect(order_id, ws)


monitor_connection_manager = MonitorConnectionManager()


def _auth_user_for_order(ticket: str, order_id: str) -> tuple[bool, int]:
    user_id = ws_ticket_service.consume(
        ticket=ticket,
        scope=WS_TICKET_SCOPE_MONITOR,
        order_id=order_id,
    )
    if user_id is None:
        return False, 4001

    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.user_id == user_id).limit(1))
        if user is None:
            return False, 4001
        if user.status in (UserStatus.PENDING, UserStatus.DISABLED):
            return False, 4001

        order = db.scalar(select(Order).where(Order.order_id == order_id).limit(1))
        if order is None:
            return False, 4004

        if user.role == UserRole.DRIVER and order.driver_id != user.user_id:
            return False, 4003

    return True, 1000


@router.websocket("/ws/monitor/{order_id}")
async def monitor_ws(websocket: WebSocket, order_id: str):
    ticket = websocket.query_params.get("ticket", "")
    if not ticket:
        await websocket.close(code=4001, reason="缺少 ws ticket")
        return

    ok, close_code = _auth_user_for_order(ticket, order_id)
    if not ok:
        await websocket.close(code=close_code, reason="鉴权失败")
        return

    await monitor_connection_manager.connect(order_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        await monitor_connection_manager.disconnect(order_id, websocket)

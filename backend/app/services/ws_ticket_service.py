from dataclasses import dataclass
from datetime import datetime, timedelta
from threading import Lock
from uuid import uuid4

WS_TICKET_SCOPE_NOTIFICATIONS = "notifications"
WS_TICKET_SCOPE_MONITOR = "monitor"
WS_TICKET_SCOPES = {WS_TICKET_SCOPE_NOTIFICATIONS, WS_TICKET_SCOPE_MONITOR}


@dataclass
class WsTicket:
    user_id: int
    scope: str
    order_id: str | None
    expires_at: datetime


class WsTicketService:
    TTL_SECONDS = 60

    def __init__(self) -> None:
        self._lock = Lock()
        self._tickets: dict[str, WsTicket] = {}

    def issue(self, *, user_id: int, scope: str, order_id: str | None = None) -> tuple[str, int]:
        if scope not in WS_TICKET_SCOPES:
            raise ValueError("不支持的 WS 票据 scope")
        now = datetime.now()
        expire_at = now + timedelta(seconds=self.TTL_SECONDS)
        ticket = uuid4().hex
        with self._lock:
            self._cleanup_expired(now)
            self._tickets[ticket] = WsTicket(
                user_id=user_id,
                scope=scope,
                order_id=order_id,
                expires_at=expire_at,
            )
        return ticket, self.TTL_SECONDS

    def consume(
        self,
        *,
        ticket: str,
        scope: str,
        order_id: str | None = None,
    ) -> int | None:
        now = datetime.now()
        with self._lock:
            self._cleanup_expired(now)
            row = self._tickets.pop(ticket, None)
        if row is None:
            return None
        if row.expires_at <= now:
            return None
        if row.scope != scope:
            return None
        if scope == WS_TICKET_SCOPE_MONITOR and row.order_id != order_id:
            return None
        return row.user_id

    def _cleanup_expired(self, now: datetime) -> None:
        expired = [key for key, row in self._tickets.items() if row.expires_at <= now]
        for key in expired:
            self._tickets.pop(key, None)


ws_ticket_service = WsTicketService()


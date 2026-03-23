from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from threading import Lock

from fastapi import HTTPException


class LoginSecurityService:
    WINDOW_SECONDS = 60
    MAX_USERNAME_ATTEMPTS = 5
    MAX_IP_ATTEMPTS = 10
    MAX_FAILED_BEFORE_LOCK = 5
    LOCK_MINUTES = 15

    def __init__(self) -> None:
        self._username_attempts: dict[str, deque[datetime]] = defaultdict(deque)
        self._ip_attempts: dict[str, deque[datetime]] = defaultdict(deque)
        self._username_failed_count: dict[str, int] = defaultdict(int)
        self._username_locked_until: dict[str, datetime] = {}
        self._lock = Lock()

    def check_request_allowed(self, username: str, ip: str) -> None:
        with self._lock:
            now = datetime.now(timezone.utc)
            self._cleanup_stale(now, username, ip)
            self._check_locked(username, now)

            username_attempts = self._username_attempts[username]
            if len(username_attempts) >= self.MAX_USERNAME_ATTEMPTS:
                raise HTTPException(status_code=429, detail="登录尝试过于频繁，请稍后再试")

            ip_attempts = self._ip_attempts[ip]
            if len(ip_attempts) >= self.MAX_IP_ATTEMPTS:
                raise HTTPException(status_code=429, detail="登录尝试过于频繁，请稍后再试")

            username_attempts.append(now)
            ip_attempts.append(now)

    def record_failure(self, username: str) -> None:
        with self._lock:
            now = datetime.now(timezone.utc)
            self._username_failed_count[username] += 1
            failed_count = self._username_failed_count[username]
            if failed_count < self.MAX_FAILED_BEFORE_LOCK:
                return

            self._username_locked_until[username] = now + timedelta(minutes=self.LOCK_MINUTES)
            self._username_failed_count[username] = 0

    def record_success(self, username: str) -> None:
        with self._lock:
            self._username_failed_count.pop(username, None)
            self._username_locked_until.pop(username, None)

    def _check_locked(self, username: str, now: datetime) -> None:
        locked_until = self._username_locked_until.get(username)
        if locked_until is None:
            return
        if locked_until <= now:
            self._username_locked_until.pop(username, None)
            return
        raise HTTPException(status_code=429, detail="账户已临时锁定，请 15 分钟后再试")

    def _cleanup_stale(self, now: datetime, username: str, ip: str) -> None:
        threshold = now - timedelta(seconds=self.WINDOW_SECONDS)
        self._cleanup_deque(self._username_attempts[username], threshold)
        self._cleanup_deque(self._ip_attempts[ip], threshold)

    @staticmethod
    def _cleanup_deque(items: deque[datetime], threshold: datetime) -> None:
        while items and items[0] < threshold:
            items.popleft()


login_security_service = LoginSecurityService()


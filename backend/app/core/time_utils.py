from datetime import datetime
from threading import RLock
from time import monotonic
from zoneinfo import ZoneInfoNotFoundError

from ..config import get_settings, resolve_app_timezone

_APP_TIMEZONE_CACHE_TTL_SECONDS = 5.0
_app_timezone_cache: tuple[float, object] | None = None
_app_timezone_lock = RLock()


def clear_app_timezone_cache() -> None:
    global _app_timezone_cache
    with _app_timezone_lock:
        _app_timezone_cache = None


def get_app_timezone_name() -> str:
    from ..services.system_config_service import system_config_service

    settings = get_settings()
    return (
        system_config_service.get_text("app_timezone", default=settings.app_timezone)
        or settings.app_timezone
    )


def get_app_timezone():
    global _app_timezone_cache
    now = monotonic()
    with _app_timezone_lock:
        if _app_timezone_cache is not None and _app_timezone_cache[0] > now:
            return _app_timezone_cache[1]

    settings = get_settings()
    timezone_name = get_app_timezone_name()
    try:
        tzinfo = resolve_app_timezone(timezone_name)
    except ZoneInfoNotFoundError:
        tzinfo = settings.app_tzinfo

    with _app_timezone_lock:
        _app_timezone_cache = (now + _APP_TIMEZONE_CACHE_TTL_SECONDS, tzinfo)
    return tzinfo


def app_now() -> datetime:
    return datetime.now(get_app_timezone()).replace(tzinfo=None)


def normalize_app_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(get_app_timezone()).replace(tzinfo=None)


def parse_app_datetime(value: str | None, *, fallback_to_now: bool = False) -> datetime | None:
    if value is None:
        return app_now() if fallback_to_now else None
    text = str(value).strip()
    if not text:
        return app_now() if fallback_to_now else None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return app_now() if fallback_to_now else None
    return normalize_app_datetime(parsed)


def format_app_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    return normalize_app_datetime(value).isoformat(sep=" ", timespec="seconds")


def to_unix_seconds(value: datetime) -> int:
    normalized = normalize_app_datetime(value)
    aware = normalized.replace(tzinfo=get_app_timezone())
    return int(aware.timestamp())


def from_unix_seconds(value: int | float) -> datetime:
    return datetime.fromtimestamp(value, tz=get_app_timezone()).replace(tzinfo=None)

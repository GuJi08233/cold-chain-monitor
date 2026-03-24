from datetime import datetime
from functools import lru_cache

from ..config import get_settings


@lru_cache
def get_app_timezone():
    return get_settings().app_tzinfo


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

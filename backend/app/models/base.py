from datetime import datetime

from sqlalchemy.orm import declarative_base

from ..core.time_utils import app_now

Base = declarative_base()


def utc_now() -> datetime:
    # 历史模型默认值沿用 utc_now 名称，但实际统一为应用配置时区的本地时间。
    return app_now()

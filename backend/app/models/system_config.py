from sqlalchemy import Column, DateTime, String, Text

from .base import Base, utc_now


class SystemConfig(Base):
    __tablename__ = "system_config"

    key = Column(String(64), primary_key=True)
    value = Column(Text, nullable=False)
    updated_at = Column(DateTime, nullable=False, default=utc_now, onupdate=utc_now)


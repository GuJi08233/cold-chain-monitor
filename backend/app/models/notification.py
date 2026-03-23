from enum import Enum

from sqlalchemy import Boolean, Column, DateTime, Enum as SQLEnum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from .base import Base, utc_now


class NotificationType(str, Enum):
    ANOMALY_START = "anomaly_start"
    ANOMALY_END = "anomaly_end"
    TICKET_RESULT = "ticket_result"
    ORDER_ASSIGNED = "order_assigned"
    NEW_TICKET = "new_ticket"
    DRIVER_PENDING = "driver_pending"


class Notification(Base):
    __tablename__ = "notifications"

    notification_id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.user_id"), nullable=False, index=True)
    type = Column(
        SQLEnum(NotificationType, name="notification_type", native_enum=False),
        nullable=False,
        index=True,
    )
    title = Column(String(255), nullable=False)
    content = Column(Text, nullable=False)
    is_read = Column(Boolean, nullable=False, default=False, index=True)
    created_at = Column(DateTime, nullable=False, default=utc_now)

    user = relationship("User", back_populates="notifications")


from enum import Enum

from sqlalchemy import Column, DateTime, Enum as SQLEnum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from .base import Base, utc_now


class TicketType(str, Enum):
    CANCEL_ORDER = "cancel_order"
    ANOMALY_REPORT = "anomaly_report"
    INFO_CHANGE = "info_change"


class TicketStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class Ticket(Base):
    __tablename__ = "tickets"

    ticket_id = Column(Integer, primary_key=True, autoincrement=True)
    type = Column(
        SQLEnum(TicketType, name="ticket_type", native_enum=False),
        nullable=False,
        index=True,
    )
    submitter_id = Column(Integer, ForeignKey("users.user_id"), nullable=False, index=True)
    order_id = Column(String(64), ForeignKey("orders.order_id"), nullable=True, index=True)
    reason = Column(Text, nullable=False)
    status = Column(
        SQLEnum(TicketStatus, name="ticket_status", native_enum=False),
        nullable=False,
        default=TicketStatus.PENDING,
        index=True,
    )
    reviewer_id = Column(Integer, ForeignKey("users.user_id"), nullable=True, index=True)
    review_comment = Column(Text, nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utc_now)

    submitter = relationship("User", back_populates="submitted_tickets", foreign_keys=[submitter_id])
    reviewer = relationship("User", back_populates="reviewed_tickets", foreign_keys=[reviewer_id])
    order = relationship("Order", back_populates="tickets")


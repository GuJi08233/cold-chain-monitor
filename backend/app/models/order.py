from enum import Enum

from sqlalchemy import (
    Column,
    DateTime,
    Enum as SQLEnum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from .base import Base, utc_now


class OrderStatus(str, Enum):
    PENDING = "pending"
    IN_TRANSIT = "in_transit"
    COMPLETED = "completed"
    ABNORMAL_CLOSED = "abnormal_closed"
    CANCELLED = "cancelled"


class AlertMetric(str, Enum):
    TEMPERATURE = "temperature"
    HUMIDITY = "humidity"
    PRESSURE = "pressure"


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        Index("ix_orders_status_planned_start", "status", "planned_start"),
        Index("ix_orders_device_status", "device_id", "status"),
        Index("ix_orders_driver_status", "driver_id", "status"),
    )

    order_id = Column(String(64), primary_key=True)
    device_id = Column(String(64), ForeignKey("devices.device_id"), nullable=False, index=True)
    driver_id = Column(Integer, ForeignKey("users.user_id"), nullable=False, index=True)
    cargo_name = Column(String(128), nullable=False)
    cargo_info = Column(Text, nullable=True)
    origin = Column(String(255), nullable=False)
    destination = Column(String(255), nullable=False)
    planned_start = Column(DateTime, nullable=False)
    actual_start = Column(DateTime, nullable=True)
    actual_end = Column(DateTime, nullable=True)
    status = Column(
        SQLEnum(OrderStatus, name="order_status", native_enum=False),
        nullable=False,
        default=OrderStatus.PENDING,
        index=True,
    )
    data_hash = Column(String(128), nullable=True)
    created_by = Column(Integer, ForeignKey("users.user_id"), nullable=False, index=True)
    created_at = Column(DateTime, nullable=False, default=utc_now)

    device = relationship("Device", back_populates="orders")
    driver = relationship("User", back_populates="driver_orders", foreign_keys=[driver_id])
    creator = relationship("User", back_populates="created_orders", foreign_keys=[created_by])
    alert_rules = relationship("AlertRule", back_populates="order", cascade="all, delete-orphan")
    anomalies = relationship("Anomaly", back_populates="order")
    tickets = relationship("Ticket", back_populates="order")
    chain_records = relationship("ChainRecord", back_populates="order")


class AlertRule(Base):
    __tablename__ = "alert_rules"

    rule_id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(String(64), ForeignKey("orders.order_id"), nullable=False, index=True)
    metric = Column(
        SQLEnum(AlertMetric, name="alert_metric", native_enum=False),
        nullable=False,
    )
    min_value = Column(Float, nullable=True)
    max_value = Column(Float, nullable=True)

    order = relationship("Order", back_populates="alert_rules")
    anomalies = relationship("Anomaly", back_populates="rule")

from enum import Enum

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum as SQLEnum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
)
from sqlalchemy.orm import relationship

from .base import Base, utc_now


class AnomalyMetric(str, Enum):
    TEMPERATURE = "temperature"
    HUMIDITY = "humidity"
    PRESSURE = "pressure"
    DEVICE_OFFLINE = "device_offline"


class AnomalyStatus(str, Enum):
    ONGOING = "ongoing"
    RESOLVED = "resolved"


class Anomaly(Base):
    __tablename__ = "anomalies"
    __table_args__ = (
        Index("ix_anomalies_status_order", "status", "order_id"),
        Index("ix_anomalies_device_status", "device_id", "status"),
    )

    anomaly_id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(String(64), ForeignKey("orders.order_id"), nullable=False, index=True)
    device_id = Column(String(64), ForeignKey("devices.device_id"), nullable=False, index=True)
    rule_id = Column(Integer, ForeignKey("alert_rules.rule_id"), nullable=True, index=True)
    metric = Column(
        SQLEnum(AnomalyMetric, name="anomaly_metric", native_enum=False),
        nullable=False,
        index=True,
    )
    trigger_value = Column(Float, nullable=False)
    threshold_min = Column(Float, nullable=True)
    threshold_max = Column(Float, nullable=True)
    start_time = Column(DateTime, nullable=False, default=utc_now)
    end_time = Column(DateTime, nullable=True)
    status = Column(
        SQLEnum(AnomalyStatus, name="anomaly_status", native_enum=False),
        nullable=False,
        default=AnomalyStatus.ONGOING,
        index=True,
    )
    peak_value = Column(Float, nullable=True)
    is_reported = Column(Boolean, nullable=False, default=False)

    order = relationship("Order", back_populates="anomalies")
    device = relationship("Device", back_populates="anomalies")
    rule = relationship("AlertRule", back_populates="anomalies")
    chain_records = relationship("ChainRecord", back_populates="anomaly")

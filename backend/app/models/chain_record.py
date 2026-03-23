from enum import Enum

from sqlalchemy import Column, DateTime, Enum as SQLEnum, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import relationship

from .base import Base, utc_now


class ChainRecordType(str, Enum):
    ORDER_HASH = "order_hash"
    ANOMALY_START = "anomaly_start"
    ANOMALY_END = "anomaly_end"


class ChainRecordStatus(str, Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    FAILED = "failed"


class ChainRecord(Base):
    __tablename__ = "chain_records"
    __table_args__ = (
        Index("ix_chain_records_status_type", "status", "type"),
        Index("ix_chain_records_order_type_status", "order_id", "type", "status"),
        Index("ix_chain_records_anomaly_type_status", "anomaly_id", "type", "status"),
    )

    record_id = Column(Integer, primary_key=True, autoincrement=True)
    type = Column(
        SQLEnum(ChainRecordType, name="chain_record_type", native_enum=False),
        nullable=False,
        index=True,
    )
    order_id = Column(String(64), ForeignKey("orders.order_id"), nullable=False, index=True)
    anomaly_id = Column(Integer, ForeignKey("anomalies.anomaly_id"), nullable=True, index=True)
    payload = Column(Text, nullable=False)
    data_hash = Column(String(128), nullable=False)
    tx_hash = Column(String(128), nullable=True, index=True)
    block_number = Column(Integer, nullable=True)
    status = Column(
        SQLEnum(ChainRecordStatus, name="chain_record_status", native_enum=False),
        nullable=False,
        default=ChainRecordStatus.PENDING,
        index=True,
    )
    created_at = Column(DateTime, nullable=False, default=utc_now)

    order = relationship("Order", back_populates="chain_records")
    anomaly = relationship("Anomaly", back_populates="chain_records")

from enum import Enum

from sqlalchemy import Column, DateTime, Enum as SQLEnum, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from .base import Base, utc_now


class DeviceStatus(str, Enum):
    ONLINE = "online"
    OFFLINE = "offline"
    UNBOUND = "unbound"


class Device(Base):
    __tablename__ = "devices"

    device_id = Column(String(64), primary_key=True)
    name = Column(String(128), nullable=False)
    driver_id = Column(Integer, ForeignKey("users.user_id"), nullable=True, index=True)
    status = Column(
        SQLEnum(DeviceStatus, name="device_status", native_enum=False),
        nullable=False,
        default=DeviceStatus.UNBOUND,
        index=True,
    )
    last_seen = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utc_now)

    driver = relationship("User", back_populates="bound_devices", foreign_keys=[driver_id])
    orders = relationship("Order", back_populates="device")
    anomalies = relationship("Anomaly", back_populates="device")


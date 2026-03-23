from enum import Enum

from sqlalchemy import Column, DateTime, Enum as SQLEnum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from .base import Base, utc_now


class UserRole(str, Enum):
    SUPER_ADMIN = "super_admin"
    ADMIN = "admin"
    DRIVER = "driver"


class UserStatus(str, Enum):
    ACTIVE = "active"
    PENDING = "pending"
    DISABLED = "disabled"


class User(Base):
    __tablename__ = "users"

    user_id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(64), nullable=False, unique=True, index=True)
    password_hash = Column(Text, nullable=False)
    role = Column(
        SQLEnum(UserRole, name="user_role", native_enum=False),
        nullable=False,
        default=UserRole.DRIVER,
        index=True,
    )
    display_name = Column(String(100), nullable=True)
    status = Column(
        SQLEnum(UserStatus, name="user_status", native_enum=False),
        nullable=False,
        default=UserStatus.PENDING,
        index=True,
    )
    password_changed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utc_now)

    driver_profile = relationship(
        "DriverProfile",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
    )
    created_orders = relationship(
        "Order",
        back_populates="creator",
        foreign_keys="Order.created_by",
    )
    driver_orders = relationship(
        "Order",
        back_populates="driver",
        foreign_keys="Order.driver_id",
    )
    bound_devices = relationship(
        "Device",
        back_populates="driver",
        foreign_keys="Device.driver_id",
    )
    notifications = relationship("Notification", back_populates="user")
    submitted_tickets = relationship(
        "Ticket",
        back_populates="submitter",
        foreign_keys="Ticket.submitter_id",
    )
    reviewed_tickets = relationship(
        "Ticket",
        back_populates="reviewer",
        foreign_keys="Ticket.reviewer_id",
    )


class DriverProfile(Base):
    __tablename__ = "driver_profiles"

    driver_id = Column(Integer, ForeignKey("users.user_id"), primary_key=True)
    real_name = Column(String(64), nullable=False)
    id_card = Column(String(32), nullable=False, unique=True, index=True)
    phone = Column(String(32), nullable=False)
    plate_number = Column(String(32), nullable=False)
    vehicle_type = Column(String(64), nullable=False)

    user = relationship("User", back_populates="driver_profile")

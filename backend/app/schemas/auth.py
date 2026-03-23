from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class LoginRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=8, max_length=128)
    real_name: str = Field(min_length=1, max_length=64)
    id_card: str = Field(min_length=6, max_length=32)
    phone: str = Field(min_length=5, max_length=32)
    plate_number: str = Field(min_length=3, max_length=32)
    vehicle_type: str = Field(min_length=2, max_length=64)


class ChangePasswordRequest(BaseModel):
    old_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class WsTicketRequest(BaseModel):
    scope: Literal["notifications", "monitor"]
    order_id: str | None = Field(default=None, min_length=1, max_length=64)


class DriverProfileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    real_name: str
    id_card: str
    phone: str
    plate_number: str
    vehicle_type: str


class CurrentUserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: int
    username: str
    role: str
    display_name: str | None = None
    status: str
    created_at: str
    driver_profile: DriverProfileOut | None = None

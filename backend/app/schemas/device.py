from pydantic import BaseModel, Field

from ..models import DeviceStatus


class DeviceCreateRequest(BaseModel):
    device_id: str = Field(min_length=3, max_length=64)
    name: str = Field(min_length=1, max_length=128)


class DeviceBindRequest(BaseModel):
    driver_id: int | None = Field(default=None, ge=1)


class DeviceListQuery(BaseModel):
    status: DeviceStatus | None = None
    driver_id: int | None = Field(default=None, ge=1)


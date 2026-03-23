from pydantic import BaseModel, Field


class AdminCreateRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=8, max_length=128)
    display_name: str | None = Field(default=None, min_length=1, max_length=100)


class UserApproveRequest(BaseModel):
    device_id: str = Field(min_length=3, max_length=64)

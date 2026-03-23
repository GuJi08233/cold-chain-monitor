from pydantic import BaseModel, Field, model_validator

from ..models import TicketType


class TicketCreateRequest(BaseModel):
    type: TicketType
    order_id: str | None = Field(default=None, min_length=1, max_length=64)
    reason: str = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def validate_order_id(self):
        if self.type in (TicketType.CANCEL_ORDER, TicketType.ANOMALY_REPORT) and not self.order_id:
            raise ValueError("该工单类型必须提供 order_id")
        return self


class TicketReviewRequest(BaseModel):
    comment: str = Field(min_length=1, max_length=1000)

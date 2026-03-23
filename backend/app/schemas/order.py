from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, model_validator

from ..models import AlertMetric


class AlertRuleCreateItem(BaseModel):
    metric: AlertMetric
    min_value: float | None = None
    max_value: float | None = None

    @model_validator(mode="after")
    def validate_threshold(self):
        if self.min_value is None and self.max_value is None:
            raise ValueError("告警规则至少需要设置 min_value 或 max_value")
        if (
            self.min_value is not None
            and self.max_value is not None
            and self.min_value > self.max_value
        ):
            raise ValueError("min_value 不能大于 max_value")
        return self


class OrderCreateRequest(BaseModel):
    device_id: str = Field(min_length=3, max_length=64)
    driver_id: int = Field(ge=1)
    cargo_name: str = Field(min_length=1, max_length=128)
    cargo_info: dict[str, Any] | None = None
    origin: str = Field(min_length=1, max_length=255)
    destination: str = Field(min_length=1, max_length=255)
    planned_start: datetime
    alert_rules: list[AlertRuleCreateItem] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_rules(self):
        if len(self.alert_rules) > 3:
            raise ValueError("alert_rules 最多允许 3 条")

        seen_metrics: set[AlertMetric] = set()
        for rule in self.alert_rules:
            if rule.metric in seen_metrics:
                raise ValueError(f"告警指标重复: {rule.metric.value}")
            seen_metrics.add(rule.metric)
        return self


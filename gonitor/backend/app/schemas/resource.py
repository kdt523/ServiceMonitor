from datetime import datetime
from typing import Optional, Literal
from pydantic import BaseModel, field_validator


class ResourceCreate(BaseModel):
    name: str
    url: str
    resource_type: Literal["http", "tcp"]
    interval_minutes: int = 5

    @field_validator("interval_minutes")
    @classmethod
    def validate_interval(cls, v: int) -> int:
        if v < 1:
            raise ValueError("interval_minutes must be >= 1")
        return v


class ResourceUpdate(BaseModel):
    name: Optional[str] = None
    url: Optional[str] = None
    interval_minutes: Optional[int] = None
    is_active: Optional[bool] = None

    @field_validator("interval_minutes")
    @classmethod
    def validate_interval(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and v < 1:
            raise ValueError("interval_minutes must be >= 1")
        return v


class ResourceRead(BaseModel):
    id: int
    user_id: int
    name: str
    url: str
    resource_type: str
    interval_minutes: int
    status: str
    last_checked_at: Optional[datetime] = None
    response_time_ms: Optional[int] = None
    created_at: datetime
    is_active: bool

    model_config = {"from_attributes": True}

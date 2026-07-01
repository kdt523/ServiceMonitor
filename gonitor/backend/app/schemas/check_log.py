from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class CheckLogRead(BaseModel):
    id: int
    resource_id: int
    status: str
    response_time_ms: Optional[int] = None
    error_message: Optional[str] = None
    checked_at: datetime

    model_config = {"from_attributes": True}

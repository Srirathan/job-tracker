from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.application import ApplicationStatus


class ApplicationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: int
    user_id: int
    gmail_message_id: Optional[str] = None
    date: datetime = Field(validation_alias="email_date")
    company: str
    role: str
    status: ApplicationStatus
    created_at: datetime
    updated_at: datetime

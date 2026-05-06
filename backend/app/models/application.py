from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, Enum as SqlEnum, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.user import User


class ApplicationStatus(str, Enum):
    APPLIED = "Applied"
    REJECTED = "Rejected"
    INTERVIEW = "Interview"
    OA = "OA"
    OFFER = "Offer"


class Application(Base):
    __tablename__ = "applications"
    __table_args__ = (UniqueConstraint("user_id", "gmail_message_id", name="uq_applications_user_gmail_message"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    gmail_message_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    email_date: Mapped[datetime] = mapped_column("date", DateTime(timezone=True), nullable=False)
    company: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    status: Mapped[ApplicationStatus] = mapped_column(
        SqlEnum(ApplicationStatus, native_enum=False, length=32),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    user: Mapped["User"] = relationship("User", back_populates="applications")

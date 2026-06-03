import uuid
import secrets
from datetime import datetime

from sqlalchemy import String, Integer, DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def generate_referral_code() -> str:
    return secrets.token_hex(4)


class WaitlistEntry(Base):
    __tablename__ = "waitlist_entries"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False, index=True
    )
    trading_experience: Mapped[str] = mapped_column(String(50), nullable=False)
    primary_interest: Mapped[str] = mapped_column(String(50), nullable=False)
    queue_position: Mapped[int | None] = mapped_column(Integer, nullable=True)
    referral_code: Mapped[str] = mapped_column(
        String(8), unique=True, nullable=False, index=True, default=generate_referral_code
    )
    referred_by: Mapped[str | None] = mapped_column(String(8), nullable=True)
    referral_signups_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

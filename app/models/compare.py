import uuid
from datetime import datetime

from sqlalchemy import String, DateTime, JSON, BigInteger
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.database import Base


class StockCompareCache(Base):
    __tablename__ = "stock_compare_cache"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    comparison_slug: Mapped[str] = mapped_column(String(200), unique=True, nullable=False, index=True)
    stock1_slug: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    stock2_slug: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    request_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    response_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    response_status: Mapped[str] = mapped_column(String(20), nullable=False, default="success")
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


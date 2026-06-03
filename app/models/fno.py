import uuid
from datetime import datetime

from sqlalchemy import String, Float, BigInteger, Boolean, DateTime, ForeignKey, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.database import Base


class FnoSymbol(Base):
    __tablename__ = "fno_symbols"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    symbol: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    segment: Mapped[str] = mapped_column(String(20), nullable=False)
    exchange: Mapped[str] = mapped_column(String(10), nullable=False)
    asset_type: Mapped[str] = mapped_column(String(20), nullable=False)
    underlying_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    lot_size: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    tick_size: Mapped[float] = mapped_column(Float, nullable=False, default=0.05)
    freeze_quantity: Mapped[float | None] = mapped_column(Float, nullable=True)
    minimum_lot: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    qty_multiplier: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    weekly: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    expiries = relationship("FnoExpiry", back_populates="symbol", cascade="all, delete-orphan")
    instruments = relationship("FnoInstrument", back_populates="symbol", cascade="all, delete-orphan")


class FnoExpiry(Base):
    __tablename__ = "fno_expiries"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    symbol_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fno_symbols.id", ondelete="CASCADE"), nullable=False, index=True
    )
    expiry_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    expiry_timestamp: Mapped[int] = mapped_column(BigInteger, nullable=False)
    weekly: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    symbol = relationship("FnoSymbol", back_populates="expiries")
    instruments = relationship("FnoInstrument", back_populates="expiry", cascade="all, delete-orphan")


class FnoInstrument(Base):
    __tablename__ = "fno_instruments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    symbol_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fno_symbols.id", ondelete="CASCADE"), nullable=False, index=True
    )
    expiry_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fno_expiries.id", ondelete="CASCADE"), nullable=False, index=True
    )
    instrument_key: Mapped[str] = mapped_column(
        String(100), unique=True, nullable=False, index=True
    )
    exchange_token: Mapped[str] = mapped_column(String(50), nullable=False)
    trading_symbol: Mapped[str] = mapped_column(String(100), nullable=False)
    instrument_type: Mapped[str] = mapped_column(String(10), nullable=False)
    strike_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    lot_size: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    tick_size: Mapped[float] = mapped_column(Float, nullable=False, default=0.05)
    freeze_quantity: Mapped[float | None] = mapped_column(Float, nullable=True)
    minimum_lot: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    qty_multiplier: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    asset_type: Mapped[str] = mapped_column(String(20), nullable=False)
    underlying_type: Mapped[str] = mapped_column(String(20), nullable=False)
    underlying_symbol: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    asset_symbol: Mapped[str] = mapped_column(String(50), nullable=False)
    underlying_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    asset_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    segment: Mapped[str] = mapped_column(String(20), nullable=False)
    exchange: Mapped[str] = mapped_column(String(10), nullable=False)
    weekly: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    symbol = relationship("FnoSymbol", back_populates="instruments")
    expiry = relationship("FnoExpiry", back_populates="instruments")

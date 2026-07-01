from datetime import datetime
from sqlalchemy import String, Float, DateTime, Text, Integer
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from app.database import Base


class StockInfo(Base):
    __tablename__ = "stock_info"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    symbol: Mapped[str | None] = mapped_column(String(50), nullable=True)
    company_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    sector: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    industry: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    market_cap: Mapped[float | None] = mapped_column(Float, nullable=True)
    trailing_pe: Mapped[float | None] = mapped_column(Float, nullable=True)
    forward_pe: Mapped[float | None] = mapped_column(Float, nullable=True)
    price_to_book: Mapped[float | None] = mapped_column(Float, nullable=True)
    dividend_yield: Mapped[float | None] = mapped_column(Float, nullable=True)
    roe: Mapped[float | None] = mapped_column(Float, nullable=True)
    roa: Mapped[float | None] = mapped_column(Float, nullable=True)
    profit_margins: Mapped[float | None] = mapped_column(Float, nullable=True)
    revenue_growth: Mapped[float | None] = mapped_column(Float, nullable=True)
    earnings_growth: Mapped[float | None] = mapped_column(Float, nullable=True)
    eps: Mapped[float | None] = mapped_column(Float, nullable=True)
    forward_eps: Mapped[float | None] = mapped_column(Float, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    fetched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

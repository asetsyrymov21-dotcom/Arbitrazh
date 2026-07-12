import enum
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.time import utc_now
from app.persistence.database import Base


class StrategyName(str, enum.Enum):
    FUNDING = "funding"
    SPREAD = "spread"


class OrderStatus(str, enum.Enum):
    FILLED = "filled"
    PARTIAL = "partial"
    REJECTED = "rejected"


class Side(str, enum.Enum):
    BUY = "buy"
    SELL = "sell"


class MarketSnapshot(Base):
    __tablename__ = "market_snapshots"
    __table_args__ = (Index("ix_market_snapshots_symbol_category_ts", "symbol", "category", "ts"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    category: Mapped[str] = mapped_column(String(16))
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    bid_price: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    bid_size: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    ask_price: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    ask_size: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    orderbook: Mapped[dict[str, Any]] = mapped_column(JSONB)
    raw: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class FundingRate(Base):
    __tablename__ = "funding_rates"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    funding_rate: Mapped[Decimal] = mapped_column(Numeric(38, 18))
    funding_rate_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    raw: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class Signal(Base):
    __tablename__ = "signals"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    strategy: Mapped[StrategyName] = mapped_column(Enum(StrategyName))
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    action: Mapped[str] = mapped_column(String(32))
    strength: Mapped[Decimal] = mapped_column(Numeric(38, 18), default=Decimal("0"))
    reason: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SimulatedOrder(Base):
    __tablename__ = "simulated_orders"
    __table_args__ = (Index("uq_simulated_order_idempotency", "idempotency_key", unique=True),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    position_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("positions.id"))
    idempotency_key: Mapped[str] = mapped_column(String(128))
    strategy: Mapped[StrategyName] = mapped_column(Enum(StrategyName))
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    market: Mapped[str] = mapped_column(String(16))
    side: Mapped[Side] = mapped_column(Enum(Side))
    requested_qty: Mapped[Decimal] = mapped_column(Numeric(38, 18))
    filled_qty: Mapped[Decimal] = mapped_column(Numeric(38, 18), default=Decimal("0"))
    avg_price: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    status: Mapped[OrderStatus] = mapped_column(Enum(OrderStatus))
    rejected_reason: Mapped[str | None] = mapped_column(Text)
    fee: Mapped[Decimal] = mapped_column(Numeric(38, 18), default=Decimal("0"))
    slippage: Mapped[Decimal] = mapped_column(Numeric(38, 18), default=Decimal("0"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    fills: Mapped[list["Fill"]] = relationship(back_populates="order")


class Fill(Base):
    __tablename__ = "fills"
    __table_args__ = (Index("uq_fill_idempotency", "idempotency_key", unique=True),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    idempotency_key: Mapped[str] = mapped_column(String(128))
    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("simulated_orders.id"))
    price: Mapped[Decimal] = mapped_column(Numeric(38, 18))
    qty: Mapped[Decimal] = mapped_column(Numeric(38, 18))
    fee: Mapped[Decimal] = mapped_column(Numeric(38, 18))
    liquidity: Mapped[str] = mapped_column(String(16), default="taker")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    order: Mapped[SimulatedOrder] = relationship(back_populates="fills")


class Position(Base):
    __tablename__ = "positions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    strategy: Mapped[StrategyName] = mapped_column(Enum(StrategyName))
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    spot_qty: Mapped[Decimal] = mapped_column(Numeric(38, 18), default=Decimal("0"))
    perp_qty: Mapped[Decimal] = mapped_column(Numeric(38, 18), default=Decimal("0"))
    entry_spot_price: Mapped[Decimal] = mapped_column(Numeric(38, 18))
    entry_perp_price: Mapped[Decimal] = mapped_column(Numeric(38, 18))
    entry_spread: Mapped[Decimal] = mapped_column(Numeric(38, 18))
    max_adverse_spread: Mapped[Decimal] = mapped_column(Numeric(38, 18), default=Decimal("0"))
    notional: Mapped[Decimal] = mapped_column(Numeric(38, 18))
    leverage: Mapped[Decimal] = mapped_column(Numeric(38, 18))
    liquidation_price: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    exit_spot_price: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    exit_perp_price: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    realized_pnl: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    total_fees: Mapped[Decimal] = mapped_column(Numeric(38, 18), default=Decimal("0"))
    is_open: Mapped[bool] = mapped_column(default=True, index=True)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class FundingPayment(Base):
    __tablename__ = "funding_payments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    position_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("positions.id"))
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    funding_rate: Mapped[Decimal] = mapped_column(Numeric(38, 18))
    notional: Mapped[Decimal] = mapped_column(Numeric(38, 18))
    amount: Mapped[Decimal] = mapped_column(Numeric(38, 18))
    paid_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class PortfolioSnapshot(Base):
    __tablename__ = "portfolio_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, default=utc_now)
    equity: Mapped[Decimal] = mapped_column(Numeric(38, 18))
    cash: Mapped[Decimal] = mapped_column(Numeric(38, 18))
    deployed_capital: Mapped[Decimal] = mapped_column(Numeric(38, 18))
    net_pnl: Mapped[Decimal] = mapped_column(Numeric(38, 18))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)


class StrategyRun(Base):
    __tablename__ = "strategy_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    strategy: Mapped[StrategyName] = mapped_column(Enum(StrategyName))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(32), default="running")
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class RiskEvent(Base):
    __tablename__ = "risk_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    severity: Mapped[str] = mapped_column(String(16), index=True)
    code: Mapped[str] = mapped_column(String(64), index=True)
    symbol: Mapped[str | None] = mapped_column(String(32), index=True)
    message: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSONB)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

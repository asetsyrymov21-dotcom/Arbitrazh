"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-07-12 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


strategy_enum = postgresql.ENUM("FUNDING", "SPREAD", name="strategyname")
side_enum = postgresql.ENUM("BUY", "SELL", name="side")
status_enum = postgresql.ENUM("FILLED", "PARTIAL", "REJECTED", name="orderstatus")


def upgrade() -> None:
    strategy_enum.create(op.get_bind(), checkfirst=True)
    side_enum.create(op.get_bind(), checkfirst=True)
    status_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "market_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("category", sa.String(16), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("bid_price", sa.Numeric(38, 18)),
        sa.Column("bid_size", sa.Numeric(38, 18)),
        sa.Column("ask_price", sa.Numeric(38, 18)),
        sa.Column("ask_size", sa.Numeric(38, 18)),
        sa.Column("orderbook", postgresql.JSONB, nullable=False),
        sa.Column("raw", postgresql.JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_market_snapshots_symbol", "market_snapshots", ["symbol"])
    op.create_index("ix_market_snapshots_ts", "market_snapshots", ["ts"])
    op.create_index(
        "ix_market_snapshots_symbol_category_ts", "market_snapshots", ["symbol", "category", "ts"]
    )

    op.create_table(
        "funding_rates",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("funding_rate", sa.Numeric(38, 18), nullable=False),
        sa.Column("funding_rate_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw", postgresql.JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_funding_rates_symbol", "funding_rates", ["symbol"])
    op.create_index("ix_funding_rates_funding_rate_timestamp", "funding_rates", ["funding_rate_timestamp"])

    op.create_table(
        "signals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("strategy", strategy_enum, nullable=False),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("strength", sa.Numeric(38, 18), nullable=False),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_signals_symbol", "signals", ["symbol"])

    op.create_table(
        "simulated_orders",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("strategy", strategy_enum, nullable=False),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("market", sa.String(16), nullable=False),
        sa.Column("side", side_enum, nullable=False),
        sa.Column("requested_qty", sa.Numeric(38, 18), nullable=False),
        sa.Column("filled_qty", sa.Numeric(38, 18), nullable=False),
        sa.Column("avg_price", sa.Numeric(38, 18)),
        sa.Column("status", status_enum, nullable=False),
        sa.Column("rejected_reason", sa.Text),
        sa.Column("fee", sa.Numeric(38, 18), nullable=False),
        sa.Column("slippage", sa.Numeric(38, 18), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_simulated_orders_symbol", "simulated_orders", ["symbol"])
    op.create_index("uq_simulated_order_idempotency", "simulated_orders", ["idempotency_key"], unique=True)

    op.create_table(
        "fills",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("simulated_orders.id"), nullable=False),
        sa.Column("price", sa.Numeric(38, 18), nullable=False),
        sa.Column("qty", sa.Numeric(38, 18), nullable=False),
        sa.Column("fee", sa.Numeric(38, 18), nullable=False),
        sa.Column("liquidity", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("uq_fill_idempotency", "fills", ["idempotency_key"], unique=True)

    op.create_table(
        "positions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("strategy", strategy_enum, nullable=False),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("spot_qty", sa.Numeric(38, 18), nullable=False),
        sa.Column("perp_qty", sa.Numeric(38, 18), nullable=False),
        sa.Column("entry_spot_price", sa.Numeric(38, 18), nullable=False),
        sa.Column("entry_perp_price", sa.Numeric(38, 18), nullable=False),
        sa.Column("entry_spread", sa.Numeric(38, 18), nullable=False),
        sa.Column("max_adverse_spread", sa.Numeric(38, 18), nullable=False),
        sa.Column("notional", sa.Numeric(38, 18), nullable=False),
        sa.Column("leverage", sa.Numeric(38, 18), nullable=False),
        sa.Column("liquidation_price", sa.Numeric(38, 18)),
        sa.Column("is_open", sa.Boolean, nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_positions_symbol", "positions", ["symbol"])
    op.create_index("ix_positions_is_open", "positions", ["is_open"])

    op.create_table(
        "funding_payments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("position_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("positions.id")),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("funding_rate", sa.Numeric(38, 18), nullable=False),
        sa.Column("notional", sa.Numeric(38, 18), nullable=False),
        sa.Column("amount", sa.Numeric(38, 18), nullable=False),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_funding_payments_symbol", "funding_payments", ["symbol"])

    op.create_table(
        "portfolio_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("equity", sa.Numeric(38, 18), nullable=False),
        sa.Column("cash", sa.Numeric(38, 18), nullable=False),
        sa.Column("deployed_capital", sa.Numeric(38, 18), nullable=False),
        sa.Column("net_pnl", sa.Numeric(38, 18), nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=False),
    )
    op.create_index("ix_portfolio_snapshots_ts", "portfolio_snapshots", ["ts"])

    op.create_table(
        "strategy_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("strategy", strategy_enum, nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=False),
    )

    op.create_table(
        "risk_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("symbol", sa.String(32)),
        sa.Column("message", sa.Text, nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_risk_events_severity", "risk_events", ["severity"])
    op.create_index("ix_risk_events_code", "risk_events", ["code"])
    op.create_index("ix_risk_events_symbol", "risk_events", ["symbol"])

    op.create_table(
        "settings",
        sa.Column("key", sa.String(128), primary_key=True),
        sa.Column("value", postgresql.JSONB, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    for table in [
        "settings",
        "risk_events",
        "strategy_runs",
        "portfolio_snapshots",
        "funding_payments",
        "positions",
        "fills",
        "simulated_orders",
        "signals",
        "funding_rates",
        "market_snapshots",
    ]:
        op.drop_table(table)
    status_enum.drop(op.get_bind(), checkfirst=True)
    side_enum.drop(op.get_bind(), checkfirst=True)
    strategy_enum.drop(op.get_bind(), checkfirst=True)


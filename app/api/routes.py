from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings import settings
from app.persistence.database import get_session
from app.persistence.models import (
    Fill,
    FundingPayment,
    MarketSnapshot,
    Position,
    RiskEvent,
    Signal,
    SimulatedOrder,
)
from app.reporting.metrics import EMPTY_METRICS

router = APIRouter()


def _decimal_to_str(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None


@router.get("/health")
async def health() -> dict[str, Any]:
    return {"status": "ok", "mode": "paper", "watchlist": settings.watchlist}


@router.get("/settings")
async def get_settings() -> dict[str, Any]:
    return {
        "virtual_capital_usdt": str(settings.virtual_capital_usdt),
        "watchlist": settings.watchlist,
        "max_active_notional_pct": str(settings.max_active_notional_pct),
        "max_total_deployed_pct": str(settings.max_total_deployed_pct),
        "default_leverage": str(settings.default_leverage),
        "max_leverage": str(settings.max_leverage),
        "paper_trading_only": True,
    }


@router.get("/market/snapshots")
async def market_snapshots(session: AsyncSession = Depends(get_session), limit: int = 100) -> list[dict[str, Any]]:
    rows = (await session.execute(select(MarketSnapshot).order_by(desc(MarketSnapshot.ts)).limit(limit))).scalars()
    return [
        {
            "symbol": row.symbol,
            "category": row.category,
            "ts": row.ts.isoformat(),
            "bid_price": _decimal_to_str(row.bid_price),
            "ask_price": _decimal_to_str(row.ask_price),
        }
        for row in rows
    ]


@router.get("/signals")
async def signals(session: AsyncSession = Depends(get_session), limit: int = 100) -> list[dict[str, Any]]:
    rows = (await session.execute(select(Signal).order_by(desc(Signal.created_at)).limit(limit))).scalars()
    return [
        {
            "strategy": row.strategy.value,
            "symbol": row.symbol,
            "action": row.action,
            "strength": str(row.strength),
            "reason": row.reason,
            "created_at": row.created_at.isoformat(),
        }
        for row in rows
    ]


@router.get("/positions")
async def positions(session: AsyncSession = Depends(get_session)) -> list[dict[str, Any]]:
    rows = (await session.execute(select(Position).order_by(desc(Position.opened_at)))).scalars()
    return [
        {
            "strategy": row.strategy.value,
            "symbol": row.symbol,
            "spot_qty": str(row.spot_qty),
            "perp_qty": str(row.perp_qty),
            "notional": str(row.notional),
            "entry_spot_price": str(row.entry_spot_price),
            "entry_perp_price": str(row.entry_perp_price),
            "exit_spot_price": _decimal_to_str(row.exit_spot_price),
            "exit_perp_price": _decimal_to_str(row.exit_perp_price),
            "realized_pnl": _decimal_to_str(row.realized_pnl),
            "total_fees": str(row.total_fees),
            "funding_income": str(
                (
                    await session.execute(
                        select(func.coalesce(func.sum(FundingPayment.amount), Decimal("0"))).where(
                            FundingPayment.position_id == row.id
                        )
                    )
                ).scalar_one()
            ),
            "is_open": row.is_open,
            "opened_at": row.opened_at.isoformat(),
            "closed_at": row.closed_at.isoformat() if row.closed_at else None,
        }
        for row in rows
    ]


@router.get("/trades")
async def trades(session: AsyncSession = Depends(get_session), limit: int = 100) -> list[dict[str, Any]]:
    rows = (await session.execute(select(SimulatedOrder).order_by(desc(SimulatedOrder.created_at)).limit(limit))).scalars()
    return [
        {
            "idempotency_key": row.idempotency_key,
            "strategy": row.strategy.value,
            "symbol": row.symbol,
            "market": row.market,
            "side": row.side.value,
            "status": row.status.value,
            "filled_qty": str(row.filled_qty),
            "avg_price": _decimal_to_str(row.avg_price),
            "fee": str(row.fee),
            "slippage": str(row.slippage),
        }
        for row in rows
    ]


@router.get("/pnl")
async def pnl(session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    realized = (
        await session.execute(
            select(func.coalesce(func.sum(Position.realized_pnl), Decimal("0"))).where(Position.is_open.is_(False))
        )
    ).scalar_one()
    fees = (await session.execute(select(func.coalesce(func.sum(Position.total_fees), Decimal("0"))))).scalar_one()
    funding_income = (
        await session.execute(select(func.coalesce(func.sum(FundingPayment.amount), Decimal("0"))))
    ).scalar_one()
    return {
        "realized_pnl": str(realized),
        "total_fees": str(fees),
        "funding_income": str(funding_income),
        "open_positions": str(
            (await session.execute(select(func.count()).select_from(Position).where(Position.is_open.is_(True)))).scalar_one()
        ),
    }


@router.get("/equity-curve")
async def equity_curve() -> list[dict[str, Any]]:
    return []


@router.get("/metrics")
async def metrics() -> dict[str, Any]:
    return {key: str(value) if isinstance(value, Decimal) else value for key, value in EMPTY_METRICS.__dict__.items()}


@router.get("/risk-events")
async def risk_events(session: AsyncSession = Depends(get_session), limit: int = 100) -> list[dict[str, Any]]:
    rows = (await session.execute(select(RiskEvent).order_by(desc(RiskEvent.created_at)).limit(limit))).scalars()
    return [
        {
            "severity": row.severity,
            "code": row.code,
            "symbol": row.symbol,
            "message": row.message,
            "created_at": row.created_at.isoformat(),
        }
        for row in rows
    ]

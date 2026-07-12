from dataclasses import dataclass
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings import Settings
from app.core.time import utc_now
from app.execution_simulator.simulator import ExecutionSimulator, SimulatedOrderResult
from app.market_data.types import OrderBook
from app.persistence.models import Fill, OrderStatus, Position, Side, SimulatedOrder, StrategyName
from app.risk.engine import RiskDecision, RiskEngine


@dataclass(frozen=True)
class PaperExecutionEvent:
    kind: str
    symbol: str
    notional: Decimal
    pnl: Decimal | None = None
    fees: Decimal | None = None


def calculate_realized_pnl(
    *,
    qty: Decimal,
    entry_spot: Decimal,
    entry_perp: Decimal,
    exit_spot: Decimal,
    exit_perp: Decimal,
    fees: Decimal,
) -> Decimal:
    """PnL for a spot-long / perpetual-short hedged paper position."""
    return (exit_spot - entry_spot) * qty + (entry_perp - exit_perp) * qty - fees


class PaperExecutionService:
    def __init__(self, settings: Settings, risk: RiskEngine) -> None:
        self.settings = settings
        self.risk = risk
        self.simulator = ExecutionSimulator(
            settings.spot_taker_fee_bps,
            settings.perp_taker_fee_bps,
            settings.slippage_bps,
        )

    async def process(
        self,
        session: AsyncSession,
        *,
        symbol: str,
        enter: bool,
        exit: bool,
        spot_book: OrderBook,
        perp_book: OrderBook,
    ) -> tuple[PaperExecutionEvent | None, RiskDecision | None]:
        position = (
            await session.execute(
                select(Position).where(Position.symbol == symbol, Position.is_open.is_(True)).limit(1)
            )
        ).scalar_one_or_none()
        if position is not None:
            if exit:
                return await self._close(session, position, spot_book, perp_book), None
            return None, None
        if not enter:
            return None, None
        return await self._open(session, symbol, spot_book, perp_book)

    async def _open(
        self, session: AsyncSession, symbol: str, spot_book: OrderBook, perp_book: OrderBook
    ) -> tuple[PaperExecutionEvent | None, RiskDecision | None]:
        if spot_book.best_ask is None or perp_book.best_bid is None:
            return None, RiskDecision(False, "missing_orderbook", "missing executable orderbook", "warning")
        max_notional = self.settings.virtual_capital_usdt * self.settings.max_active_notional_pct
        qty = min(
            max_notional / spot_book.best_ask.price,
            spot_book.best_ask.qty,
            perp_book.best_bid.qty,
        )
        notional = qty * spot_book.best_ask.price
        deployed = (
            await session.execute(
                select(func.coalesce(func.sum(Position.notional), Decimal("0"))).where(Position.is_open.is_(True))
            )
        ).scalar_one()
        symbol_exposure = (
            await session.execute(
                select(func.coalesce(func.sum(Position.notional), Decimal("0"))).where(
                    Position.is_open.is_(True), Position.symbol == symbol
                )
            )
        ).scalar_one()
        decision = self.risk.check_capital_limits(
            equity=self.settings.virtual_capital_usdt,
            deployed_capital=Decimal(deployed),
            symbol_exposure=Decimal(symbol_exposure),
            new_notional=notional,
        )
        if not decision.allowed:
            return None, decision

        request_id = uuid4().hex
        spot_order = self.simulator.open_spot_long(symbol, qty, spot_book, f"{request_id}:spot-entry")
        perp_order = self.simulator.open_perp_short("spread", symbol, qty, perp_book, f"{request_id}:perp-entry")
        if not _is_fully_hedged(spot_order, perp_order, qty):
            return None, RiskDecision(False, "paper_entry_not_fully_hedged", "entry fill was not fully hedged", "warning")
        assert spot_order.avg_price is not None and perp_order.avg_price is not None
        position = Position(
            strategy=StrategyName.SPREAD,
            symbol=symbol,
            spot_qty=qty,
            perp_qty=qty,
            entry_spot_price=spot_order.avg_price,
            entry_perp_price=perp_order.avg_price,
            entry_spread=(perp_order.avg_price - spot_order.avg_price) / spot_order.avg_price,
            max_adverse_spread=Decimal("0"),
            notional=spot_order.avg_price * qty,
            leverage=self.settings.default_leverage,
            liquidation_price=self.simulator.estimate_short_liquidation_price(
                perp_order.avg_price, self.settings.default_leverage
            ),
            total_fees=spot_order.fee + perp_order.fee,
        )
        session.add(position)
        await session.flush()
        _persist_order(session, spot_order, position.id)
        _persist_order(session, perp_order, position.id)
        return PaperExecutionEvent("opened", symbol, position.notional, fees=position.total_fees), None

    async def _close(
        self, session: AsyncSession, position: Position, spot_book: OrderBook, perp_book: OrderBook
    ) -> PaperExecutionEvent | None:
        if (
            spot_book.best_bid is None
            or perp_book.best_ask is None
            or spot_book.best_bid.qty < position.spot_qty
            or perp_book.best_ask.qty < position.perp_qty
        ):
            return None
        request_id = uuid4().hex
        spot_order = self.simulator.close_spot_long(position.symbol, position.spot_qty, spot_book, f"{request_id}:spot-exit")
        perp_order = self.simulator.close_perp_short("spread", position.symbol, position.perp_qty, perp_book, f"{request_id}:perp-exit")
        if not _is_fully_hedged(spot_order, perp_order, position.spot_qty):
            return None
        assert spot_order.avg_price is not None and perp_order.avg_price is not None
        close_fees = spot_order.fee + perp_order.fee
        position.exit_spot_price = spot_order.avg_price
        position.exit_perp_price = perp_order.avg_price
        position.total_fees += close_fees
        position.realized_pnl = calculate_realized_pnl(
            qty=position.spot_qty,
            entry_spot=position.entry_spot_price,
            entry_perp=position.entry_perp_price,
            exit_spot=spot_order.avg_price,
            exit_perp=perp_order.avg_price,
            fees=position.total_fees,
        )
        position.is_open = False
        position.closed_at = utc_now()
        _persist_order(session, spot_order, position.id)
        _persist_order(session, perp_order, position.id)
        return PaperExecutionEvent("closed", position.symbol, position.notional, position.realized_pnl, position.total_fees)


def _is_fully_hedged(left: SimulatedOrderResult, right: SimulatedOrderResult, qty: Decimal) -> bool:
    return left.status == "filled" and right.status == "filled" and left.filled_qty == right.filled_qty == qty


def _persist_order(session: AsyncSession, result: SimulatedOrderResult, position_id: object) -> None:
    order = SimulatedOrder(
        idempotency_key=result.idempotency_key,
        position_id=position_id,
        strategy=StrategyName(result.strategy),
        symbol=result.symbol,
        market=result.market,
        side=Side(result.side),
        requested_qty=result.requested_qty,
        filled_qty=result.filled_qty,
        avg_price=result.avg_price,
        status=OrderStatus(result.status),
        rejected_reason=result.rejected_reason,
        fee=result.fee,
        slippage=result.slippage,
    )
    session.add(order)
    for fill in result.fills:
        order.fills.append(
            Fill(
                idempotency_key=fill.idempotency_key,
                price=fill.price,
                qty=fill.qty,
                fee=fill.fee,
                liquidity=fill.liquidity,
            )
        )

from dataclasses import dataclass
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings import Settings
from app.core.time import utc_now
from app.execution_simulator.simulator import ExecutionSimulator, SimulatedOrderResult
from app.market_data.types import FundingPoint, OrderBook
from app.persistence.models import FundingPayment, Fill, OrderStatus, Position, Side, SimulatedOrder, StrategyName
from app.risk.engine import RiskDecision, RiskEngine


@dataclass(frozen=True)
class PaperExecutionEvent:
    kind: str
    symbol: str
    notional: Decimal
    pnl: Decimal | None = None
    fees: Decimal | None = None
    funding_income: Decimal | None = None


def calculate_realized_pnl(
    *,
    qty: Decimal,
    entry_spot: Decimal,
    entry_perp: Decimal,
    exit_spot: Decimal,
    exit_perp: Decimal,
    fees: Decimal,
    funding_income: Decimal = Decimal("0"),
) -> Decimal:
    """PnL for a spot-long / perpetual-short hedged paper position."""
    return (exit_spot - entry_spot) * qty + (entry_perp - exit_perp) * qty - fees + funding_income


def check_open_position_limit(open_positions: int, max_open_positions: int) -> RiskDecision:
    if open_positions >= max_open_positions:
        return RiskDecision(
            False,
            "max_open_positions",
            f"open position limit reached: {open_positions}/{max_open_positions}",
            "warning",
        )
    return RiskDecision(True, "ok", "open position limit ok")


def check_post_fill_profitability(
    *,
    settings: Settings,
    strategy: StrategyName,
    spot_price: Decimal,
    perp_price: Decimal,
    expected_funding: Decimal | None,
) -> RiskDecision:
    actual_spread = (perp_price - spot_price) / spot_price
    round_trip_cost = (
        settings.spot_taker_fee_bps * Decimal("2")
        + settings.perp_taker_fee_bps * Decimal("2")
        + settings.slippage_bps * Decimal("4")
    ) / Decimal("10000")
    if strategy == StrategyName.SPREAD:
        required = round_trip_cost + settings.spread_entry_threshold_bps / Decimal("10000")
        if actual_spread <= required:
            return RiskDecision(
                False,
                "post_fill_spread_below_threshold",
                f"actual entry spread {actual_spread} is not above required {required}",
                "warning",
            )
    else:
        if expected_funding is None:
            return RiskDecision(
                False, "missing_expected_funding", "funding estimate is missing", "warning"
            )
        required = round_trip_cost * settings.funding_cost_safety_factor
        projected_return = expected_funding + actual_spread
        if projected_return <= required:
            return RiskDecision(
                False,
                "post_fill_funding_below_costs",
                f"projected funding return {projected_return} is not above required {required}",
                "warning",
            )
    return RiskDecision(True, "ok", "post-fill profitability check passed")


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
        entry_strategy: StrategyName | None,
        expected_funding: Decimal | None,
        funding_signal_active: bool,
        funding_history: list[FundingPoint],
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
            await self._accrue_funding(session, position, funding_history)
            should_close = exit if position.strategy == StrategyName.SPREAD else (
                not funding_signal_active
                and await self._funding_payment_count(session, position.id) >= self.settings.funding_min_hold_periods
            )
            if should_close:
                return await self._close(session, position, spot_book, perp_book), None
            return None, None
        if entry_strategy is None:
            return None, None
        return await self._open(
            session, symbol, entry_strategy, expected_funding, spot_book, perp_book
        )

    async def _open(
        self,
        session: AsyncSession,
        symbol: str,
        strategy: StrategyName,
        expected_funding: Decimal | None,
        spot_book: OrderBook,
        perp_book: OrderBook,
    ) -> tuple[PaperExecutionEvent | None, RiskDecision | None]:
        if spot_book.best_ask is None or perp_book.best_bid is None:
            return None, RiskDecision(False, "missing_orderbook", "missing executable orderbook", "warning")
        open_positions = (
            await session.execute(
                select(func.count()).select_from(Position).where(Position.is_open.is_(True))
            )
        ).scalar_one()
        position_limit = check_open_position_limit(int(open_positions), self.settings.max_open_positions)
        if not position_limit.allowed:
            return None, position_limit
        max_notional = self.settings.virtual_capital_usdt * self.settings.max_active_notional_pct
        target_notional = min(self.settings.paper_position_notional_usdt, max_notional)
        qty = target_notional / spot_book.best_ask.price
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
        spot_order = self.simulator.open_spot_long(strategy.value, symbol, qty, spot_book, f"{request_id}:spot-entry")
        perp_order = self.simulator.open_perp_short(strategy.value, symbol, qty, perp_book, f"{request_id}:perp-entry")
        if not _is_fully_hedged(spot_order, perp_order, qty):
            return None, RiskDecision(False, "paper_entry_not_fully_hedged", "entry fill was not fully hedged", "warning")
        assert spot_order.avg_price is not None and perp_order.avg_price is not None
        profitability = check_post_fill_profitability(
            settings=self.settings,
            strategy=strategy,
            spot_price=spot_order.avg_price,
            perp_price=perp_order.avg_price,
            expected_funding=expected_funding,
        )
        if not profitability.allowed:
            return None, profitability
        position = Position(
            strategy=strategy,
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
        if spot_book.best_bid is None or perp_book.best_ask is None:
            return None
        request_id = uuid4().hex
        spot_order = self.simulator.close_spot_long(
            position.strategy.value, position.symbol, position.spot_qty, spot_book, f"{request_id}:spot-exit"
        )
        perp_order = self.simulator.close_perp_short(
            position.strategy.value, position.symbol, position.perp_qty, perp_book, f"{request_id}:perp-exit"
        )
        if not _is_fully_hedged(spot_order, perp_order, position.spot_qty):
            return None
        assert spot_order.avg_price is not None and perp_order.avg_price is not None
        close_fees = spot_order.fee + perp_order.fee
        position.exit_spot_price = spot_order.avg_price
        position.exit_perp_price = perp_order.avg_price
        position.total_fees += close_fees
        funding_income = await self._funding_income(session, position.id)
        position.realized_pnl = calculate_realized_pnl(
            qty=position.spot_qty,
            entry_spot=position.entry_spot_price,
            entry_perp=position.entry_perp_price,
            exit_spot=spot_order.avg_price,
            exit_perp=perp_order.avg_price,
            fees=position.total_fees,
            funding_income=funding_income,
        )
        position.is_open = False
        position.closed_at = utc_now()
        _persist_order(session, spot_order, position.id)
        _persist_order(session, perp_order, position.id)
        return PaperExecutionEvent(
            "closed",
            position.symbol,
            position.notional,
            position.realized_pnl,
            position.total_fees,
            funding_income,
        )

    async def _accrue_funding(
        self,
        session: AsyncSession,
        position: Position,
        funding_history: list[FundingPoint],
    ) -> Decimal:
        if position.strategy != StrategyName.FUNDING:
            return Decimal("0")
        paid_at_values = set(
            (
                await session.execute(
                    select(FundingPayment.paid_at).where(FundingPayment.position_id == position.id)
                )
            ).scalars()
        )
        accrued = Decimal("0")
        for point in funding_history:
            if point.funding_rate_timestamp <= position.opened_at or point.funding_rate_timestamp in paid_at_values:
                continue
            amount = ExecutionSimulator.simulate_funding_payment(position.notional, point.funding_rate)
            session.add(
                FundingPayment(
                    position_id=position.id,
                    symbol=position.symbol,
                    funding_rate=point.funding_rate,
                    notional=position.notional,
                    amount=amount,
                    paid_at=point.funding_rate_timestamp,
                )
            )
            accrued += amount
        return accrued

    async def _funding_payment_count(self, session: AsyncSession, position_id: object) -> int:
        return int(
            (
                await session.execute(
                    select(func.count()).select_from(FundingPayment).where(FundingPayment.position_id == position_id)
                )
            ).scalar_one()
        )

    async def _funding_income(self, session: AsyncSession, position_id: object) -> Decimal:
        return Decimal(
            (
                await session.execute(
                    select(func.coalesce(func.sum(FundingPayment.amount), Decimal("0"))).where(
                        FundingPayment.position_id == position_id
                    )
                )
            ).scalar_one()
        )


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

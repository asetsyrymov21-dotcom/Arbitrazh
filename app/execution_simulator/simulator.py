import hashlib
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from app.market_data.types import BookLevel, OrderBook

Side = Literal["buy", "sell"]
Market = Literal["spot", "perp"]
Strategy = Literal["funding", "spread"]


@dataclass(frozen=True)
class SimulatedFill:
    idempotency_key: str
    price: Decimal
    qty: Decimal
    fee: Decimal
    liquidity: str = "taker"


@dataclass(frozen=True)
class SimulatedOrderResult:
    idempotency_key: str
    strategy: Strategy
    symbol: str
    market: Market
    side: Side
    requested_qty: Decimal
    filled_qty: Decimal
    avg_price: Decimal | None
    status: Literal["filled", "partial", "rejected"]
    fee: Decimal
    slippage: Decimal
    fills: tuple[SimulatedFill, ...]
    rejected_reason: str | None = None


class ExecutionSimulator:
    def __init__(self, spot_fee_bps: Decimal, perp_fee_bps: Decimal, slippage_bps: Decimal) -> None:
        self.spot_fee_bps = spot_fee_bps
        self.perp_fee_bps = perp_fee_bps
        self.slippage_bps = slippage_bps

    def execute_market_order(
        self,
        *,
        strategy: Strategy,
        symbol: str,
        market: Market,
        side: Side,
        qty: Decimal,
        orderbook: OrderBook,
        client_order_id: str,
    ) -> SimulatedOrderResult:
        if qty <= 0:
            return self._rejected(strategy, symbol, market, side, qty, client_order_id, "qty_must_be_positive")

        levels = self._executable_levels(side, orderbook)
        if not levels:
            return self._rejected(strategy, symbol, market, side, qty, client_order_id, "missing_orderbook_depth")

        remaining = qty
        fills: list[SimulatedFill] = []
        gross_notional = Decimal("0")
        fee_bps = self.spot_fee_bps if market == "spot" else self.perp_fee_bps
        slip_multiplier = self._slippage_multiplier(side)

        for index, level in enumerate(levels):
            if remaining <= 0:
                break
            fill_qty = min(remaining, level.qty)
            slipped_price = level.price * slip_multiplier
            notional = fill_qty * slipped_price
            fee = notional * fee_bps / Decimal("10000")
            fills.append(
                SimulatedFill(
                    idempotency_key=self._key(client_order_id, "fill", str(index)),
                    price=slipped_price,
                    qty=fill_qty,
                    fee=fee,
                )
            )
            gross_notional += notional
            remaining -= fill_qty

        filled_qty = qty - remaining
        if filled_qty == 0:
            return self._rejected(strategy, symbol, market, side, qty, client_order_id, "no_fill")

        avg_price = gross_notional / filled_qty
        top_price = levels[0].price
        slippage = abs(avg_price - top_price) * filled_qty
        status = "filled" if remaining == 0 else "partial"
        return SimulatedOrderResult(
            idempotency_key=self._key(client_order_id, "order"),
            strategy=strategy,
            symbol=symbol,
            market=market,
            side=side,
            requested_qty=qty,
            filled_qty=filled_qty,
            avg_price=avg_price,
            status=status,
            fee=sum((fill.fee for fill in fills), Decimal("0")),
            slippage=slippage,
            fills=tuple(fills),
            rejected_reason=None if status == "filled" else "insufficient_depth",
        )

    def open_spot_long(
        self, strategy: Strategy, symbol: str, qty: Decimal, orderbook: OrderBook, client_order_id: str
    ) -> SimulatedOrderResult:
        return self.execute_market_order(
            strategy=strategy, symbol=symbol, market="spot", side="buy", qty=qty, orderbook=orderbook, client_order_id=client_order_id
        )

    def close_spot_long(
        self, strategy: Strategy, symbol: str, qty: Decimal, orderbook: OrderBook, client_order_id: str
    ) -> SimulatedOrderResult:
        return self.execute_market_order(
            strategy=strategy, symbol=symbol, market="spot", side="sell", qty=qty, orderbook=orderbook, client_order_id=client_order_id
        )

    def open_perp_short(self, strategy: Strategy, symbol: str, qty: Decimal, orderbook: OrderBook, client_order_id: str) -> SimulatedOrderResult:
        return self.execute_market_order(
            strategy=strategy, symbol=symbol, market="perp", side="sell", qty=qty, orderbook=orderbook, client_order_id=client_order_id
        )

    def close_perp_short(self, strategy: Strategy, symbol: str, qty: Decimal, orderbook: OrderBook, client_order_id: str) -> SimulatedOrderResult:
        return self.execute_market_order(
            strategy=strategy, symbol=symbol, market="perp", side="buy", qty=qty, orderbook=orderbook, client_order_id=client_order_id
        )

    @staticmethod
    def simulate_funding_payment(short_notional: Decimal, funding_rate: Decimal) -> Decimal:
        return short_notional * funding_rate

    @staticmethod
    def estimate_short_liquidation_price(entry_price: Decimal, leverage: Decimal) -> Decimal:
        # Approximation for isolated short margin; exchange maintenance tiers are handled later.
        return entry_price * (Decimal("1") + (Decimal("1") / leverage))

    def _executable_levels(self, side: Side, orderbook: OrderBook) -> tuple[BookLevel, ...]:
        if side == "buy":
            return orderbook.asks
        return orderbook.bids

    def _slippage_multiplier(self, side: Side) -> Decimal:
        adjustment = self.slippage_bps / Decimal("10000")
        return Decimal("1") + adjustment if side == "buy" else Decimal("1") - adjustment

    @staticmethod
    def _key(*parts: str) -> str:
        return hashlib.sha256(":".join(parts).encode()).hexdigest()

    def _rejected(
        self,
        strategy: Strategy,
        symbol: str,
        market: Market,
        side: Side,
        qty: Decimal,
        client_order_id: str,
        reason: str,
    ) -> SimulatedOrderResult:
        return SimulatedOrderResult(
            idempotency_key=self._key(client_order_id, "order"),
            strategy=strategy,
            symbol=symbol,
            market=market,
            side=side,
            requested_qty=qty,
            filled_qty=Decimal("0"),
            avg_price=None,
            status="rejected",
            fee=Decimal("0"),
            slippage=Decimal("0"),
            fills=(),
            rejected_reason=reason,
        )

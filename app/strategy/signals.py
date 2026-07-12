from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from app.market_data.types import FundingPoint, OrderBook, Ticker

SignalAction = Literal["enter", "exit", "hold", "reject"]


@dataclass(frozen=True)
class StrategySignal:
    strategy: Literal["funding", "spread"]
    symbol: str
    action: SignalAction
    strength: Decimal
    reason: str
    payload: dict[str, str]


def executable_entry_spread(spot_book: OrderBook, perp_book: OrderBook) -> Decimal | None:
    if spot_book.best_ask is None or perp_book.best_bid is None:
        return None
    return (perp_book.best_bid.price / spot_book.best_ask.price) - Decimal("1")


def executable_exit_spread(spot_book: OrderBook, perp_book: OrderBook) -> Decimal | None:
    if spot_book.best_bid is None or perp_book.best_ask is None:
        return None
    return (perp_book.best_ask.price / spot_book.best_bid.price) - Decimal("1")


class FundingStrategy:
    def __init__(
        self,
        horizon_periods: int,
        persistence_periods: int,
        cost_safety_factor: Decimal,
        round_trip_cost_bps: Decimal,
    ) -> None:
        self.horizon_periods = horizon_periods
        self.persistence_periods = persistence_periods
        self.cost_safety_factor = cost_safety_factor
        self.round_trip_cost = round_trip_cost_bps / Decimal("10000")

    def evaluate(
        self,
        *,
        symbol: str,
        linear_ticker: Ticker,
        funding_history: list[FundingPoint],
        spot_book: OrderBook,
        perp_book: OrderBook,
    ) -> StrategySignal:
        if spot_book.best_ask is None or perp_book.best_bid is None:
            return self._reject(symbol, "missing_orderbook_depth")
        if linear_ticker.funding_rate is None:
            return self._reject(symbol, "missing_current_funding")
        prior = funding_history[: self.persistence_periods]
        if len(prior) < self.persistence_periods:
            return self._reject(symbol, "insufficient_funding_history")
        if any(point.funding_rate <= 0 for point in prior):
            return self._reject(symbol, "funding_not_persistent")

        expected_funding = linear_ticker.funding_rate * Decimal(self.horizon_periods)
        required = self.round_trip_cost * self.cost_safety_factor
        if expected_funding <= required:
            return StrategySignal(
                "funding",
                symbol,
                "reject",
                expected_funding,
                "expected_funding_below_cost_safety_factor",
                {"expected_funding": str(expected_funding), "required": str(required)},
            )

        spread = executable_entry_spread(spot_book, perp_book)
        return StrategySignal(
            "funding",
            symbol,
            "enter",
            expected_funding,
            "positive_persistent_funding_after_costs",
            {"expected_funding": str(expected_funding), "entry_spread": str(spread)},
        )

    @staticmethod
    def _reject(symbol: str, reason: str) -> StrategySignal:
        return StrategySignal("funding", symbol, "reject", Decimal("0"), reason, {})


class SpreadStrategy:
    def __init__(self, entry_threshold_bps: Decimal, exit_threshold_bps: Decimal, round_trip_cost_bps: Decimal) -> None:
        self.entry_threshold = entry_threshold_bps / Decimal("10000")
        self.exit_threshold = exit_threshold_bps / Decimal("10000")
        self.round_trip_cost = round_trip_cost_bps / Decimal("10000")

    def evaluate_entry(self, *, symbol: str, spot_book: OrderBook, perp_book: OrderBook) -> StrategySignal:
        spread = executable_entry_spread(spot_book, perp_book)
        if spread is None:
            return StrategySignal("spread", symbol, "reject", Decimal("0"), "missing_orderbook_depth", {})
        required = self.entry_threshold + self.round_trip_cost
        if spread <= required:
            return StrategySignal(
                "spread",
                symbol,
                "reject",
                spread,
                "entry_spread_below_threshold_after_costs",
                {"entry_spread": str(spread), "required": str(required)},
            )
        return StrategySignal(
            "spread",
            symbol,
            "enter",
            spread,
            "entry_spread_exceeds_cost_adjusted_threshold",
            {"entry_spread": str(spread), "required": str(required)},
        )

    def evaluate_exit(self, *, symbol: str, spot_book: OrderBook, perp_book: OrderBook) -> StrategySignal:
        spread = executable_exit_spread(spot_book, perp_book)
        if spread is None:
            return StrategySignal("spread", symbol, "hold", Decimal("0"), "missing_orderbook_depth", {})
        if spread <= self.exit_threshold:
            return StrategySignal("spread", symbol, "exit", spread, "spread_converged_to_exit_threshold", {"exit_spread": str(spread)})
        return StrategySignal("spread", symbol, "hold", spread, "spread_not_converged", {"exit_spread": str(spread)})


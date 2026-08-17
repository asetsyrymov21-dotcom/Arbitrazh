from datetime import UTC, datetime
from decimal import Decimal

from app.execution_simulator.simulator import ExecutionSimulator
from app.core.settings import Settings
from app.execution_simulator.paper_execution import (
    calculate_realized_pnl,
    check_open_position_limit,
    check_post_fill_profitability,
)
from app.market_data.types import BookLevel, OrderBook
from app.persistence.models import StrategyName


def make_book() -> OrderBook:
    return OrderBook(
        symbol="BTCUSDT",
        category="spot",
        bids=(BookLevel(Decimal("99"), Decimal("1")), BookLevel(Decimal("98"), Decimal("2"))),
        asks=(BookLevel(Decimal("101"), Decimal("1")), BookLevel(Decimal("102"), Decimal("2"))),
        ts=datetime.now(UTC),
    )


def test_buy_uses_ask_depth_and_fees() -> None:
    simulator = ExecutionSimulator(spot_fee_bps=Decimal("10"), perp_fee_bps=Decimal("5"), slippage_bps=Decimal("0"))
    result = simulator.execute_market_order(
        strategy="funding",
        symbol="BTCUSDT",
        market="spot",
        side="buy",
        qty=Decimal("2"),
        orderbook=make_book(),
        client_order_id="entry-1",
    )

    assert result.status == "filled"
    assert result.filled_qty == Decimal("2")
    assert result.avg_price == Decimal("101.5")
    assert result.fee == Decimal("0.2030")
    assert [fill.price for fill in result.fills] == [Decimal("101"), Decimal("102")]


def test_sell_uses_bid_depth_and_partial_fill() -> None:
    simulator = ExecutionSimulator(spot_fee_bps=Decimal("10"), perp_fee_bps=Decimal("5"), slippage_bps=Decimal("0"))
    result = simulator.execute_market_order(
        strategy="spread",
        symbol="BTCUSDT",
        market="perp",
        side="sell",
        qty=Decimal("5"),
        orderbook=make_book(),
        client_order_id="entry-2",
    )

    assert result.status == "partial"
    assert result.filled_qty == Decimal("3")
    assert result.avg_price == Decimal("98.33333333333333333333333333")
    assert result.rejected_reason == "insufficient_depth"


def test_funding_payment_for_short_receives_positive_funding() -> None:
    assert ExecutionSimulator.simulate_funding_payment(Decimal("10000"), Decimal("0.0001")) == Decimal("1.0000")


def test_realized_pnl_accounts_for_both_hedge_legs_and_fees() -> None:
    pnl = calculate_realized_pnl(
        qty=Decimal("2"),
        entry_spot=Decimal("100"),
        entry_perp=Decimal("101"),
        exit_spot=Decimal("102"),
        exit_perp=Decimal("102"),
        fees=Decimal("0.5"),
    )
    assert pnl == Decimal("1.5")


def test_realized_pnl_includes_funding_income() -> None:
    pnl = calculate_realized_pnl(
        qty=Decimal("100"),
        entry_spot=Decimal("10"),
        entry_perp=Decimal("10"),
        exit_spot=Decimal("10"),
        exit_perp=Decimal("10"),
        fees=Decimal("3"),
        funding_income=Decimal("8"),
    )

    assert pnl == Decimal("5")


def test_open_position_limit_blocks_the_fourth_position() -> None:
    decision = check_open_position_limit(open_positions=3, max_open_positions=3)

    assert decision.allowed is False
    assert decision.code == "max_open_positions"


def test_post_fill_spread_rejects_depth_inverted_entry() -> None:
    decision = check_post_fill_profitability(
        settings=Settings(),
        strategy=StrategyName.SPREAD,
        spot_price=Decimal("100"),
        perp_price=Decimal("99.8"),
        expected_funding=None,
    )

    assert decision.allowed is False
    assert decision.code == "post_fill_spread_below_threshold"


def test_post_fill_funding_includes_actual_entry_basis() -> None:
    decision = check_post_fill_profitability(
        settings=Settings(),
        strategy=StrategyName.FUNDING,
        spot_price=Decimal("100"),
        perp_price=Decimal("99.5"),
        expected_funding=Decimal("0.01"),
    )

    assert decision.allowed is False
    assert decision.code == "post_fill_funding_below_costs"

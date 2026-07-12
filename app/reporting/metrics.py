from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal


@dataclass(frozen=True)
class PerformanceMetrics:
    net_pnl: Decimal
    funding_income: Decimal
    spread_pnl: Decimal
    spot_pnl: Decimal
    futures_pnl: Decimal
    fees: Decimal
    slippage: Decimal
    win_rate: Decimal
    average_holding_time: timedelta | None
    max_drawdown: Decimal
    sharpe_like: Decimal | None
    capital_utilization: Decimal


EMPTY_METRICS = PerformanceMetrics(
    net_pnl=Decimal("0"),
    funding_income=Decimal("0"),
    spread_pnl=Decimal("0"),
    spot_pnl=Decimal("0"),
    futures_pnl=Decimal("0"),
    fees=Decimal("0"),
    slippage=Decimal("0"),
    win_rate=Decimal("0"),
    average_holding_time=None,
    max_drawdown=Decimal("0"),
    sharpe_like=None,
    capital_utilization=Decimal("0"),
)


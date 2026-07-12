from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from app.market_data.types import OrderBook


@dataclass(frozen=True)
class RiskDecision:
    allowed: bool
    code: str
    message: str
    severity: str = "info"


class RiskEngine:
    def __init__(
        self,
        *,
        stale_seconds: int,
        max_drawdown_pct: Decimal,
        max_symbol_exposure_pct: Decimal,
        max_total_deployed_pct: Decimal,
        delta_mismatch_pct: Decimal,
    ) -> None:
        self.stale_seconds = stale_seconds
        self.max_drawdown_pct = max_drawdown_pct
        self.max_symbol_exposure_pct = max_symbol_exposure_pct
        self.max_total_deployed_pct = max_total_deployed_pct
        self.delta_mismatch_pct = delta_mismatch_pct

    def check_market_data_fresh(self, book: OrderBook, now: datetime) -> RiskDecision:
        age = (now - book.ts).total_seconds()
        if age > self.stale_seconds:
            return RiskDecision(False, "stale_market_data", f"{book.symbol}:{book.category} age {age:.1f}s", "warning")
        if book.best_bid is None or book.best_ask is None:
            return RiskDecision(False, "missing_orderbook", f"{book.symbol}:{book.category} has missing book side", "critical")
        return RiskDecision(True, "ok", "market data fresh")

    def check_capital_limits(
        self,
        *,
        equity: Decimal,
        deployed_capital: Decimal,
        symbol_exposure: Decimal,
        new_notional: Decimal,
    ) -> RiskDecision:
        if equity <= 0:
            return RiskDecision(False, "invalid_equity", "equity must be positive", "critical")
        if (deployed_capital + new_notional) / equity > self.max_total_deployed_pct:
            return RiskDecision(False, "max_total_deployed", "total deployed capital limit exceeded", "critical")
        if (symbol_exposure + new_notional) / equity > self.max_symbol_exposure_pct:
            return RiskDecision(False, "max_symbol_exposure", "per-symbol exposure limit exceeded", "warning")
        return RiskDecision(True, "ok", "capital limits ok")

    def check_drawdown(self, *, equity: Decimal, peak_equity: Decimal) -> RiskDecision:
        if peak_equity <= 0:
            return RiskDecision(False, "invalid_peak_equity", "peak equity must be positive", "critical")
        drawdown = (peak_equity - equity) / peak_equity
        if drawdown >= self.max_drawdown_pct:
            return RiskDecision(False, "max_drawdown", f"drawdown {drawdown:.4f} exceeds limit", "critical")
        return RiskDecision(True, "ok", "drawdown ok")

    def check_delta_match(self, *, spot_notional: Decimal, perp_notional: Decimal) -> RiskDecision:
        larger = max(abs(spot_notional), abs(perp_notional))
        if larger == 0:
            return RiskDecision(False, "zero_notional", "cannot trade zero notional", "warning")
        mismatch = abs(spot_notional - perp_notional) / larger
        if mismatch > self.delta_mismatch_pct:
            return RiskDecision(False, "delta_mismatch", f"delta mismatch {mismatch:.4f} exceeds limit", "warning")
        return RiskDecision(True, "ok", "delta match ok")


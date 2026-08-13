from decimal import Decimal

from app.market_data.types import Ticker


def select_funding_candidates(
    linear_tickers: list[Ticker],
    spot_symbols: set[str],
    *,
    limit: int,
    min_turnover_usdt: Decimal,
) -> list[str]:
    """Return the highest-turnover USDT pairs available on both spot and perpetual."""
    eligible = [
        ticker
        for ticker in linear_tickers
        if ticker.symbol.endswith("USDT")
        and ticker.symbol in spot_symbols
        and ticker.funding_rate is not None
        and _turnover(ticker) >= min_turnover_usdt
    ]
    eligible.sort(key=_turnover, reverse=True)
    return [ticker.symbol for ticker in eligible[:limit]]


def _turnover(ticker: Ticker) -> Decimal:
    return Decimal(str(ticker.raw.get("turnover24h", "0")))

from datetime import UTC, datetime
from decimal import Decimal

from app.market_data.types import Ticker
from app.market_data.universe import select_funding_candidates


def _ticker(symbol: str, funding: str, turnover: str) -> Ticker:
    return Ticker(
        symbol=symbol,
        category="linear",
        bid=None,
        ask=None,
        mark_price=None,
        index_price=None,
        funding_rate=Decimal(funding),
        next_funding_time=datetime.now(UTC),
        raw={"turnover24h": turnover},
    )


def test_funding_universe_keeps_only_liquid_spot_perp_pairs() -> None:
    candidates = select_funding_candidates(
        [
            _ticker("HIGHVOLUMEUSDT", "-0.001", "50000000"),
            _ticker("LOWVOLUMEUSDT", "0.01", "25000000"),
            _ticker("ILLIQUIDUSDT", "0.01", "100"),
        ],
        {"HIGHVOLUMEUSDT", "LOWVOLUMEUSDT", "ILLIQUIDUSDT"},
        limit=2,
        min_turnover_usdt=Decimal("10000000"),
    )

    assert candidates == ["HIGHVOLUMEUSDT", "LOWVOLUMEUSDT"]

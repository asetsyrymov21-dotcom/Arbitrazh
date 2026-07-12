from decimal import Decimal

from app.market_data.bybit_public import parse_funding_point, parse_orderbook, parse_ticker


def test_parse_orderbook_uses_bid_ask_depth() -> None:
    book = parse_orderbook(
        "spot",
        {
            "s": "BTCUSDT",
            "b": [["65485.47", "47.081829"]],
            "a": [["65557.70", "16.606555"]],
            "ts": 1716863719031,
            "u": 230704,
            "seq": 1432604333,
        },
    )

    assert book.symbol == "BTCUSDT"
    assert book.best_bid is not None
    assert book.best_bid.price == Decimal("65485.47")
    assert book.best_ask is not None
    assert book.best_ask.qty == Decimal("16.606555")
    assert book.update_id == 230704


def test_parse_linear_ticker_funding_fields() -> None:
    ticker = parse_ticker(
        "linear",
        {
            "symbol": "BTCUSDT",
            "bid1Price": "65480",
            "ask1Price": "65490",
            "markPrice": "65485",
            "indexPrice": "65470",
            "fundingRate": "0.0001",
            "nextFundingTime": "1716864000000",
        },
    )

    assert ticker.funding_rate == Decimal("0.0001")
    assert ticker.next_funding_time is not None


def test_parse_funding_history_point() -> None:
    point = parse_funding_point(
        {
            "symbol": "ETHUSDT",
            "fundingRate": "0.0002",
            "fundingRateTimestamp": "1716864000000",
        }
    )

    assert point.symbol == "ETHUSDT"
    assert point.funding_rate == Decimal("0.0002")


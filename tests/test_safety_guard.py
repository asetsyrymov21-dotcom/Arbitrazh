import pytest

from app.market_data.bybit_public import RealTradingEndpointBlocked, ensure_public_market_endpoint


def test_public_market_endpoint_is_allowed() -> None:
    ensure_public_market_endpoint("/v5/market/orderbook")


@pytest.mark.parametrize(
    "path",
    [
        "/v5/order/create",
        "/v5/trade",
        "/v5/position/list",
        "/v5/account/wallet-balance",
        "/v5/asset/transfer/query-account-coins-balance",
        "/private/order",
    ],
)
def test_real_trading_and_private_endpoints_are_blocked(path: str) -> None:
    with pytest.raises(RealTradingEndpointBlocked):
        ensure_public_market_endpoint(path)


def test_unknown_endpoint_is_blocked_by_default() -> None:
    with pytest.raises(RealTradingEndpointBlocked):
        ensure_public_market_endpoint("/v5/market/recent-trade")


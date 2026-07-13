import asyncio
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from urllib.parse import urljoin

import httpx
import websockets

try:
    import structlog
except ModuleNotFoundError:  # pragma: no cover - dependency is installed in the Docker image.
    import logging

    class _FallbackLogger:
        def warning(self, event: str, **kwargs: object) -> None:
            logging.getLogger(__name__).warning("%s %s", event, kwargs)

    class _FallbackStructlog:
        @staticmethod
        def get_logger(_: str) -> _FallbackLogger:
            return _FallbackLogger()

    structlog = _FallbackStructlog()  # type: ignore[assignment]

from app.core.time import ms_to_utc
from app.market_data.types import BookLevel, Category, FundingPoint, OrderBook, Ticker

log = structlog.get_logger(__name__)


class RealTradingEndpointBlocked(RuntimeError):
    pass


PUBLIC_MARKET_ENDPOINTS = {
    "/v5/market/time",
    "/v5/market/orderbook",
    "/v5/market/tickers",
    "/v5/market/funding/history",
    "/v5/market/instruments-info",
}
BLOCKED_PATH_TOKENS = {
    "/v5/order",
    "/v5/trade",
    "/v5/position",
    "/v5/account",
    "/v5/asset",
    "/v5/user",
    "/private",
}


def ensure_public_market_endpoint(path: str) -> None:
    normalized = path.rstrip("/")
    if normalized not in PUBLIC_MARKET_ENDPOINTS:
        raise RealTradingEndpointBlocked(f"Endpoint is not allow-listed for paper mode: {path}")
    lowered = normalized.lower()
    if any(token in lowered for token in BLOCKED_PATH_TOKENS):
        raise RealTradingEndpointBlocked(f"Real trading/private endpoint blocked: {path}")


class BybitPublicClient:
    def __init__(
        self,
        base_url: str,
        ws_spot_url: str,
        ws_linear_url: str,
        timeout_seconds: float = 10,
    ) -> None:
        self.base_url = base_url.rstrip("/") + "/"
        self.ws_spot_url = ws_spot_url
        self.ws_linear_url = ws_linear_url
        self._http = httpx.AsyncClient(timeout=timeout_seconds)

    async def close(self) -> None:
        await self._http.aclose()

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        ensure_public_market_endpoint(path)
        response = await self._http.get(urljoin(self.base_url, path.lstrip("/")), params=params)
        response.raise_for_status()
        payload = response.json()
        if payload.get("retCode") != 0:
            raise RuntimeError(f"Bybit returned retCode={payload.get('retCode')}: {payload.get('retMsg')}")
        return payload

    async def get_orderbook(self, category: Category, symbol: str, limit: int = 50) -> OrderBook:
        payload = await self._get(
            "/v5/market/orderbook",
            {"category": category, "symbol": symbol.upper(), "limit": limit},
        )
        return parse_orderbook(category, payload["result"])

    async def get_ticker(self, category: Category, symbol: str) -> Ticker:
        payload = await self._get("/v5/market/tickers", {"category": category, "symbol": symbol.upper()})
        items = payload["result"]["list"]
        if not items:
            raise RuntimeError(f"No ticker returned for {category}:{symbol}")
        return parse_ticker(category, items[0])

    async def get_tickers(self, category: Category) -> list[Ticker]:
        payload = await self._get("/v5/market/tickers", {"category": category})
        return [parse_ticker(category, item) for item in payload["result"]["list"]]

    async def get_instruments_info(self, category: Category, symbol: str) -> dict[str, Any]:
        payload = await self._get(
            "/v5/market/instruments-info",
            {"category": category, "symbol": symbol.upper()},
        )
        return payload["result"]

    async def get_funding_history(self, symbol: str, limit: int = 20) -> list[FundingPoint]:
        payload = await self._get(
            "/v5/market/funding/history",
            {"category": "linear", "symbol": symbol.upper(), "limit": limit},
        )
        return [parse_funding_point(item) for item in payload["result"].get("list", [])]

    async def stream_orderbooks(
        self,
        category: Category,
        symbols: list[str],
        depth: int = 50,
    ) -> AsyncIterator[OrderBook]:
        ws_url = self.ws_spot_url if category == "spot" else self.ws_linear_url
        topics = [f"orderbook.{depth}.{symbol.upper()}" for symbol in symbols]
        backoff = 1.0
        while True:
            try:
                async with websockets.connect(ws_url, ping_interval=20, ping_timeout=10) as websocket:
                    await websocket.send(json.dumps({"op": "subscribe", "args": topics}))
                    backoff = 1.0
                    async for raw_message in websocket:
                        message = json.loads(raw_message)
                        if "topic" not in message or "data" not in message:
                            continue
                        symbol = message["topic"].split(".")[-1]
                        data = message["data"]
                        data.setdefault("s", symbol)
                        yield parse_orderbook(category, data)
            except Exception as exc:
                log.warning("bybit_ws_reconnect", category=category, error=str(exc), backoff=backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)


def _decimal(value: str | int | float | Decimal | None) -> Decimal | None:
    if value in (None, ""):
        return None
    return Decimal(str(value))


def _levels(raw: list[list[str]]) -> tuple[BookLevel, ...]:
    return tuple(BookLevel(price=Decimal(price), qty=Decimal(qty)) for price, qty in raw)


def parse_orderbook(category: Category, result: dict[str, Any]) -> OrderBook:
    ts_value = result.get("ts") or result.get("T")
    ts = ms_to_utc(ts_value) or datetime.now(UTC)
    return OrderBook(
        symbol=result["s"],
        category=category,
        bids=_levels(result.get("b", [])),
        asks=_levels(result.get("a", [])),
        ts=ts,
        update_id=int(result["u"]) if result.get("u") is not None else None,
        sequence=int(result["seq"]) if result.get("seq") is not None else None,
        raw=result,
    )


def parse_ticker(category: Category, item: dict[str, Any]) -> Ticker:
    return Ticker(
        symbol=item["symbol"],
        category=category,
        bid=_decimal(item.get("bid1Price")),
        ask=_decimal(item.get("ask1Price")),
        mark_price=_decimal(item.get("markPrice")),
        index_price=_decimal(item.get("indexPrice")),
        funding_rate=_decimal(item.get("fundingRate")),
        next_funding_time=ms_to_utc(item.get("nextFundingTime")),
        raw=item,
    )


def parse_funding_point(item: dict[str, Any]) -> FundingPoint:
    ts = ms_to_utc(item.get("fundingRateTimestamp"))
    if ts is None:
        raise ValueError("fundingRateTimestamp is required")
    return FundingPoint(
        symbol=item["symbol"],
        funding_rate=Decimal(item["fundingRate"]),
        funding_rate_timestamp=ts,
        raw=item,
    )

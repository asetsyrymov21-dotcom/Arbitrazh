from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal


Category = Literal["spot", "linear"]


@dataclass(frozen=True)
class BookLevel:
    price: Decimal
    qty: Decimal


@dataclass(frozen=True)
class OrderBook:
    symbol: str
    category: Category
    bids: tuple[BookLevel, ...]
    asks: tuple[BookLevel, ...]
    ts: datetime
    update_id: int | None = None
    sequence: int | None = None
    raw: dict[str, Any] | None = None

    @property
    def best_bid(self) -> BookLevel | None:
        return self.bids[0] if self.bids else None

    @property
    def best_ask(self) -> BookLevel | None:
        return self.asks[0] if self.asks else None


@dataclass(frozen=True)
class Ticker:
    symbol: str
    category: Category
    bid: Decimal | None
    ask: Decimal | None
    mark_price: Decimal | None
    index_price: Decimal | None
    funding_rate: Decimal | None
    next_funding_time: datetime | None
    raw: dict[str, Any]


@dataclass(frozen=True)
class FundingPoint:
    symbol: str
    funding_rate: Decimal
    funding_rate_timestamp: datetime
    raw: dict[str, Any]


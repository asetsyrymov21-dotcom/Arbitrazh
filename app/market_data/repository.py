from sqlalchemy.ext.asyncio import AsyncSession

from app.market_data.types import OrderBook
from app.persistence.models import MarketSnapshot


async def persist_orderbook_snapshot(session: AsyncSession, book: OrderBook) -> MarketSnapshot:
    snapshot = MarketSnapshot(
        symbol=book.symbol,
        category=book.category,
        ts=book.ts,
        bid_price=book.best_bid.price if book.best_bid else None,
        bid_size=book.best_bid.qty if book.best_bid else None,
        ask_price=book.best_ask.price if book.best_ask else None,
        ask_size=book.best_ask.qty if book.best_ask else None,
        orderbook={
            "bids": [[str(level.price), str(level.qty)] for level in book.bids],
            "asks": [[str(level.price), str(level.qty)] for level in book.asks],
        },
        raw=book.raw or {},
    )
    session.add(snapshot)
    return snapshot


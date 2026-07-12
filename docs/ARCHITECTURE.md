# Architecture

## Goal

Build a production-like Bybit paper-trading service that simulates, but never sends, orders for:

- funding-rate arbitrage: spot long plus equal-size USDT perpetual short;
- spread arbitrage: executable futures bid versus spot ask entry spread and executable exit spread.

The starting virtual portfolio is 100,000 USDT. All timestamps are UTC.

## Safety Assumptions

- MVP uses only Bybit V5 public market data endpoints.
- No exchange API key settings exist.
- No real order endpoints are implemented.
- `BybitPublicClient` allow-lists `/v5/market/orderbook`, `/v5/market/tickers`, `/v5/market/funding/history`, `/v5/market/instruments-info`, and `/v5/market/time`.
- Any path containing trade/private/order/account/position/asset/user execution surfaces is rejected before an HTTP request is made.

## Components

- `market_data`: public REST/WebSocket client, order book cache, stale data detection, snapshot persistence.
- `strategy`: funding and spread signal generation using executable bid/ask/depth, never last price.
- `execution_simulator`: deterministic depth-walking fills, fees, slippage, partial/rejected fills, idempotency keys.
- `portfolio`: virtual cash, spot/perp positions, funding payments, equity snapshots.
- `risk`: drawdown, exposure, stale data, liquidity, delta mismatch, margin, and circuit breaker checks.
- `persistence`: SQLAlchemy 2 models and repositories.
- `reporting`: PnL and risk metrics.
- `telegram`: command and notification surface for monitoring and simulated controls.
- `api/dashboard`: FastAPI endpoints for health, positions, signals, trades, PnL, metrics, settings, and risk events.

## Bybit Public API References

- REST orderbook: `GET /v5/market/orderbook`, response includes sorted bid/ask arrays, exchange timestamps, update id, and sequence.
- REST tickers: `GET /v5/market/tickers`, response includes best bid/ask, mark/index prices, funding rate and next funding time for linear contracts.
- REST instruments: `GET /v5/market/instruments-info`, used for trading restrictions and lot/price filters.
- REST funding history: `GET /v5/market/funding/history`.
- WebSocket public orderbook topics use `orderbook.{depth}.{symbol}` under public spot and linear streams.

## Accounting

Entry opens equal notional legs:

- spot leg buys from spot ask depth;
- perpetual leg shorts from linear futures bid depth.

Exit reverses at executable prices:

- spot leg sells into spot bid depth;
- perpetual short closes using futures ask depth.

PnL is decomposed into spot PnL, futures PnL, funding, fees, and slippage. Funding payments are simulated from position notional and observed funding rates.

## MVP Limits

This skeleton prioritizes accounting correctness, hard safety, deterministic simulation, and testability. Live WebSocket loops and Telegram polling are implemented as startable services, but strategy scheduling is intentionally thin so it can be operated safely against public data first.


# Bybit Paper Arbitrage

Paper-trading only bot for Bybit V5 public market data. It simulates funding-rate and spot/perpetual spread arbitrage on a virtual 100,000 USDT portfolio and intentionally contains no real order submission code.

## Local Start

```bash
cp .env.example .env
docker compose up --build
```

API:

```bash
curl http://localhost:8000/health
curl http://localhost:8000/settings
```

Development checks:

```bash
python -m pip install -e ".[dev]"
pytest
ruff check .
mypy app
```

## Safety

The Bybit client allow-lists public market endpoints only. Any attempted private or trade path raises `RealTradingEndpointBlocked`. The MVP does not accept exchange API keys.


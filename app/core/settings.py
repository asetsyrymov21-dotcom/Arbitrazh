from decimal import Decimal
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "local"
    database_url: str = "postgresql+asyncpg://paper:paper@localhost:5432/paper"
    bybit_base_url: str = "https://api.bybit.com"
    bybit_ws_spot_url: str = "wss://stream.bybit.com/v5/public/spot"
    bybit_ws_linear_url: str = "wss://stream.bybit.com/v5/public/linear"
    watchlist: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    )

    virtual_capital_usdt: Decimal = Decimal("100000")
    max_active_notional_pct: Decimal = Decimal("0.20")
    max_total_deployed_pct: Decimal = Decimal("0.60")
    max_open_positions: int = 3
    default_leverage: Decimal = Decimal("2")
    max_leverage: Decimal = Decimal("3")

    spot_taker_fee_bps: Decimal = Decimal("10")
    perp_taker_fee_bps: Decimal = Decimal("5.5")
    slippage_bps: Decimal = Decimal("2")

    funding_horizon_periods: int = 3
    funding_persistence_periods: int = 2
    funding_cost_safety_factor: Decimal = Decimal("2")
    spread_entry_threshold_bps: Decimal = Decimal("30")
    spread_exit_threshold_bps: Decimal = Decimal("5")
    market_poll_seconds: int = 60
    enable_funding_universe_scan: bool = True
    funding_scan_limit: int = 30
    min_funding_scan_turnover_usdt: Decimal = Decimal("10000000")
    signal_notification_cooldown_seconds: int = 900
    enable_market_event_loop: bool = True

    stale_market_data_seconds: int = 10
    max_drawdown_pct: Decimal = Decimal("0.15")
    max_symbol_exposure_pct: Decimal = Decimal("0.25")
    delta_mismatch_pct: Decimal = Decimal("0.03")

    telegram_bot_token: str | None = None
    telegram_allowed_chat_ids: Annotated[list[int], NoDecode] = Field(default_factory=list)
    telegram_notify_chat_id: str | None = None

    @field_validator("watchlist", mode="before")
    @classmethod
    def parse_watchlist(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, str):
            return [item.strip().upper() for item in value.split(",") if item.strip()]
        return value

    @field_validator("telegram_allowed_chat_ids", mode="before")
    @classmethod
    def parse_chat_ids(cls, value: str | list[int] | None) -> list[int]:
        if value in (None, ""):
            return []
        if isinstance(value, str):
            return [int(item.strip()) for item in value.split(",") if item.strip()]
        return value


settings = Settings()

from dataclasses import dataclass
from typing import Protocol

import httpx

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

from app.core.settings import Settings
from app.execution_simulator.paper_execution import PaperExecutionEvent
from app.risk.engine import RiskDecision
from app.strategy.signals import StrategySignal

log = structlog.get_logger(__name__)


class AsyncPostClient(Protocol):
    async def post(self, url: str, json: dict[str, object]) -> httpx.Response:
        pass


@dataclass(frozen=True)
class TelegramNotifier:
    token: str
    chat_id: str
    client: AsyncPostClient

    @classmethod
    def from_settings(cls, settings: Settings, client: AsyncPostClient) -> "TelegramNotifier | None":
        if not settings.telegram_bot_token or not settings.telegram_notify_chat_id:
            return None
        return cls(
            token=settings.telegram_bot_token,
            chat_id=settings.telegram_notify_chat_id,
            client=client,
        )

    async def send(self, text: str) -> bool:
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        payload: dict[str, object] = {
            "chat_id": self.chat_id,
            "text": text,
            "disable_web_page_preview": True,
        }
        try:
            response = await self.client.post(url, json=payload)
            response.raise_for_status()
        except Exception as exc:
            log.warning("telegram_notify_failed", error=str(exc))
            return False
        return True


def render_startup_message(watchlist: list[str]) -> str:
    symbols = ", ".join(watchlist)
    return (
        "Bybit paper arbitrage bot запущен\n"
        "Режим: только paper trading\n"
        f"Мониторинг: {symbols}\n"
        "Защита: реальные биржевые ордера заблокированы"
    )


def render_signal_message(signal: StrategySignal) -> str:
    details = "\n".join(
        f"{_translate_payload_key(key)}: {value}" for key, value in sorted(signal.payload.items())
    )
    suffix = f"\n{details}" if details else ""
    return (
        "Paper-сигнал\n"
        f"Стратегия: {_translate_strategy(signal.strategy)}\n"
        f"Символ: {signal.symbol}\n"
        f"Действие: {_translate_action(signal.action)}\n"
        f"Сила сигнала: {signal.strength}\n"
        f"Причина: {_translate_reason(signal.reason)}"
        f"{suffix}"
    )


def render_risk_message(symbol: str | None, decision: RiskDecision) -> str:
    subject = symbol or "system"
    return (
        "Risk alert\n"
        f"Важность: {_translate_severity(decision.severity)}\n"
        f"Объект: {subject}\n"
        f"Код: {_translate_reason(decision.code)}\n"
        f"Сообщение: {decision.message}"
    )


def render_paper_execution_message(event: PaperExecutionEvent) -> str:
    if event.kind == "opened":
        return (
            "Paper-позиция открыта\n"
            f"Символ: {event.symbol}\n"
            "Конструкция: spot long + perpetual short\n"
            f"Объем: {event.notional:.2f} USDT\n"
            f"Комиссии входа: {event.fees:.4f} USDT"
        )
    return (
        "Paper-позиция закрыта\n"
        f"Символ: {event.symbol}\n"
        f"Объем: {event.notional:.2f} USDT\n"
        f"Реализованный PnL: {event.pnl:.4f} USDT\n"
        f"Все комиссии: {event.fees:.4f} USDT"
    )


def _translate_strategy(value: str) -> str:
    return {"funding": "funding arbitrage", "spread": "spread arbitrage"}.get(value, value)


def _translate_action(value: str) -> str:
    return {
        "enter": "вход",
        "exit": "выход",
        "hold": "держать",
        "reject": "пропуск",
    }.get(value, value)


def _translate_payload_key(value: str) -> str:
    return {
        "entry_spread": "спред входа",
        "exit_spread": "спред выхода",
        "expected_funding": "ожидаемый funding",
        "required": "минимум после costs/safety",
    }.get(value, value)


def _translate_severity(value: str) -> str:
    return {"info": "инфо", "warning": "предупреждение", "critical": "критично"}.get(
        value,
        value,
    )


def _translate_reason(value: str) -> str:
    return {
        "entry_spread_exceeds_cost_adjusted_threshold": "спред входа выше порога после costs",
        "spread_converged_to_exit_threshold": "спред сошёлся до порога выхода",
        "market_api_error": "ошибка public market API",
        "stale_market_data": "устаревшие market data",
        "missing_orderbook": "нет нужной стороны стакана",
        "missing_orderbook_depth": "недостаточно глубины стакана",
        "funding_not_persistent": "funding не устойчиво положительный",
        "expected_funding_below_cost_safety_factor": (
            "ожидаемый funding ниже costs с safety factor"
        ),
        "insufficient_funding_history": "недостаточно истории funding",
        "missing_current_funding": "нет текущего funding rate",
    }.get(value, value)

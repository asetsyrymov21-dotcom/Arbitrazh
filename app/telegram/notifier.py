from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
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
        "Бот запущен и проверяет рынок\n"
        "Режим: учебная торговля, реальные деньги не используются\n"
        f"Основные пары: {symbols}\n"
        "Реальные биржевые ордера технически заблокированы"
    )


def render_signal_message(signal: StrategySignal) -> str:
    details = "\n".join(
        f"{_translate_payload_key(key)}: {_format_payload_value(key, value)}"
        for key, value in sorted(signal.payload.items())
    )
    suffix = f"\n{details}" if details else ""
    return (
        "Найдена торговая возможность\n"
        "Это еще не открытая сделка. Бот сначала проверит стакан и все ограничения.\n"
        f"Пара: {signal.symbol}\n"
        f"Способ заработка: {_translate_strategy(signal.strategy)}\n"
        f"Предварительное решение: {_translate_action(signal.action)}\n"
        f"Расчетная доходность: {_format_percent(signal.strength)}\n"
        f"Почему найден сигнал: {_translate_reason(signal.reason)}"
        f"{suffix}"
    )


def render_risk_message(symbol: str | None, decision: RiskDecision) -> str:
    subject = symbol or "система"
    return (
        "Предупреждение бота\n"
        f"Пара: {subject}\n"
        f"Уровень: {_translate_severity(decision.severity)}\n"
        f"Что произошло: {_risk_explanation(decision.code)}"
    )


def render_paper_execution_message(event: PaperExecutionEvent) -> str:
    purpose = _execution_purpose(event.strategy)
    if event.kind == "opened":
        return (
            "Учебная сделка открыта\n"
            f"Пара: {event.symbol}\n"
            f"Цель: {purpose}\n"
            "Что сделал бот: купил монету на обычном рынке и одновременно открыл "
            "противоположную позицию на бессрочном контракте.\n"
            f"Расчетная сумма: {event.notional:.2f} USDT\n"
            f"Комиссия за открытие: {event.fees:.2f} USDT\n"
            "Статус: позиция активна"
        )
    pnl = event.pnl or Decimal("0")
    result = "прибыль" if pnl >= 0 else "убыток"
    return (
        "Учебная сделка закрыта\n"
        f"Пара: {event.symbol}\n"
        "Статус: позиция больше не активна\n"
        f"Итог после всех расходов: {result} {abs(pnl):.2f} USDT\n"
        f"Получено выплат за удержание позиции: {(event.funding_income or Decimal('0')):.2f} USDT\n"
        f"Всего комиссий: {(event.fees or Decimal('0')):.2f} USDT"
    )


def _translate_strategy(value: str) -> str:
    return {
        "funding": "получение периодических выплат за удержание позиции",
        "spread": "заработок на схождении цен двух рынков",
    }.get(value, "арбитраж между двумя рынками")


def _translate_action(value: str) -> str:
    return {
        "enter": "проверить возможность входа",
        "exit": "проверить возможность закрытия",
        "hold": "продолжать наблюдение",
        "reject": "пропустить",
    }.get(value, "продолжать наблюдение")


def _translate_payload_key(value: str) -> str:
    return {
        "entry_spread": "разница цен при входе",
        "exit_spread": "разница цен при выходе",
        "expected_funding": "ожидаемые выплаты",
        "required": "минимально допустимая доходность",
    }.get(value, "Дополнительный показатель")


def _translate_severity(value: str) -> str:
    return {"info": "инфо", "warning": "предупреждение", "critical": "критично"}.get(
        value,
        value,
    )


def _translate_reason(value: str) -> str:
    return {
        "entry_spread_exceeds_cost_adjusted_threshold": "разница цен выше безопасного порога",
        "spread_converged_to_exit_threshold": "разница цен сократилась до уровня закрытия",
        "market_api_error": "не удалось получить рыночные данные",
        "stale_market_data": "рыночные данные пришли с задержкой",
        "missing_orderbook": "нет цен для безопасного исполнения",
        "missing_orderbook_depth": "в стакане недостаточно объема",
        "funding_not_persistent": "выплаты недостаточно устойчивы",
        "expected_funding_below_cost_safety_factor": (
            "ожидаемые выплаты не покрывают расходы с запасом"
        ),
        "insufficient_funding_history": "недостаточно истории выплат",
        "missing_current_funding": "нет текущих данных о выплатах",
    }.get(value, "условия стратегии выполнены")


def _risk_explanation(code: str) -> str:
    return {
        "market_api_error": (
            "не удалось получить свежие данные Bybit. Бот не открывал сделку и продолжит попытки."
        ),
        "stale_market_data": "данные пришли с задержкой, поэтому этот цикл пропущен.",
        "paper_entry_not_fully_hedged": (
            "сделка не открыта: в стакане не хватило объема для обеих частей позиции."
        ),
        "post_fill_spread_below_threshold": (
            "сделка не открыта: после расчета реального исполнения прибыль стала недостаточной."
        ),
        "post_fill_funding_below_costs": (
            "сделка не открыта: ожидаемые выплаты не покрывают расходы с безопасным запасом."
        ),
        "max_open_positions": "сделка не открыта: уже достигнут лимит активных позиций.",
        "missing_orderbook": "сделка не открыта: нет надежных цен для обеих частей позиции.",
    }.get(code, "действие отменено внутренней проверкой безопасности.")


def _execution_purpose(strategy: str) -> str:
    return {
        "funding": "получать периодические выплаты, оставаясь защищенным от движения цены",
        "spread": "заработать на сокращении разницы цен между двумя рынками",
    }.get(strategy, "заработать на разнице между двумя рынками")


def _format_payload_value(key: str, value: str) -> str:
    if key in {"entry_spread", "exit_spread", "expected_funding", "required"}:
        return _format_percent(value)
    return value


def _format_percent(value: Decimal | str) -> str:
    try:
        percent = Decimal(str(value)) * Decimal("100")
    except InvalidOperation:
        return str(value)
    return f"{percent:.4f}".rstrip("0").rstrip(".") + "%"

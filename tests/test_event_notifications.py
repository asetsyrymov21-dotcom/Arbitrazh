from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.market_data.event_worker import EventNotificationGate
from app.execution_simulator.paper_execution import PaperExecutionEvent
from app.risk.engine import RiskDecision
from app.strategy.signals import StrategySignal
from app.telegram.notifier import (
    render_paper_execution_message,
    render_risk_message,
    render_signal_message,
)


def test_notification_gate_deduplicates_with_cooldown() -> None:
    gate = EventNotificationGate(cooldown_seconds=60)
    now = datetime.now(UTC)

    assert gate.allow("event", now) is True
    assert gate.allow("event", now + timedelta(seconds=30)) is False
    assert gate.allow("event", now + timedelta(seconds=61)) is True


def test_signal_message_contains_trade_context() -> None:
    signal = StrategySignal(
        strategy="spread",
        symbol="BTCUSDT",
        action="enter",
        strength=Decimal("0.001"),
        reason="entry_spread_exceeds_cost_adjusted_threshold",
        payload={"entry_spread": "0.001", "required": "0.0008"},
    )

    message = render_signal_message(signal)

    assert "Это еще не открытая сделка" in message
    assert "BTCUSDT" in message
    assert "разница цен при входе: 0.1%" in message


def test_risk_message_contains_code_and_subject() -> None:
    decision = RiskDecision(False, "market_api_error", "timeout", "warning")

    message = render_risk_message("ETHUSDT", decision)

    assert "Предупреждение бота" in message
    assert "ETHUSDT" in message
    assert "Бот не открывал сделку" in message


def test_execution_messages_clearly_show_active_and_closed_status() -> None:
    opened = render_paper_execution_message(
        PaperExecutionEvent(
            "opened",
            "BTCUSDT",
            "funding",
            Decimal("10000"),
            fees=Decimal("15.5"),
        )
    )
    closed = render_paper_execution_message(
        PaperExecutionEvent(
            "closed",
            "BTCUSDT",
            "funding",
            Decimal("10000"),
            pnl=Decimal("25.25"),
            fees=Decimal("31"),
            funding_income=Decimal("60"),
        )
    )

    assert "позиция активна" in opened
    assert "периодические выплаты" in opened
    assert "позиция больше не активна" in closed
    assert "прибыль 25.25 USDT" in closed

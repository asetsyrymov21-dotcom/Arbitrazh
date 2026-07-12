from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.market_data.event_worker import EventNotificationGate
from app.risk.engine import RiskDecision
from app.strategy.signals import StrategySignal
from app.telegram.notifier import render_risk_message, render_signal_message


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

    assert "Paper-сигнал" in message
    assert "BTCUSDT" in message
    assert "спред входа" in message


def test_risk_message_contains_code_and_subject() -> None:
    decision = RiskDecision(False, "market_api_error", "timeout", "warning")

    message = render_risk_message("ETHUSDT", decision)

    assert "Risk alert" in message
    assert "ETHUSDT" in message
    assert "ошибка public market API" in message

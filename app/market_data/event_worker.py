import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select

try:
    import structlog
except ModuleNotFoundError:  # pragma: no cover - dependency is installed in the Docker image.
    import logging

    class _FallbackLogger:
        def info(self, event: str, **kwargs: object) -> None:
            logging.getLogger(__name__).info("%s %s", event, kwargs)

        def warning(self, event: str, **kwargs: object) -> None:
            logging.getLogger(__name__).warning("%s %s", event, kwargs)

    class _FallbackStructlog:
        @staticmethod
        def get_logger(_: str) -> _FallbackLogger:
            return _FallbackLogger()

    structlog = _FallbackStructlog()  # type: ignore[assignment]

from app.core.settings import Settings
from app.core.time import utc_now
from app.execution_simulator.paper_execution import PaperExecutionService
from app.market_data.bybit_public import BybitPublicClient
from app.market_data.repository import persist_orderbook_snapshot
from app.market_data.universe import select_funding_candidates
from app.persistence.database import SessionLocal
from app.persistence.models import Position, RiskEvent, Signal, StrategyName
from app.risk.engine import RiskDecision, RiskEngine
from app.strategy.signals import FundingStrategy, SpreadStrategy, StrategySignal
from app.telegram.notifier import (
    TelegramNotifier,
    render_paper_execution_message,
    render_risk_message,
    render_signal_message,
)

log = structlog.get_logger(__name__)

NotifyFn = Callable[[str], Awaitable[bool]]


class EventNotificationGate:
    def __init__(self, cooldown_seconds: int) -> None:
        self.cooldown_seconds = cooldown_seconds
        self._sent_at: dict[str, datetime] = {}

    def allow(self, key: str, now: datetime) -> bool:
        last_sent = self._sent_at.get(key)
        if last_sent is not None and (now - last_sent).total_seconds() < self.cooldown_seconds:
            return False
        self._sent_at[key] = now
        return True


async def run_market_event_loop(
    settings: Settings,
    notifier: TelegramNotifier | None,
    stop_event: asyncio.Event,
) -> None:
    if not settings.enable_market_event_loop:
        log.info("market_event_loop_disabled")
        return

    client = BybitPublicClient(
        settings.bybit_base_url,
        settings.bybit_ws_spot_url,
        settings.bybit_ws_linear_url,
    )
    gate = EventNotificationGate(settings.signal_notification_cooldown_seconds)
    try:
        while not stop_event.is_set():
            await run_market_event_cycle(settings, client, notifier, gate)
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=settings.market_poll_seconds)
            except TimeoutError:
                continue
    finally:
        await client.close()


async def run_market_event_cycle(
    settings: Settings,
    client: BybitPublicClient,
    notifier: TelegramNotifier | None,
    gate: EventNotificationGate,
) -> None:
    notify = notifier.send if notifier is not None else None
    risk = RiskEngine(
        stale_seconds=settings.stale_market_data_seconds,
        max_drawdown_pct=settings.max_drawdown_pct,
        max_symbol_exposure_pct=settings.max_symbol_exposure_pct,
        max_total_deployed_pct=settings.max_total_deployed_pct,
        delta_mismatch_pct=settings.delta_mismatch_pct,
    )
    round_trip_cost_bps = (
        settings.spot_taker_fee_bps * Decimal("2")
        + settings.perp_taker_fee_bps * Decimal("2")
        + settings.slippage_bps * Decimal("4")
    )
    funding_strategy = FundingStrategy(
        settings.funding_horizon_periods,
        settings.funding_persistence_periods,
        settings.funding_cost_safety_factor,
        round_trip_cost_bps,
    )
    spread_strategy = SpreadStrategy(
        settings.spread_entry_threshold_bps,
        settings.spread_exit_threshold_bps,
        round_trip_cost_bps,
    )

    for symbol in await _symbols_for_cycle(settings, client):
        try:
            spot_book, perp_book, linear_ticker, funding_history = await asyncio.gather(
                client.get_orderbook("spot", symbol),
                client.get_orderbook("linear", symbol),
                client.get_ticker("linear", symbol),
                client.get_funding_history(symbol, limit=max(settings.funding_persistence_periods, 20)),
            )
            now = utc_now()
            decisions = [
                risk.check_market_data_fresh(spot_book, now),
                risk.check_market_data_fresh(perp_book, now),
            ]
            signals = [
                funding_strategy.evaluate(
                    symbol=symbol,
                    linear_ticker=linear_ticker,
                    funding_history=funding_history,
                    spot_book=spot_book,
                    perp_book=perp_book,
                ),
                spread_strategy.evaluate_entry(symbol=symbol, spot_book=spot_book, perp_book=perp_book),
            ]
            spread_exit = spread_strategy.evaluate_exit(symbol=symbol, spot_book=spot_book, perp_book=perp_book)

            async with SessionLocal() as session:
                await persist_orderbook_snapshot(session, spot_book)
                await persist_orderbook_snapshot(session, perp_book)
                for decision in decisions:
                    if not decision.allowed:
                        session.add(_risk_event(symbol, decision))
                        await _notify_risk(symbol, decision, notify, gate, now)
                for signal in signals:
                    session.add(_signal_row(signal))
                    await _notify_signal(signal, notify, gate, now)
                entry_signal = next((signal for signal in signals if signal.action == "enter"), None)
                execution, execution_risk = await PaperExecutionService(settings, risk).process(
                    session,
                    symbol=symbol,
                    entry_strategy=StrategyName(entry_signal.strategy) if entry_signal is not None else None,
                    funding_signal_active=signals[0].action == "enter",
                    funding_history=funding_history,
                    exit=spread_exit.action == "exit",
                    spot_book=spot_book,
                    perp_book=perp_book,
                )
                if execution is not None and notify is not None:
                    await notify(render_paper_execution_message(execution))
                if execution_risk is not None and not execution_risk.allowed:
                    session.add(_risk_event(symbol, execution_risk))
                    await _notify_risk(symbol, execution_risk, notify, gate, now)
                await session.commit()
        except Exception as exc:
            log.warning("market_event_cycle_symbol_failed", symbol=symbol, error=str(exc))
            decision = RiskDecision(False, "market_api_error", str(exc), "warning")
            async with SessionLocal() as session:
                session.add(_risk_event(symbol, decision))
                await session.commit()
            await _notify_risk(symbol, decision, notify, gate, utc_now())


async def _symbols_for_cycle(settings: Settings, client: BybitPublicClient) -> list[str]:
    symbols = set(settings.watchlist)
    async with SessionLocal() as session:
        active_symbols = (
            await session.execute(select(Position.symbol).where(Position.is_open.is_(True)))
        ).scalars()
        symbols.update(active_symbols)
    if not settings.enable_funding_universe_scan:
        return sorted(symbols)
    try:
        linear_tickers, spot_tickers = await asyncio.gather(
            client.get_tickers("linear"),
            client.get_tickers("spot"),
        )
        candidates = select_funding_candidates(
            linear_tickers,
            {ticker.symbol for ticker in spot_tickers},
            limit=settings.funding_scan_limit,
            min_turnover_usdt=settings.min_funding_scan_turnover_usdt,
        )
        symbols.update(candidates)
        log.info("funding_universe_scanned", candidates=candidates, total_symbols=len(symbols))
    except Exception as exc:
        log.warning("funding_universe_scan_failed", error=str(exc))
    return sorted(symbols)


def _signal_row(signal: StrategySignal) -> Signal:
    return Signal(
        strategy=StrategyName(signal.strategy),
        symbol=signal.symbol,
        action=signal.action,
        strength=signal.strength,
        reason=signal.reason,
        payload=signal.payload,
    )


def _risk_event(symbol: str | None, decision: RiskDecision) -> RiskEvent:
    return RiskEvent(
        severity=decision.severity,
        code=decision.code,
        symbol=symbol,
        message=decision.message,
        payload={"allowed": decision.allowed},
    )


async def _notify_signal(
    signal: StrategySignal,
    notify: NotifyFn | None,
    gate: EventNotificationGate,
    now: datetime,
) -> None:
    if notify is None or signal.action not in {"enter", "exit"}:
        return
    key = f"signal:{signal.strategy}:{signal.symbol}:{signal.action}:{signal.reason}"
    if gate.allow(key, now):
        await notify(render_signal_message(signal))


async def _notify_risk(
    symbol: str | None,
    decision: RiskDecision,
    notify: NotifyFn | None,
    gate: EventNotificationGate,
    now: datetime,
) -> None:
    if notify is None or decision.allowed:
        return
    key = f"risk:{symbol}:{decision.code}:{decision.severity}"
    if gate.allow(key, now):
        await notify(render_risk_message(symbol, decision))

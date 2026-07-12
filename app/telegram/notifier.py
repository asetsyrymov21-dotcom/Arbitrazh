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
        "Bybit paper arbitrage bot started\n"
        "Mode: paper trading only\n"
        f"Watchlist: {symbols}\n"
        "Safety: real exchange orders are blocked"
    )

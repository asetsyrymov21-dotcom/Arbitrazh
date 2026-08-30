from dataclasses import dataclass
import asyncio

import httpx

from app.core.settings import Settings
from app.telegram.notifier import TelegramNotifier, render_startup_message


@dataclass
class FakePostClient:
    payload: dict[str, object] | None = None
    url: str | None = None

    async def post(self, url: str, json: dict[str, object]) -> httpx.Response:
        self.url = url
        self.payload = json
        return httpx.Response(200, json={"ok": True}, request=httpx.Request("POST", url))


def test_notifier_sends_to_configured_chat() -> None:
    client = FakePostClient()
    notifier = TelegramNotifier("token", "-100123", client)

    sent = asyncio.run(notifier.send("hello"))

    assert sent is True
    assert client.url == "https://api.telegram.org/bottoken/sendMessage"
    assert client.payload == {
        "chat_id": "-100123",
        "text": "hello",
        "disable_web_page_preview": True,
    }


def test_notifier_is_disabled_without_channel() -> None:
    settings = Settings(telegram_bot_token="token", telegram_notify_chat_id=None)

    assert TelegramNotifier.from_settings(settings, FakePostClient()) is None


def test_startup_message_includes_paper_safety() -> None:
    message = render_startup_message(["BTCUSDT"])

    assert "учебная торговля" in message
    assert "Реальные биржевые ордера технически заблокированы" in message

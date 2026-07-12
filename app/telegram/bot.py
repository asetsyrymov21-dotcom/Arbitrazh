from collections.abc import Awaitable, Callable

import structlog
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from app.core.settings import Settings

log = structlog.get_logger(__name__)


CommandCallback = Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[None]]


class TelegramPaperBot:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.paused = False

    def build_application(self) -> Application | None:
        if not self.settings.telegram_bot_token:
            log.info("telegram_disabled_no_token")
            return None
        app = Application.builder().token(self.settings.telegram_bot_token).build()
        for command in [
            "status",
            "portfolio",
            "positions",
            "signals",
            "trades",
            "pnl",
            "settings",
            "pause",
            "resume",
            "close_all_simulated",
            "report",
        ]:
            app.add_handler(CommandHandler(command, self._handle_command))
        return app

    async def _handle_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.effective_chat is None or update.message is None:
            return
        if self.settings.telegram_allowed_chat_ids and update.effective_chat.id not in self.settings.telegram_allowed_chat_ids:
            await update.message.reply_text("Unauthorized")
            return
        command = (update.message.text or "").split()[0].removeprefix("/")
        if command == "pause":
            self.paused = True
        elif command == "resume":
            self.paused = False
        elif command == "close_all_simulated":
            await update.message.reply_text("Simulated close-all requested; no real exchange orders exist.")
            return
        await update.message.reply_text(self._render(command))

    def _render(self, command: str) -> str:
        if command == "status":
            return f"paper bot {'paused' if self.paused else 'running'}"
        if command == "settings":
            return "paper-only mode; watchlist=" + ",".join(self.settings.watchlist)
        return f"{command}: API dashboard has the current paper-trading state."


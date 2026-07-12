from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

import httpx
from fastapi import FastAPI

from app.api.routes import router
from app.core.logging import configure_logging
from app.core.settings import settings
from app.telegram.notifier import TelegramNotifier, render_startup_message


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    async with httpx.AsyncClient(timeout=10) as client:
        notifier = TelegramNotifier.from_settings(settings, client)
        if notifier is not None:
            await notifier.send(render_startup_message(settings.watchlist))
    yield


app = FastAPI(title="Bybit Paper Arbitrage", version="0.1.0", lifespan=lifespan)
app.include_router(router)
